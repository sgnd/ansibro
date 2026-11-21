#!/usr/bin/env python3
"""dejavu: the handover pack for a system built with ansibro.

Run it with ansibro's own Python, inside the ansibro folder that ran ./install.sh:

    .venv/bin/python <skill>/scripts/handover.py <command> [--out DIR] [--config FILE]

Commands:
    doctor      check this machine: the ansibro folder, Python, the tools
    init        make the output folder and handover.yml, the answers ansibro cannot know
    facts       read the facts from ansibro (no network, no SSH) into facts.json
    check       run ansibro's own acceptance test on the servers (read-only; ask first)
    build       write the documents (Markdown + PDF), the credentials file and SHA256SUMS
    scan        search the output for secret values (build does it too)
    passphrase  show the credentials file's passphrase (only in a real terminal)

Every line starts with "ok:", "warning: [id]", "needs the user: [id]" or "failed: [id]".
Exit codes: 0 ok, 1 failed, 2 wrong usage, 3 the user must act, 4 state/ changed, 5 a secret leaked.

Secret values never reach a document, the screen or a command line: they are read into
memory only to build the credentials file and to search the output for leaks.
"""

import argparse
import base64
import datetime
import hashlib
import io
import ipaddress
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse

import jinja2
import yaml

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(SKILL, "assets")
# The PDF tools, pinned. mise downloads them once when they are not on PATH.
TOOLS = {"pandoc": "3.13", "typst": "0.15.1", "d2": "0.9.0"}
TOOL_MIN = {"pandoc": (3, 1, 2), "typst": (0, 14, 0), "d2": (0, 7, 0)}
KEEPASSXC_MIN = (2, 7, 6)
LANGS = ("id", "en")
OSES = ("windows", "macos", "linux")
MIN_SECRET = 6  # shorter values cannot be searched for safely
TEST = os.environ.get("DEJAVU_TEST") == "1"


# ---------- output ------------------------------------------------------------------

class Stop(Exception):
    """Stops the command with an exit code. The message is already printed."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def say(kind, msg, ident=None):
    tag = f" [{ident}]" if ident else ""
    print(f"{kind}{tag}: {msg}", flush=True)


def ok(msg):
    say("ok", msg)


def warning(ident, msg):
    say("warning", msg, ident)


def needs_user(ident, msg):
    say("needs the user", msg, ident)
    raise Stop(3)


def failed(ident, msg, code=1):
    say("failed", msg, ident)
    raise Stop(code)


# ---------- small helpers -----------------------------------------------------------

def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def version():
    """The skill version: metadata.version in SKILL.md (the one version source)."""
    with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
        front = f.read().split("---")[1]
    return yaml.safe_load(front)["metadata"]["version"]


def slugify(text):
    text = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return text or "client"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def run(cmd, **kw):
    """Run a command without a shell. Input (secrets) only through `input`, never argv."""
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(cmd, check=False, **kw)


def in_git_tree(path):
    p = path
    while not os.path.isdir(p):
        p = os.path.dirname(p)
    try:
        r = run(["git", "-C", p, "rev-parse", "--is-inside-work-tree"])
    except FileNotFoundError:
        return False
    return r.returncode == 0 and r.stdout.strip() == "true"


def today():
    """The date of the documents. Tests fix it with HANDOVER_TODAY."""
    fixed = os.environ.get("HANDOVER_TODAY")
    return datetime.date.fromisoformat(fixed) if fixed else datetime.date.today()


# ---------- ansibro ----------------------------------------------------------------

class Ansibro:
    """The ansibro folder that ran ./install.sh: its code, its config and its state/."""

    def __init__(self, folder, config):
        self.dir = os.path.abspath(folder)
        self.config = os.path.abspath(os.path.join(self.dir, config))
        self.state = os.path.join(self.dir, "state")
        self.state_age = os.path.join(self.dir, "state.age")
        self.key = os.environ.get("ANSIBRO_KEY") or os.path.expanduser("~/.config/ansibro/age.key")
        self.venv_bin = os.path.dirname(sys.executable)

    def check_folder(self):
        for f in ("inventory.py", "catalog.yml", "site.yml", "versions.yml"):
            if not os.path.isfile(os.path.join(self.dir, f)):
                failed("not-ansibro", f"{self.dir} is not an ansibro folder ({f} is missing). "
                       "Run dejavu inside the ansibro folder that ran ./install.sh, or pass --ansibro DIR.")
        if not os.path.isfile(self.config):
            needs_user("no-config", f"{os.path.basename(self.config)} is not in {self.dir}. "
                       "Which config was installed? Pass it with --config FILE.")

    def env(self):
        env = dict(os.environ, ANSIBRO_CONFIG=self.config, ANSIBLE_NOCOLOR="1",
                   ANSIBLE_DEPRECATION_WARNINGS="False", ANSIBLE_CALLBACK_RESULT_FORMAT="json")
        env["PATH"] = self.venv_bin + os.pathsep + env.get("PATH", "")
        return env

    def version(self):
        """ansibro's version: the git tag, else the newest CHANGELOG heading."""
        describe, dirty = None, False
        r = run(["git", "-C", self.dir, "describe", "--tags", "--always", "--dirty"])
        if r.returncode == 0:
            describe = r.stdout.strip()
            dirty = describe.endswith("-dirty")
        ver = None
        try:
            with open(os.path.join(self.dir, "CHANGELOG.md"), encoding="utf-8") as f:
                for line in f:
                    m = re.match(r"^## (\d+\.\d+\.\d+)", line)
                    if m:
                        ver = m.group(1)
                        break
        except OSError:
            pass
        return {"version": ver, "describe": describe, "dirty": dirty}

    # --- the resolved facts, from ansibro's own code ---

    def inventory(self, recorded=None):
        if recorded:
            return load_json(recorded, self.dir)
        r = run([sys.executable, os.path.join(self.dir, "inventory.py"), "--list"], cwd=self.dir, env=self.env())
        if r.returncode != 0:
            failed("config", (r.stderr or r.stdout).strip() or "inventory.py failed")
        return json.loads(r.stdout)

    def group_vars(self, recorded=None):
        """ansibro's own rules (traefik_nodes, admin_sso, ...) through one debug call.
        The debug module does not connect anywhere, so no SSH. secrets_dir points to an empty
        temporary folder, so even a mistaken password lookup cannot write into state/."""
        if recorded:
            return load_json(recorded, self.dir)
        names = ["swarm_leader", "traefik_nodes", "admin_sso", "database_app", "database_ha", "database_host",
                 "database_port", "postgres_patroni", "mariadb_galera", "cache_app", "cache_ha", "monitoring_app",
                 "swarm_app_constraint", "registry_addr"]
        expr = "{{ {" + ", ".join(f'"{n}": {n}' for n in names) + "} }}"
        before = self.state_listing()
        with tempfile.TemporaryDirectory() as tmp:
            ansible = os.path.join(self.venv_bin, "ansible")
            if not os.path.exists(ansible):
                ansible = shutil.which("ansible") or ansible
            r = run([ansible, "managers[0]", "-m", "ansible.builtin.debug", "-e", f"secrets_dir={tmp}",
                     "-a", f"msg={expr}"], cwd=self.dir, env=self.env())
            wrote = os.listdir(tmp)
        if wrote or self.state_listing() != before:
            failed("state-guard", "a password lookup ran while reading the facts. Nothing was changed in state/, "
                   "but please report this as a dejavu bug.", code=4)
        out = r.stdout
        if r.returncode != 0 or "=>" not in out:
            failed("ansible", "ansible could not read ansibro's settings: " + (r.stderr or out).strip()[-400:])
        return json.loads(out[out.index("=>") + 2:])["msg"]

    def state_listing(self):
        """Names and change times under state/, to prove that reading changed nothing."""
        found = []
        for root, _dirs, files in os.walk(self.state):
            for f in files:
                p = os.path.join(root, f)
                found.append((os.path.relpath(p, self.state), os.stat(p).st_mtime_ns))
        return sorted(found)

    # --- state/: plain, or encrypted as state.age ---

    def state_mode(self):
        plain, age = os.path.isdir(self.state), os.path.isfile(self.state_age)
        if plain and age:
            failed("state-both", "both state/ and state.age are here. Do not delete either: they hold the "
                   "passwords. Move one of them to a backup folder, then run dejavu again.")
        if age:
            if not os.path.isfile(self.key):
                needs_user("age-key", f"state.age is encrypted, but its key {self.key} is not on this machine. "
                           "Ask the user for the key file, or set ANSIBRO_KEY=/path/to/age.key.")
            return "age"
        return "plain" if plain else "none"

    def _age_members(self, want):
        """Read files from state.age straight into memory: nothing is written to disk."""
        if not shutil.which("age"):
            needs_user("age", "state.age is encrypted with age, but age is not installed. "
                       "macOS: brew install age. Linux: sudo apt-get install age")
        p = subprocess.Popen(["age", "-d", "-i", self.key, self.state_age], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
        data = {}
        with tarfile.open(fileobj=p.stdout, mode="r|") as tar:
            for m in tar:
                if m.isfile() and want(m.name):
                    data[m.name] = tar.extractfile(m).read()
        if p.wait() != 0:
            failed("age", "age could not open state.age: " + p.stderr.read().decode(errors="replace").strip())
        return data

    def secret_names(self):
        mode = self.state_mode()
        if mode == "plain":
            d = os.path.join(self.state, "secrets")
            return sorted(os.listdir(d)) if os.path.isdir(d) else []
        if mode == "age":
            members = self._age_members(lambda n: n.startswith("state/secrets/"))
            return sorted(n.split("/", 2)[2] for n in members)
        return []

    def secret_values(self):
        """name -> value, in memory. Only for the credentials file and the leak scan."""
        mode = self.state_mode()
        values = {}
        if mode == "plain":
            d = os.path.join(self.state, "secrets")
            for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
                with open(os.path.join(d, name), encoding="utf-8", errors="replace") as f:
                    values[name] = f.read().strip()
        elif mode == "age":
            for n, raw in self._age_members(lambda n: n.startswith("state/secrets/")).items():
                values[n.split("/", 2)[2]] = raw.decode(errors="replace").strip()
        return values

    def last_install(self):
        """The date of the last install: when state/summary.md was written (never opened)."""
        for p in (os.path.join(self.state, "summary.md"), self.state_age):
            if os.path.exists(p):
                return datetime.date.fromtimestamp(os.stat(p).st_mtime).isoformat()
        return None

    # --- the passphrase of the credentials file: kept in state/handover/, encrypted with state ---

    def passphrase_path(self, slug):
        return os.path.join(self.state, "handover", f"{slug}.passphrase")

    def read_passphrase(self, slug):
        mode = self.state_mode()
        if mode == "plain":
            p = self.passphrase_path(slug)
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    return f.read().strip()
        elif mode == "age":
            name = f"state/handover/{slug}.passphrase"
            got = self._age_members(lambda n: n == name)
            if name in got:
                return got[name].decode().strip()
        return None

    def write_passphrase(self, slug, phrase):
        mode = self.state_mode()
        if mode == "none":
            needs_user("no-state", "there is no state/ here, so there are no passwords to hand over. "
                       "Run dejavu in the folder that ran ./install.sh.")

        def write():
            d = os.path.dirname(self.passphrase_path(slug))
            os.makedirs(d, mode=0o700, exist_ok=True)
            os.chmod(d, 0o700)
            fd = os.open(self.passphrase_path(slug), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(phrase + "\n")

        if mode == "plain":
            write()
            return
        # Encrypted state: open it with ansibro's own script, write, and always close it again.
        script = os.path.join(self.dir, "scripts", "state.sh")
        r = run([script, "open"], cwd=self.dir)
        if r.returncode != 0:
            failed("state-open", r.stderr.strip() or "scripts/state.sh open failed")
        old = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)}

        def close(*_):
            run([script, "close"], cwd=self.dir)
            raise Stop(130)

        for s in old:
            signal.signal(s, close)
        try:
            write()
        finally:
            for s, h in old.items():
                signal.signal(s, h)
            r = run([script, "close"], cwd=self.dir)
            if r.returncode != 0:
                failed("state-close", "could not encrypt state/ again. Run scripts/state.sh close now. " + r.stderr.strip())


def load_json(path, ansibro=None):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if ansibro:  # a recording from tests/record.py: its folder is written as @ANSIBRO@
        text = text.replace("@ANSIBRO@", ansibro)
    return json.loads(text)


# ---------- facts --------------------------------------------------------------------

def redact_repository(repo):
    """Keep where the backups go, never the user and password in it."""
    if not repo:
        return None
    kind = repo.split(":", 1)[0] if ":" in repo and not repo.startswith("/") else "local"
    rest = repo.split(":", 1)[1] if kind != "local" else repo
    host = None
    if "://" in rest:
        u = urllib.parse.urlsplit(rest)
        host = u.hostname
        rest = f"{u.scheme}://{host}{':' + str(u.port) if u.port else ''}{u.path}"
    return {"kind": kind, "host": host, "where": rest if kind != "local" else repo}


def webhook_kind(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    if "slack.com" in host:
        return "slack"
    if "discord" in host:
        return "discord"
    return "webhook"


def matches(cond, f):
    """Is a condition from apps.yml true for this system?"""
    apps = f["app_names"]
    return {
        "always": True, "optional": True,
        "patroni": bool(f["gv"].get("postgres_patroni")),
        "galera": bool(f["gv"].get("mariadb_galera")),
        "ha_db": bool(f["gv"].get("database_ha")),
        "ha_cache": bool(f["gv"].get("cache_ha")),
        "keycloak_login": f["admin_sso"] == "keycloak",
        "victoria": "victoria" in apps,
        "backup": f["backup"]["enabled"],
        "k3s": f["orchestrator"] == "k3s",
        "wireguard": f["wireguard"],
    }[cond]


def build_facts(ab, args, data):
    """Everything the documents say about the system, without a single secret value."""
    inv = ab.inventory(getattr(args, "inventory_json", None))
    gv = ab.group_vars(getattr(args, "groupvars_json", None))
    cfg = inv["all"]["vars"]
    hosts = inv["_meta"]["hostvars"]
    known = data["apps"]
    warnings = []

    def warn(ident, **kw):
        warnings.append({"id": ident, **kw})

    # Config keys dejavu knows. A new ansibro setting is left out with a warning, never an error.
    documented = {"acme_email", "ansible_port", "ansible_ssh_private_key_file", "ansible_user", "app_nodes",
                  "apps", "backup", "bundle", "catalog", "docker_packages", "domain", "images", "k3s",
                  "kong_subnet", "monitoring", "offline", "orchestrator", "registry_port", "ssh",
                  "swarm_address_pool", "swarm_apps", "timezone", "tls", "wireguard", "wireguard_port",
                  "admin_allow_from", "firewall_allow", "acme_server", "acme_ca_cert", "tls_cert", "tls_key"}
    for key in sorted(set(cfg) - documented):
        warn("not-documented", key=key)

    managers = inv["managers"]["hosts"]
    first = managers[0]
    traefik_nodes = gv.get("traefik_nodes") or []
    nodes = []
    for name in inv["_meta"]["hostvars"]:
        h = hosts[name]
        nodes.append({
            "name": name, "ip": h["node_ip"], "host": h["node_host"], "role": h["node_role"],
            "tier": (h.get("node_labels") or {}).get("tier", ""), "apps": h.get("node_apps", []),
            "first": name == first, "traefik": name in traefik_nodes and "traefik" in cfg["apps"],
        })

    apps_cfg = cfg["apps"]
    app_nodes = cfg.get("app_nodes", {})
    images = cfg.get("images", {})
    ssh = cfg.get("ssh") or {}
    backup_cfg = cfg.get("backup") or {}
    mon_cfg = cfg.get("monitoring") or {}
    f = {
        "orchestrator": cfg["orchestrator"], "domain": cfg["domain"], "tls": cfg["tls"],
        "app_names": list(apps_cfg), "gv": gv, "admin_sso": gv.get("admin_sso") or "",
        "wireguard": bool(cfg.get("wireguard")),
        "backup": {"enabled": bool(backup_cfg)},
    }

    apps = []
    for name, entry in cfg["catalog"].items():  # catalog order: the order ansibro installs them
        if name not in apps_cfg:
            continue
        info = known.get(name)
        if info is None:
            warn("unknown-app", app=name)
        target = apps_cfg[name]
        on = app_nodes.get(name) or ([] if target == "swarm" else [target])
        primary = hosts[on[0]]["node_ip"] if on else ""
        web = []
        for w in (info or {}).get("web", []):
            if w.get("when") and not matches(w["when"], f):
                continue
            web.append({**{k: v for k, v in w.items() if k != "when"},
                        "url": f"https://{w['host']}.{cfg['domain']}{w['path']}"})
        app_images = []
        for key in (info or {}).get("images", []):
            if key in images:
                i = images[key]
                app_images.append({"key": key, "repo": i["repo"], "tag": str(i["tag"]),
                                   "digest": i.get("digest", "")[7:19]})
        if name == "postgres":  # only the images of the layout that is installed
            ha = len(on) > 1
            app_images = [i for i in app_images if (i["key"] in ("spilo", "etcd", "haproxy")) == ha]
        if name == "mariadb" and len(on) < 2:
            app_images = [i for i in app_images if i["key"] != "haproxy"]
        if name == "keycloak" and f["admin_sso"] != "keycloak":
            app_images = [i for i in app_images if i["key"] != "oauth2-proxy"]
        apps.append({
            "name": name, "category": entry.get("category", ""), "license": entry.get("license", ""),
            "cluster": target == "swarm", "nodes": on, "primary_ip": primary, "ha": len(on) > 1,
            "known": info is not None, "info": entry.get("info", "").replace("<domain>", cfg["domain"])
            .replace("<ip>", primary),
            "about": (info or {}).get("about"), "web": web if "traefik" in apps_cfg else [],
            "ports": [{"port": p["port"], "use": p["use"]} for p in (info or {}).get("ports", [])],
            "data": [f"/opt/ansibro/{d}" for d in (info or {}).get("data", [name])],
            "backup": (info or {}).get("backup", "paused") if backup_cfg else "none",
            "health": (info or {}).get("health", ""), "laptop": (info or {}).get("laptop", "none"),
            "notes": [{"id": n["id"], "en": n["en"]} for n in (info or {}).get("notes", [])
                      if not n.get("when") or matches(n["when"], f)], "images": app_images,
            "version": app_images[0]["tag"] if app_images else "",
        })
        spilo = next((i for i in app_images if i["key"] == "spilo"), None)
        if spilo:  # PostgreSQL with Patroni: the PostgreSQL version is in the image name (spilo-18)
            apps[-1]["version"] = f"{spilo['repo'].rsplit('-', 1)[-1]} (Spilo {spilo['tag']})"
        if name == "traefik" and cfg["orchestrator"] == "k3s":
            apps[-1]["version"] = f"k3s {cfg.get('k3s', {}).get('version', '')}"
            apps[-1]["images"] = []

    components = []
    for name, c in data["components"].items():
        if c["when"] != "always" and not matches(c["when"], f):
            continue
        img = images.get(c["image"]) if c.get("image") else None
        ver = str(img["tag"]) if img else ""
        if name == "k3s":
            ver = cfg.get("k3s", {}).get("version", "")
        port = int(gv.get("database_port") or c["port"]) if name == "database-proxy" else c["port"]
        components.append({"name": name, "where": c["where"], "port": port, "version": ver,
                           "license": c.get("license") or "", "about": c["about"]})

    # Backup: where it goes, never its keys.
    backup = {"enabled": bool(backup_cfg)}
    if backup_cfg:
        backup.update(redact_repository(backup_cfg.get("repository")) or {})
        backup.update({"time": str(backup_cfg.get("time", "02:00")),
                       "keep": {"daily": backup_cfg.get("keep_daily", 7), "weekly": backup_cfg.get("keep_weekly", 4),
                                "monthly": backup_cfg.get("keep_monthly", 6)}})
    # Alert channels: their kind and host only.
    channels = []
    if mon_cfg.get("telegram"):
        channels.append({"kind": "telegram"})
    if mon_cfg.get("email"):
        e = mon_cfg["email"]
        channels.append({"kind": "email", "to": e.get("to"), "host": str(e.get("smarthost", "")).split(":")[0]})
    if mon_cfg.get("webhook"):
        channels.append({"kind": webhook_kind(mon_cfg["webhook"]), "host": urllib.parse.urlsplit(mon_cfg["webhook"]).hostname})
    monitoring = {"app": gv.get("monitoring_app") or ("beszel" if "beszel" in apps_cfg else ""),
                  "channels": channels,
                  "heartbeat": urllib.parse.urlsplit(mon_cfg["heartbeat_url"]).hostname if mon_cfg.get("heartbeat_url") else None,
                  "keep_days": mon_cfg.get("keep_days", 30) if mon_cfg else None,
                  "uptimekuma": "uptimekuma" in apps_cfg}

    # Secrets: names only. Which are expected, which are left over from removed apps.
    names = ab.secret_names()
    secrets = []
    groups_of = {e["secret"]: e for e in data["entries"]}
    users_of = {e.get("user_secret"): e["secret"] for e in data["entries"] if e.get("user_secret")}
    expected = set()
    for name, s in data["secrets"].items():
        owner_installed = s["app"] in apps_cfg or s["app"] in ("registry", "etcd", "backup", "k3s")
        if s["app"] == "etcd":
            owner_installed = "postgres" in apps_cfg
        if owner_installed and s["when"] not in ("optional",) and matches(s["when"], f):
            expected.add(name)
    for name in sorted(set(names) | expected):
        s = data["secrets"].get(name)
        if s is None:
            status = "unknown"
        elif name not in names:
            status = "missing"
        elif name in expected or (s["when"] == "optional" and (s["app"] in apps_cfg or s["app"] == "victoria")):
            status = "present"
        else:
            status = "stale"
        e = groups_of.get(name)
        if name in users_of:  # a user name stored in another entry (S3 access keys)
            e = groups_of[users_of[name]]
        group = e["group"] if e and status == "present" else ("old" if status == "stale" else "internal")
        secrets.append({
            "name": name, "status": status, "app": s["app"] if s else "", "change": s["change"] if s else "internal",
            "audience": s["audience"] if s else "internal", "verified": s["verified"] if s else False,
            "group": group, "title": e["title"] if e else name,
            "user": ((e.get("user") or (e.get("user_prefix", "") + "… (access key)" if e.get("user_secret") else ""))
                     .replace("{domain}", cfg["domain"]) if e and status == "present" else ""),
        })
        if status == "missing":
            warn("missing-secret", name=name)
        elif status == "stale":
            warn("stale-secret", name=name)
        elif status == "unknown":
            warn("unknown-secret", name=name)

    # Secrets inside config.yml: their names only.
    config_secrets = []
    if backup_cfg.get("s3_access_key"):
        config_secrets += ["backup.s3_access_key", "backup.s3_secret_key"]
    if "@" in str(backup_cfg.get("repository", "")).split("://")[-1].split("/")[0]:
        config_secrets.append("backup.repository")
    if (mon_cfg.get("telegram") or {}).get("bot_token"):
        config_secrets.append("monitoring.telegram.bot_token")
    if (mon_cfg.get("email") or {}).get("password"):
        config_secrets.append("monitoring.email.password")
    if mon_cfg.get("webhook"):
        config_secrets.append("monitoring.webhook")
    if mon_cfg.get("heartbeat_url"):
        config_secrets.append("monitoring.heartbeat_url")

    alerts = read_alerts(ab, apps_cfg, gv, f)

    # Laptop tunnels: one local port per private service, 10000 + its port (+1 per extra server).
    tunnels = []
    for a in apps:
        for p in a["ports"]:
            for i, node in enumerate(a["nodes"]):
                tunnels.append({"app": a["name"], "use": p["use"], "node": node, "ip": hosts[node]["node_ip"],
                                "port": p["port"], "local": 10000 + p["port"] + i})
    if cfg["orchestrator"] == "k3s":
        tunnels.append({"app": "k3s", "use": "Kubernetes API", "node": first, "ip": hosts[first]["node_ip"],
                        "port": 6443, "local": 16443})

    tls_cert = None
    if cfg.get("tls_cert") and os.path.isfile(cfg["tls_cert"]):
        tls_cert = read_cert(cfg["tls_cert"])
        days = (datetime.date.fromisoformat(tls_cert["not_after"]) - today()).days
        if days < 90:
            warn("custom-cert-expires", days=days)
    ca_file = cfg.get("acme_ca_cert") if cfg.get("acme_ca_cert") and os.path.isfile(cfg.get("acme_ca_cert")) else None

    # Warnings that need a decision from the user.
    if not ssh.get("allow_from"):
        warn("allowlist-empty", list="ssh.allow_from")
    if not cfg.get("admin_allow_from"):
        warn("allowlist-empty", list="admin_allow_from")
    if cfg["tls"] == "selfsigned":
        warn("tls-selfsigned")
    if not backup_cfg:
        warn("no-backup")
    elif monitoring["app"] != "victoria":
        warn("backup-no-alert")
    if not monitoring["app"]:
        warn("no-monitoring")
    if "uptimekuma" in apps_cfg:
        warn("uptimekuma-notifications-manual")
    if "beszel" in apps_cfg:
        warn("beszel-alerts-manual")
    if "swarmpit" in apps_cfg:
        warn("swarmpit-old-databases")

    av = ab.version()
    rng = data_range()
    if av["version"] and not in_range(av["version"], rng):
        warn("ansibro-untested-version", version=av["version"], tested=rng)
    if av["dirty"]:
        warn("ansibro-dirty")
    configs = [c for c in os.listdir(ab.dir) if re.match(r"^config(\..+)?\.yml$", c) and c != "config.example.yml"]
    if len(configs) > 1:
        warn("shared-state", configs=sorted(configs))

    facts = {
        "dejavu": version(), "ansibro": av, "config": os.path.splitext(os.path.basename(ab.config))[0],
        "last_install": ab.last_install(), "state": ab.state_mode(),
        "orchestrator": cfg["orchestrator"], "domain": cfg["domain"], "tls": cfg["tls"],
        "acme_email": cfg.get("acme_email"), "acme_server": urllib.parse.urlsplit(cfg["acme_server"]).hostname
        if cfg.get("acme_server") else None, "ca_file": bool(ca_file), "timezone": cfg.get("timezone") or "UTC",
        "offline": bool(cfg.get("offline")),
        "ssh": {"user": cfg.get("ansible_user", "ubuntu"), "port": cfg.get("ansible_port", 22),
                "allow_from": list(ssh.get("allow_from") or [])},
        "admin_allow_from": list(cfg.get("admin_allow_from") or []),
        "firewall_allow": [{k: v for k, v in r.items()} for r in (cfg.get("firewall_allow") or [])],
        "wireguard": bool(cfg.get("wireguard")), "wireguard_port": cfg.get("wireguard_port", 51820),
        "registry_addr": gv.get("registry_addr"),
        "nodes": nodes, "first_manager": first, "traefik_nodes": traefik_nodes if "traefik" in apps_cfg else [],
        "admin_sso": f["admin_sso"],
        "database": {"app": gv["database_app"], "ha": bool(gv.get("database_ha")), "host": gv.get("database_host"),
                     "port": int(gv.get("database_port") or 0)} if gv.get("database_app") else None,
        "cache": {"app": gv["cache_app"], "ha": bool(gv.get("cache_ha"))} if gv.get("cache_app") else None,
        "apps": apps, "components": components, "backup": backup, "monitoring": monitoring, "alerts": alerts,
        "secrets": secrets, "config_secrets": config_secrets, "tunnels": tunnels, "tls_cert": tls_cert,
        "versions": {"docker": [p.split("=")[0] + " " + p.split("=")[1].rstrip("*").split(":")[-1]
                                for p in cfg.get("docker_packages", [])],
                     "k3s": cfg.get("k3s", {}).get("version") if cfg["orchestrator"] == "k3s" else None},
        "warnings": warnings,
        "sources": {
            "nodes, apps, domain, tls, ssh, allow-lists, backup, monitoring, versions": "inventory.py --list",
            "traefik_nodes, admin_sso, database, cache, monitoring app": "group_vars/all.yml (ansible debug)",
            "alerts": "roles/observability/files/alerts.yml",
            "pages, ports, data, backup kind, change of passwords": "dejavu assets/apps.yml",
            "secret names": "state/secrets (names only)" if ab.state_mode() != "age" else "state.age (names only)",
            "last install": "the date of state/summary.md (never opened)",
            "ansibro version": "git describe / CHANGELOG.md",
        },
    }
    return facts, ca_file


def data_range():
    with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as f:
        front = yaml.safe_load(f.read().split("---")[1])
    return front["metadata"]["ansibro"]


def in_range(ver, rng):
    """'1.2.0' in '>=1.2.0 <2'."""
    v = tuple(int(x) for x in ver.split("."))
    for part in rng.split():
        m = re.match(r"(>=|<)(\d+(?:\.\d+)*)", part)
        if not m:
            continue
        w = tuple(int(x) for x in m.group(2).split("."))
        w = w + (0,) * (3 - len(w))
        if m.group(1) == ">=" and v < w or m.group(1) == "<" and v >= w:
            return False
    return True


def read_alerts(ab, apps_cfg, gv, f):
    """ansibro's alert rules that apply to this system (only with victoria)."""
    if gv.get("monitoring_app") != "victoria":
        return []
    path = os.path.join(ab.dir, "roles", "observability", "files", "alerts.yml")
    if not os.path.isfile(path):
        return []
    applies = {"monitoring": True, "servers": True, "apps": True, "k3s": f["orchestrator"] == "k3s",
               "backup": f["backup"]["enabled"], "wireguard": f["wireguard"],
               "databases": bool(gv.get("database_app") or gv.get("cache_app")),
               "secrets": "openbao" in apps_cfg}
    out = []
    for group in load_yaml(path).get("groups", []):
        if not applies.get(group["name"], True):
            continue
        for rule in group.get("rules", []):
            if not alert_applies(rule["alert"], apps_cfg, gv, f):
                continue
            sev = (rule.get("labels") or {}).get("severity", "")
            if sev == "none":
                continue
            summary = re.sub(r"\{\{\s*\$labels\.(\w+)\s*\}\}", r"<\1>", (rule.get("annotations") or {}).get("summary", ""))
            summary = re.sub(r"\{\{[^}]*\}\}", "…", summary)
            out.append({"group": group["name"], "name": rule["alert"], "severity": sev,
                        "for": rule.get("for", ""), "summary": summary.strip()})
    return out


def alert_applies(name, apps_cfg, gv, f):
    """Some rules in a group are about one app or one orchestrator only."""
    n = name.lower()
    for prefix, applies in (("postgres", "postgres" in apps_cfg), ("patroni", bool(gv.get("postgres_patroni"))),
                            ("mariadb", "mariadb" in apps_cfg), ("galera", bool(gv.get("mariadb_galera"))),
                            ("cache", bool(gv.get("cache_app"))), ("redis", "redis" in apps_cfg),
                            ("valkey", "valkey" in apps_cfg), ("swarm", f["orchestrator"] == "swarm"),
                            ("k3s", f["orchestrator"] == "k3s"), ("openbao", "openbao" in apps_cfg),
                            ("garage", "garage" in apps_cfg), ("traefik", "traefik" in apps_cfg),
                            ("uptimekuma", "uptimekuma" in apps_cfg)):
        if n.startswith(prefix):
            return applies
    return True


def read_cert(path):
    """Public facts of a certificate: who it is for, who signed it, until when."""
    from cryptography import x509
    with open(path, "rb") as fh:
        cert = x509.load_pem_x509_certificate(fh.read())
    try:
        sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)
    except x509.ExtensionNotFound:
        sans = []
    end = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
    return {"subject": cert.subject.rfc4514_string(), "issuer": cert.issuer.rfc4514_string(),
            "sans": sans, "not_after": end.date().isoformat()}


# ---------- answers (handover.yml) ----------------------------------------------------

ANSWER_KEYS = {
    "lang", "environment", "slug", "document", "bast", "client", "vendor", "servers", "dns", "people",
    "ssh_handover", "state_owner", "password_change_days", "vendor_access_end", "delivery", "support",
    "tls", "font", "known_issues", "out_of_scope", "extra_apps", "notes", "summary_note", "attach",
    "restore_drill", "provider",
}
REQUIRED_FINAL = [
    ("bast", "number"), ("bast", "date"), ("bast", "place"), ("client", "name"), ("client", "signer", "name"),
    ("client", "signer", "title"), ("vendor", "name"), ("vendor", "signer", "name"), ("vendor", "signer", "title"),
    ("delivery", "kdbx_channel"), ("delivery", "passphrase_channel"), ("delivery", "recipient"),
]


def dig(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def load_answers(out):
    path = os.path.join(out, "handover.yml")
    if not os.path.isfile(path):
        needs_user("no-answers", f"{path} is missing. Run init first, then fill it in with the user.")
    a = load_yaml(path)
    unknown = sorted(set(a) - ANSWER_KEYS)
    if not unknown:
        a = with_defaults(a)
    if unknown:
        failed("answers", f"handover.yml has unknown settings: {', '.join(unknown)} (typo?)", code=2)
    langs = a.get("lang") or ["id"]
    langs = [langs] if isinstance(langs, str) else list(langs)
    bad = [x for x in langs if x not in LANGS]
    if bad:
        failed("answers", f"lang must be id, en or [id, en], got {bad}", code=2)
    a["lang"] = langs
    people = a.get("people") or []
    for p in people:
        if p.get("os") and p["os"] not in OSES:
            failed("answers", f"people: os must be one of {', '.join(OSES)}, got {p['os']}", code=2)
        if p.get("persona") and p["persona"] not in ("viewer", "operator", "successor"):
            failed("answers", f"people: persona must be viewer, operator or successor, got {p['persona']}", code=2)
    if a.get("ssh_handover", "client_key") not in ("client_key", "generated"):
        failed("answers", "ssh_handover must be client_key or generated", code=2)
    if a.get("state_owner", "vendor") not in ("vendor", "client"):
        failed("answers", "state_owner must be vendor or client", code=2)
    if dig(a, "bast", "stage") not in (None, "single", "pho", "fho"):
        failed("answers", "bast.stage must be single, pho or fho", code=2)
    if dig(a, "bast", "first_party") not in (None, "vendor", "client"):
        failed("answers", "bast.first_party must be vendor or client", code=2)
    return a


def with_defaults(a):
    """Every key of handover.example.yml exists, so templates never meet a missing one."""
    with open(os.path.join(ASSETS, "handover.example.yml"), encoding="utf-8") as f:
        defaults = yaml.safe_load(f.read().replace("  # SERVERS", "")) or {}

    def merge(base, top):
        if isinstance(base, dict) and isinstance(top, dict):
            return {**base, **{k: merge(base.get(k), v) for k, v in top.items()}}
        return base if top is None and isinstance(base, (dict, list)) else top

    return merge(defaults, a)


def missing_required(a):
    return [".".join(p) for p in REQUIRED_FINAL if dig(a, *p) in (None, "")]


def slug_of(a, facts):
    if a.get("slug"):
        return slugify(a["slug"])
    base = dig(a, "client", "short") or dig(a, "client", "name") or facts["domain"].split(".")[0]
    return slugify(base)


# ---------- language helpers ----------------------------------------------------------

DAYS = {"id": ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"],
        "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]}
MONTHS = {"id": ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September",
                 "Oktober", "November", "Desember"],
          "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                 "October", "November", "December"]}
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
ONES_ID = ["nol", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan", "sepuluh", "sebelas"]
ONES_EN = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
           "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
TENS_EN = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def terbilang(n):
    """A number in Indonesian words, 0 to 9999: 2026 -> dua ribu dua puluh enam."""
    n = int(n)
    if n < 12:
        return ONES_ID[n]
    if n < 20:
        return f"{ONES_ID[n - 10]} belas"
    if n < 100:
        rest = n % 10
        return f"{ONES_ID[n // 10]} puluh" + (f" {ONES_ID[rest]}" if rest else "")
    if n < 200:
        return "seratus" + (f" {terbilang(n - 100)}" if n > 100 else "")
    if n < 1000:
        rest = n % 100
        return f"{ONES_ID[n // 100]} ratus" + (f" {terbilang(rest)}" if rest else "")
    if n < 2000:
        return "seribu" + (f" {terbilang(n - 1000)}" if n > 1000 else "")
    if n < 10000:
        rest = n % 1000
        return f"{ONES_ID[n // 1000]} ribu" + (f" {terbilang(rest)}" if rest else "")
    raise ValueError("terbilang: up to 9999")


def words_en(n):
    n = int(n)
    if n < 20:
        return ONES_EN[n]
    if n < 100:
        return TENS_EN[n // 10] + (f"-{ONES_EN[n % 10]}" if n % 10 else "")
    if n < 1000:
        return f"{ONES_EN[n // 100]} hundred" + (f" and {words_en(n % 100)}" if n % 100 else "")
    if n < 10000:
        return f"{words_en(n // 1000)} thousand" + (f" {words_en(n % 1000)}" if n % 1000 else "")
    raise ValueError("words_en: up to 9999")


def as_date(value):
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value))


def date_long(value, lang):
    """4 November 2026 (id) / Wednesday, 4 November 2026 (en)."""
    if value in (None, ""):
        return None
    d = as_date(value)
    text = f"{d.day} {MONTHS[lang][d.month - 1]} {d.year}"
    return text if lang == "id" else f"{DAYS['en'][d.weekday()]}, {text}"


def date_words(value, lang):
    """The BAST opening: Rabu, tanggal empat bulan November tahun dua ribu dua puluh enam."""
    d = as_date(value)
    if lang == "id":
        return (f"{DAYS['id'][d.weekday()]}, tanggal {terbilang(d.day)} bulan {MONTHS['id'][d.month - 1]} "
                f"tahun {terbilang(d.year)}")
    return f"{DAYS['en'][d.weekday()]}, {d.day} {MONTHS['en'][d.month - 1]} {d.year}"


def number(n, lang):
    s = f"{n:,}"
    return s.replace(",", ".") if lang == "id" else s


def md_escape(text):
    """User text in Markdown: no accidental formatting, links or Typst code."""
    if text is None:
        return ""
    return re.sub(r"([\\`*_{}\[\]<>#+!|$@~^])", r"\\\1", str(text))


# ---------- rendering -----------------------------------------------------------------

def jinja_env(lang):
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(ASSETS), undefined=jinja2.StrictUndefined,
                             keep_trailing_newline=True, trim_blocks=True, lstrip_blocks=True,
                             autoescape=False,
                             # pandoc's heading ids look like Jinja comments ({#id}): comments are {## ##}.
                             comment_start_string="{##", comment_end_string="##}")
    env.filters.update({
        "md": md_escape,
        "t": lambda v: (v.get(lang) if isinstance(v, dict) else v),
        "date": lambda v: date_long(v, lang),
        "iso": lambda v: as_date(v).isoformat() if v else "",
        "num": lambda v: number(v, lang),
        "words": lambda v: terbilang(v) if lang == "id" else words_en(v),
        "datewords": lambda v: date_words(v, lang),
        "roman": lambda v: ROMAN[as_date(v).month - 1],
        # A date some days later: {{ a.bast.date | adddays(7) | date }}
        "adddays": lambda v, n: (as_date(v) + datetime.timedelta(days=int(n))).isoformat() if v else None,
        "cidrs": lambda v: ", ".join(v) if v else "",
        "yaml": lambda v: yaml.safe_dump(v, allow_unicode=True, sort_keys=False).strip(),
        # A safe YAML/JSON string for the front matter.
        "q": lambda v: json.dumps("" if v is None else str(v), ensure_ascii=False),
    })
    return env


def contains_ip(cidrs, ip):
    """Is ip inside one of the allow-list entries? An empty list allows everyone."""
    if not cidrs:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for c in cidrs:
        try:
            if addr in ipaddress.ip_network(str(c), strict=False):
                return True
        except ValueError:
            continue
    return False


def context(facts, a, lang, slug, extra):
    """What every template sees: f (facts), a (answers), and ready-made pieces."""
    oses = sorted({p["os"] for p in a.get("people") or [] if p.get("os")}, key=OSES.index) or list(OSES)
    servers = a.get("servers") or {}
    reach = []  # how a laptop reaches each node over SSH
    public = [n for n in facts["nodes"] if dig(servers, n["name"], "public_ip") or not is_private(n["host"])]
    jump = public[0]["name"] if public else facts["first_manager"]
    for n in facts["nodes"]:
        addr = dig(servers, n["name"], "public_ip") or n["host"]
        direct = not is_private(addr)
        direct = direct or n["name"] == jump  # the jump node itself is reached directly
        reach.append({**n, "address": addr, "direct": direct, "alias": f"{slug}-{n['name']}",
                      "jump": None if direct else f"{slug}-{jump}",
                      "provider": dig(servers, n["name"], "provider"), "region": dig(servers, n["name"], "region"),
                      "public_ip": dig(servers, n["name"], "public_ip")})
    web = [w for app in facts["apps"] for w in app["web"]]
    people = a.get("people") or []
    blocked = []
    for p in people:
        for ip in p.get("allow_from") or []:
            host_ip = str(ip).split("/")[0]
            if not contains_ip(facts["admin_allow_from"], host_ip) or not contains_ip(facts["ssh"]["allow_from"], host_ip):
                blocked.append({"name": p.get("name"), "ip": ip})
    return {
        "f": facts, "a": a, "lang": lang, "slug": slug, "oses": oses, "reach": reach, "web": web,
        "app": {x["name"]: x for x in facts["apps"]}, "people": people, "blocked": blocked,
        "groups": extra["groups"], "today": today().isoformat(), "dejavu": facts["dejavu"],
        "files": extra.get("files", []), "check": extra.get("check"), "draft": extra.get("draft", False),
        "kdbx": extra.get("kdbx"), "lang_both": len(a["lang"]) > 1, "first_lang": a["lang"][0],
        "nodes": {n["name"]: n for n in facts["nodes"]},
        "has": lambda name: name in {x["name"] for x in facts["apps"]},
        "warn": {w["id"] for w in facts["warnings"]},
        "secret_groups": group_secrets(facts, extra["groups"], lang),
        "logo": {who: logo_name(who, dig(a, who, "logo")) for who in ("vendor", "client")},
    }


def logo_name(who, path):
    """The logo's file name next to the documents (build copies it there), or None."""
    if not path:
        return None
    return f"logo-{who}{os.path.splitext(str(path))[1].lower() or '.png'}"


def group_secrets(facts, groups, lang):
    out = []
    for key, title in groups.items():
        rows = [s for s in facts["secrets"] if s["group"] == key]
        out.append({"key": key, "title": title[lang], "rows": rows})
    return out


PRIVATE = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
                                             "127.0.0.0/8", "169.254.0.0/16", "fc00::/7", "fe80::/10")]


def is_private(addr):
    """An address a laptop on the internet cannot reach (a private LAN or cloud network)."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False  # a host name: reachable as far as we know
    return any(ip in n for n in PRIVATE)


# ---------- the leak gate -------------------------------------------------------------

PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"), "a private key"),
    (re.compile(r"://[^/\s:@]+:[^@\s]+@"), "a user:password in a URL"),
    (re.compile(r"client-key-data"), "a kubeconfig key"),
    (re.compile(r"hooks\.slack\.com/services/"), "a Slack webhook"),
    (re.compile(r"discord(app)?\.com/api/webhooks/"), "a Discord webhook"),
    (re.compile(r"api\.telegram\.org/bot"), "a Telegram bot token"),
]
SCAN_EXT = (".md", ".typ", ".d2", ".svg", ".json", ".txt", ".yml", ".yaml", ".crt", ".csv")


def config_secret_values(ab):
    """Secret values inside config.yml (backup keys, alert channels), in memory."""
    cfg = load_yaml(ab.config)
    found = {}
    b = cfg.get("backup") or {}
    m = cfg.get("monitoring") or {}
    for name, v in (("backup.s3_access_key", b.get("s3_access_key")), ("backup.s3_secret_key", b.get("s3_secret_key")),
                    ("monitoring.telegram.bot_token", (m.get("telegram") or {}).get("bot_token")),
                    ("monitoring.email.password", (m.get("email") or {}).get("password")),
                    ("monitoring.webhook", m.get("webhook")), ("monitoring.heartbeat_url", m.get("heartbeat_url"))):
        if v:
            found[name] = str(v)
    repo = str(b.get("repository") or "")
    u = urllib.parse.urlsplit(repo.split(":", 1)[1]) if "://" in repo else None
    if u and u.password:
        found["backup.repository"] = u.password
    if m.get("webhook"):
        path = urllib.parse.urlsplit(m["webhook"]).path.strip("/")
        if path:
            found["monitoring.webhook (path)"] = path
    return found


def needles(ab, slug):
    """Every secret value, and the forms derived from them, as name -> value."""
    values = dict(ab.secret_values())
    values.update(config_secret_values(ab))
    phrase = ab.read_passphrase(slug) if ab.state_mode() != "none" else None
    if phrase:
        values["the passphrase"] = phrase
    out = {}
    for name, v in values.items():
        for i, line in enumerate(v.splitlines() or [v]):
            line = line.strip()
            if len(line) >= MIN_SECRET:
                out[f"{name}" if i == 0 else f"{name} (line {i + 1})"] = line
            elif line and name.startswith(("backup.", "monitoring.")):
                warning("weak-secret", f"{name} is shorter than {MIN_SECRET} characters, so the leak check cannot "
                        "search for it. Use a longer one.")
    if values.get("garage_access_key"):
        out["garage_access_key (GK)"] = "GK" + values["garage_access_key"]
    if values.get("traefik_admin"):
        out["traefik_admin (basic auth)"] = base64.b64encode(f"admin:{values['traefik_admin']}".encode()).decode()
    return out


def scan(paths, found_needles):
    """Search text files for secret values and secret-looking patterns. Returns the hits."""
    hits = []
    for path in paths:
        if not path.endswith(SCAN_EXT) or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            for no, line in enumerate(f, 1):
                for name, value in found_needles.items():
                    if value in line:
                        hits.append((path, no, name))
                for rx, what in PATTERNS:
                    if rx.search(line):
                        hits.append((path, no, what))
    return hits


def walk(folder, skip=()):
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in sorted(files):
            yield os.path.join(root, f)


def leak_gate(ab, out, slug, fresh=()):
    """Stop the build when a secret reached a generated file. Deletes this run's files."""
    files = [os.path.join(out, "handover.yml")] + list(walk(out, skip={"signed"}))
    hits = scan(files, needles(ab, slug))
    if not hits:
        return
    for path, no, name in hits:
        say("failed", f"{os.path.relpath(path, out)}:{no} contains {name}", "leak")
    for p in fresh:
        if os.path.isfile(p):
            os.remove(p)
    print("A secret value reached a document. The files of this run were deleted. "
          "Remove the value from handover.yml, then build again.", flush=True)
    raise Stop(5)


# ---------- tools ---------------------------------------------------------------------

def tool_version(cmd):
    try:
        r = run(cmd + ["--version"])
    except FileNotFoundError:
        return None
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", r.stdout + r.stderr)
    return tuple(int(x or 0) for x in m.groups()) if m else None


def find_tool(name):
    """The command for a PDF tool: on PATH if new enough, else through mise (pinned)."""
    path = shutil.which(name)
    if path:
        v = tool_version([path])
        if v and v >= TOOL_MIN[name]:
            return [path]
    mise = shutil.which("mise") or (os.path.expanduser("~/.local/bin/mise") if os.path.exists(os.path.expanduser("~/.local/bin/mise")) else None)
    if mise:
        return [mise, "exec", f"{name}@{TOOLS[name]}", "--", name]
    return None


def find_keepassxc():
    for p in (shutil.which("keepassxc-cli"), "/Applications/KeePassXC.app/Contents/MacOS/keepassxc-cli"):
        if p and os.path.exists(p):
            v = tool_version([p])
            if v and v >= KEEPASSXC_MIN:
                return p
    return None


def install_lines():
    mac = sys.platform == "darwin"
    return {
        "mise": "curl https://mise.run | sh" + (" (or: brew install mise)" if mac else ""),
        "keepassxc": "brew install --cask keepassxc" if mac else
        "sudo apt-get install -y keepassxc-minimal (Ubuntu 24.04: keepassxc; Fedora: sudo dnf install keepassxc)",
        "age": "brew install age" if mac else "sudo apt-get install -y age",
    }


# ---------- the credentials file (KeePassXC) -------------------------------------------

class Vault:
    """One .kdbx with every secret value. Values travel on keepassxc-cli's stdin only."""

    def __init__(self, cli, path, phrase):
        self.cli, self.path, self.phrase = cli, path, phrase

    def call(self, args, extra_input=""):
        r = run([self.cli] + args, input=self.phrase + "\n" + extra_input)
        if r.returncode != 0:
            # Never print stdin; keepassxc-cli's own messages hold no values.
            failed("keepassxc", f"keepassxc-cli {args[0]} failed: {r.stderr.strip()[-300:]}")
        return r.stdout

    def create(self):
        if os.path.exists(self.path):
            os.remove(self.path)
        r = run([self.cli, "db-create", "-p", self.path], input=f"{self.phrase}\n{self.phrase}\n")
        if r.returncode != 0:
            failed("keepassxc", f"keepassxc-cli db-create failed: {r.stderr.strip()[-300:]}")

    def mkdir(self, group):
        self.call(["mkdir", "-q", self.path, group])

    def add(self, entry_path, user, url, notes, value):
        args = ["add", "-q", "-p", "-u", user or "", "--url", url or "", "--notes", notes, self.path, entry_path]
        self.call(args, value + "\n")

    def attach(self, entry_path, name, data):
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o700)
            p = os.path.join(tmp, name)
            fd = os.open(p, os.O_WRONLY | os.O_CREAT, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            self.call(["attachment-import", "-q", self.path, entry_path, name, p])

    def entries(self):
        return sorted(x for x in self.call(["ls", "-R", "-f", self.path]).splitlines() if x.strip())

    def password(self, entry_path):
        return self.call(["show", "-q", "-s", "-a", "Password", self.path, entry_path]).rstrip("\n")


CHANGE_NOTE = {
    "file": {"id": "Ubah file state/secrets/{name}, jalankan ./install.sh, lalu perbarui file ini.",
             "en": "Edit state/secrets/{name}, run ./install.sh, then update this file."},
    "both": {"id": "Ubah di aplikasi dan di state/secrets/{name} bersamaan, lalu ./install.sh dan tests/check.py.",
             "en": "Change it in the app and in state/secrets/{name} together, then ./install.sh and tests/check.py."},
    "app": {"id": "Ubah di aplikasi, lalu salin nilai baru ke state/secrets/{name} dan ke file ini.",
            "en": "Change it in the app, then copy the new value into state/secrets/{name} and this file."},
    "internal": {"id": "Jangan diubah kecuali bocor; ini urusan operator ansibro.",
                 "en": "Do not change it unless it leaked; the ansibro operator handles it."},
}


def build_vault(ab, cli, path, phrase, facts, a, data, lang, attachments):
    """Make the credentials file from scratch, then read it back to prove it is right."""
    values = ab.secret_values()
    groups = data["groups"]
    entries = {e["secret"]: e for e in data["entries"]}
    users_from = {e.get("user_secret") for e in data["entries"] if e.get("user_secret")}
    primary_ip = {x["name"]: x["primary_ip"] for x in facts["apps"]}
    items = []  # (group key, title, user, url, notes, value, attachment name or None)
    for s in facts["secrets"]:
        name = s["name"]
        if s["status"] == "missing" or name not in values:
            continue
        if name in users_from and s["status"] == "present":
            continue  # it is the user name of another entry
        e = entries.get(name) if s["status"] == "present" else None
        user = e.get("user", "") if e else ""
        if e and e.get("user_secret"):
            user = e.get("user_prefix", "") + values.get(e["user_secret"], "")
        url = (e.get("url", "") if e else "").replace("{domain}", facts["domain"]) \
            .replace("{ip}", primary_ip.get(s["app"], ""))
        note = CHANGE_NOTE[s["change"]][lang].format(name=name)
        if not s["verified"]:
            note += " (belum diuji)" if lang == "id" else " (not tested)"
        value = values[name]
        multi = "\n" in value
        items.append((s["group"], e["title"] if e else name, user.replace("{domain}", facts["domain"]), url,
                      f"state/secrets/{name}\n{note}", "" if multi else value, name if multi else None,
                      value.encode() if multi else None))
    for name, value in config_secret_values(ab).items():
        if name != "monitoring.webhook (path)":
            items.append(("recovery", f"config.yml {name}", "", "", "config.yml", value, None, None))
    for title, group, name, blob in attachments:
        items.append((group, title, "", "", "", "", name, blob))

    v = Vault(cli, path, phrase)
    v.create()
    for key in groups:  # only the groups that hold something, in their order
        if any(i[0] == key for i in items):
            v.mkdir(groups[key][lang])
    expect = {}
    for group, title, user, url, notes, value, att_name, blob in items:
        entry = f"{groups[group][lang]}/{title}"
        v.add(entry, user, url, notes, value)
        if att_name:
            v.attach(entry, att_name, blob)
        elif value:
            expect[entry] = value
    # Read back: every password is what it should be. Only counts are printed.
    for entry, value in expect.items():
        if v.password(entry) != value:
            failed("vault-check", f"the credentials file does not hold the right value for {entry}")
    names = v.entries()
    ok(f"credentials file: {len(names)} items, {len(expect)} passwords checked")
    return names


def installer_tar(ab):
    """config.yml and state/secrets, so a successor can run ansibro again. In memory."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def add(name, data, mode=0o600):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = mode
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
        with open(ab.config, "rb") as f:
            add(os.path.basename(ab.config), f.read())
        for name, value in sorted(ab.secret_values().items()):
            add(f"state/secrets/{name}", (value + "\n").encode())
    return buf.getvalue()


def make_passphrase(cli):
    r = run([cli, "diceware", "-W", "7"])
    if r.returncode != 0 or len(r.stdout.split()) != 7:
        failed("keepassxc", "keepassxc-cli diceware failed")
    return r.stdout.strip()


# ---------- commands ------------------------------------------------------------------

def default_out(ab):
    try:
        domain = load_yaml(ab.config).get("domain", "system")
    except OSError:
        domain = "system"
    stem = os.path.splitext(os.path.basename(ab.config))[0]
    return os.path.expanduser(f"~/Handover/{domain}-{stem}")


def prepare_out(out, create):
    out = os.path.abspath(os.path.expanduser(out))
    if in_git_tree(out if os.path.exists(out) else os.path.dirname(out)):
        failed("out-in-git", f"{out} is inside a git repository. The credentials file must never be committed: "
               "choose an output folder outside any repository (the default is ~/Handover/...).")
    if create:
        os.makedirs(out, mode=0o700, exist_ok=True)
        os.chmod(out, 0o700)
    return out


def cmd_doctor(ab, args, data):
    code = 0
    ab.check_folder()
    av = ab.version()
    ok(f"ansibro {av['version'] or av['describe'] or '(version unknown)'} in {ab.dir}")
    if sys.version_info < (3, 12):
        warning("python", f"Python {sys.version.split()[0]} is older than 3.12, which ansibro needs")
    ok(f"Python {sys.version.split()[0]} with PyYAML and Jinja2")
    configs = sorted(c for c in os.listdir(ab.dir) if re.match(r"^config(\..+)?\.yml$", c) and c != "config.example.yml")
    ok(f"config: {os.path.basename(ab.config)}" + (f" (also here: {', '.join(c for c in configs if c != os.path.basename(ab.config))})" if len(configs) > 1 else ""))
    try:
        mode = ab.state_mode()
        ok(f"state: {'encrypted (state.age)' if mode == 'age' else 'plain (state/)' if mode == 'plain' else 'none'}")
        if mode == "none":
            warning("no-state", "there is no state/ here: dejavu can write the documents, but no credentials file")
        if mode == "plain" and os.path.isfile(ab.key):
            warning("state-not-encrypted", "state/ is open while an age key exists. Close it with: scripts/state.sh close")
    except Stop as s:
        code = max(code, s.code)
    lines = install_lines()
    for name in TOOLS:
        t = find_tool(name)
        if t:
            ok(f"{name}: {'mise ' + TOOLS[name] if 'mise' in t[0] else t[0]}")
        else:
            say("needs the user", f"{name} is missing, and mise is not installed. Install mise: {lines['mise']}", "tools")
            code = 3
    cli = find_keepassxc()
    if cli:
        ok(f"keepassxc-cli: {cli}")
    else:
        say("needs the user", f"keepassxc-cli {'.'.join(map(str, KEEPASSXC_MIN))} or newer is missing. "
            f"It makes the credentials file. Install: {lines['keepassxc']}", "keepassxc")
        code = 3
    raise Stop(code)


def cmd_init(ab, args, data):
    ab.check_folder()
    out = prepare_out(args.out or default_out(ab), create=True)
    path = os.path.join(out, "handover.yml")
    if os.path.exists(path):
        ok(f"{path} is already there; it was not changed")
    else:
        inv = ab.inventory(getattr(args, "inventory_json", None))
        with open(os.path.join(ASSETS, "handover.example.yml"), encoding="utf-8") as f:
            text = f.read()
        servers = "\n".join(f"  {n}: {{public_ip: null, provider: null, region: null}}"
                            for n in inv["_meta"]["hostvars"])
        text = text.replace("  # SERVERS", servers)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        ok(f"made {path}")
    a = load_answers(out)
    missing = missing_required(a)
    if missing:
        print("These answers are still empty (references/questions.md has the questions):", flush=True)
        for m in missing:
            print(f"  - {m}")
        needs_user("answers", f"fill in handover.yml with the user, then run: facts --out {out}")
    ok("handover.yml has every required answer")
    raise Stop(0)


def write_json(path, value):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")


def cmd_facts(ab, args, data, quiet=False):
    ab.check_folder()
    out = prepare_out(args.out or default_out(ab), create=True)
    facts, ca_file = build_facts(ab, args, data)
    write_json(os.path.join(out, "facts.json"), facts)
    if not quiet:
        ok(f"facts.json: {len(facts['nodes'])} servers, {len(facts['apps'])} apps, "
           f"{sum(1 for s in facts['secrets'] if s['status'] == 'present')} secrets (names only)")
        for w in facts["warnings"]:
            extra = ", ".join(f"{k}={v}" for k, v in w.items() if k != "id")
            warning(w["id"], extra or "see references/troubleshooting.md")
    return out, facts, ca_file


def cmd_check(ab, args, data):
    """ansibro's own acceptance test, plus what the servers are. Read-only, but it connects."""
    ab.check_folder()
    out = prepare_out(args.out or default_out(ab), create=True)
    chk = os.path.join(out, "check")
    os.makedirs(chk, mode=0o700, exist_ok=True)
    mode = ab.state_mode()
    script = os.path.join(ab.dir, "scripts", "state.sh")
    opened = False
    if mode == "age":
        r = run([script, "open"], cwd=ab.dir)
        if r.returncode != 0:
            failed("state-open", r.stderr.strip())
        opened = True
    try:
        r = run([sys.executable, os.path.join(ab.dir, "tests", "check.py"), ab.config], cwd=ab.dir, env=ab.env())
        lines = [x for x in (r.stdout + r.stderr).splitlines() if re.match(r"^(PASS|FAIL|SKIP)\b", x.strip())]
        with open(os.path.join(chk, "acceptance.txt"), "w", encoding="utf-8") as f:
            f.write(f"date: {datetime.datetime.now().isoformat(timespec='minutes')}\n")
            f.write("\n".join(lines) + "\n")
        servers = server_facts(ab)
        write_json(os.path.join(chk, "servers.json"), servers)
        ok(f"server details read from {len(servers)} servers")
    finally:
        if opened:
            run([script, "close"], cwd=ab.dir)
    facts, _ca = build_facts(ab, args, data)
    write_json(os.path.join(chk, "web.json"), web_facts(facts, load_answers(out) if os.path.isfile(
        os.path.join(out, "handover.yml")) else {}))
    leak_gate(ab, out, slug_of(load_answers(out), facts) if os.path.isfile(os.path.join(out, "handover.yml")) else "x",
              fresh=[os.path.join(chk, f) for f in ("acceptance.txt", "servers.json", "web.json")])
    passed = sum(1 for x in lines if x.strip().startswith("PASS"))
    fails = sum(1 for x in lines if x.strip().startswith("FAIL"))
    (ok if not fails else lambda m: warning("check-failed", m))(f"acceptance test: {passed} passed, {fails} failed")
    raise Stop(0 if not fails else 1)


def server_facts(ab):
    """vCPU, memory, disk, OS and the SSH host key fingerprint of every server (ansible setup)."""
    with tempfile.TemporaryDirectory() as tmp:
        r = run([os.path.join(ab.venv_bin, "ansible"), "all", "-m", "ansible.builtin.setup", "-a",
                 "gather_subset=!all,hardware,distribution", "-e", f"secrets_dir={tmp}"], cwd=ab.dir, env=ab.env())
    servers = {}
    for block in re.split(r"\n(?=\S+ \| [A-Z]+!? => )", "\n" + r.stdout):
        m = re.match(r"^\s*(\S+) \| ([A-Z]+)!? => (.*)$", block, re.S)
        if not m:
            continue
        name, status, body = m.groups()
        if status != "SUCCESS":
            servers[name] = {"reached": False}
            continue
        f = json.loads(body).get("ansible_facts", {})
        root = next((x for x in f.get("ansible_mounts", []) if x.get("mount") == "/"), {})
        key = f.get("ansible_ssh_host_key_ed25519_public")
        fp = None
        if key:
            digest = hashlib.sha256(base64.b64decode(key)).digest()
            fp = "SHA256:" + base64.b64encode(digest).decode().rstrip("=")
        servers[name] = {"reached": True, "vcpu": f.get("ansible_processor_vcpus"),
                         "ram_gb": round((f.get("ansible_memtotal_mb") or 0) / 1024, 1),
                         "disk_gb": round((root.get("size_total") or 0) / 1e9),
                         "os": f"{f.get('ansible_distribution', '')} {f.get('ansible_distribution_version', '')}".strip(),
                         "kernel": f.get("ansible_kernel"), "fingerprint": fp}
    return servers


def web_facts(facts, a):
    """For each web page: does DNS answer, which certificate is served, and the HTTP status code."""
    import http.client
    import socket
    import ssl
    from cryptography import x509
    servers = (a or {}).get("servers") or {}
    targets = [dig(servers, n, "public_ip") or next(x["host"] for x in facts["nodes"] if x["name"] == n)
               for n in facts["traefik_nodes"]]
    out = []
    for app in facts["apps"]:
        for w in app["web"]:
            host = f"{w['host']}.{facts['domain']}"
            try:
                dns = sorted({i[4][0] for i in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)})
            except OSError:
                dns = []
            row = {"url": w["url"], "dns": dns, "issuer": None, "not_after": None, "status": None}
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            target = targets[0] if targets else host
            try:
                with socket.create_connection((target, 443), timeout=10) as sock:
                    with ctx.wrap_socket(sock, server_hostname=host) as tls:
                        cert = x509.load_der_x509_certificate(tls.getpeercert(binary_form=True))
                        row["issuer"] = cert.issuer.rfc4514_string()
                        end = getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after
                        row["not_after"] = end.date().isoformat()
                conn = http.client.HTTPSConnection(target, 443, timeout=10, context=ctx)
                conn.request("HEAD", w["path"], headers={"Host": host})
                row["status"] = conn.getresponse().status  # the code only, never the page
                conn.close()
            except OSError as e:
                row["error"] = type(e).__name__
            out.append(row)
    ok(f"web pages checked: {sum(1 for r in out if r['status'])} of {len(out)} answered")
    return out


def read_check(out, facts):
    p = os.path.join(out, "check", "acceptance.txt")
    if not os.path.isfile(p):
        return None
    with open(p, encoding="utf-8") as f:
        lines = f.read().splitlines()
    date = lines[0].split(":", 1)[1].strip()[:10] if lines and lines[0].startswith("date:") else None
    rows = []
    for x in lines[1:]:
        m = re.match(r"^\s*(PASS|FAIL|SKIP)\s+(.*)$", x)
        if m:
            rows.append({"result": m.group(1), "text": m.group(2)})
    stale = bool(facts.get("last_install") and date and date < facts["last_install"])
    extra = {}
    for name in ("servers", "web"):
        q = os.path.join(out, "check", f"{name}.json")
        extra[name] = load_json(q) if os.path.isfile(q) else ({} if name == "servers" else [])
    return {"date": date, "rows": rows, "stale": stale, **extra,
            "passed": sum(r["result"] == "PASS" for r in rows), "failed": sum(r["result"] == "FAIL" for r in rows),
            "skipped": sum(r["result"] == "SKIP" for r in rows)}


FILES = {
    "id": {"bast": "BAST", "technical": "dokumentasi-teknis", "laptop": "panduan-laptop"},
    "en": {"bast": "handover-certificate", "technical": "technical-documentation", "laptop": "laptop-guide"},
}


def render(env, template, ctx, path):
    try:
        text = env.get_template(template).render(**ctx)
    except jinja2.TemplateError as e:
        where = f"{getattr(e, 'name', None) or template}:{getattr(e, 'lineno', '?')}"
        failed("template", f"{where}: {e}")
    text = re.sub(r"\n{3,}", "\n\n", text)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def pdf(tools, build, md, pdf_path, lang, toc, date):
    """Markdown -> Typst (pandoc, our template) -> PDF/A-2b (typst)."""
    typ = os.path.splitext(md)[0] + ".typ"
    cmd = tools["pandoc"] + [md, "-f", "markdown", "-t", "typst", "-s", "--template",
                             os.path.join(build, "handover.typst"), "-o", typ]
    if toc:
        cmd.append("--toc")
    r = run(cmd)
    if r.returncode != 0:
        failed("pandoc", r.stderr.strip()[-500:])
    env = dict(os.environ, SOURCE_DATE_EPOCH=str(int(datetime.datetime.combine(as_date(date), datetime.time()).timestamp())))
    # Only Typst's own fonts: the same PDF on every machine, and every glyph embedded (PDF/A).
    r = run(tools["typst"] + ["compile", "--ignore-system-fonts", "--root", build, "--pdf-standard", "a-2b", typ,
                              pdf_path], env=env)
    if r.returncode != 0:
        failed("typst", r.stderr.strip()[-800:])
    return typ


def cmd_build(ab, args, data):
    ab.check_folder()
    out = prepare_out(args.out or default_out(ab), create=True)
    a = load_answers(out)
    for who in ("vendor", "client"):
        logo = dig(a, who, "logo")
        if logo and not os.path.isfile(os.path.expanduser(str(logo))):
            warning("logo", f"{who}.logo {logo} is not a file; the documents are made without it")
            a[who]["logo"] = None
    out, facts, ca_file = cmd_facts(ab, args, data, quiet=True)
    slug = slug_of(a, facts)
    missing = missing_required(a)
    draft = args.draft
    if missing and not draft:
        print("These answers are still empty:", flush=True)
        for m in missing:
            print(f"  - {m}")
        needs_user("answers", "fill them in handover.yml, or build a draft with --draft")

    # Hand edits are kept: the wording belongs in handover.yml.
    dist = os.path.join(out, "dist")
    build = os.path.join(out, "build")
    last = os.path.join(build, "last.json")
    if os.path.isfile(last) and not args.force:
        for rel, digest in load_json(last).items():
            p = os.path.join(dist, rel)
            if os.path.isfile(p) and sha256(p) != digest:
                failed("hand-edit", f"dist/{rel} was edited by hand. Put the wording in handover.yml "
                       "(notes, known_issues, extra_apps, out_of_scope, summary_note) and build again, "
                       "or build with --force to overwrite it.")
    for d in (dist, build):
        os.makedirs(d, mode=0o700, exist_ok=True)
    fresh = []

    check = read_check(out, facts)
    groups = data["groups"]
    tools = {}
    if not args.no_pdf:
        for name in TOOLS:
            t = find_tool(name)
            if not t:
                needs_user("tools", f"{name} is missing. Install mise ({install_lines()['mise']}); "
                           "dejavu then downloads the pinned PDF tools itself.")
            tools[name] = t

    # 1. Plain files: ssh_config, hosts, diagrams, the CA.
    base_ctx = context(facts, a, a["lang"][0], slug, {"groups": groups, "check": check, "draft": draft})
    env0 = jinja_env(a["lang"][0])
    for tpl, name in (("ssh_config.txt.j2", "ssh_config.txt"), ("hosts.txt.j2", "hosts.txt")):
        p = os.path.join(dist, name)
        if name == "hosts.txt" and dig(a, "dns", "mode") != "hosts":
            if os.path.exists(p):
                os.remove(p)
            continue
        fresh.append(render(env0, tpl, base_ctx, p))
    if ca_file or dig(a, "tls", "client_ca"):
        src = dig(a, "tls", "client_ca") or ca_file
        dst = os.path.join(dist, f"{slug}-ca.crt")
        shutil.copyfile(os.path.expanduser(src), dst)
        fresh.append(dst)

    # 2. The documents, except the BAST (it lists the hashes of the others).
    docs = []
    for lang in a["lang"]:
        env = jinja_env(lang)
        ctx = context(facts, a, lang, slug, {"groups": groups, "check": check, "draft": draft})
        ldist, lbuild = os.path.join(dist, lang), os.path.join(build, lang)
        os.makedirs(ldist, mode=0o700, exist_ok=True)
        os.makedirs(lbuild, mode=0o700, exist_ok=True)
        for diagram in ("architecture", "access"):
            fresh.append(render(env, f"{diagram}.d2.j2", ctx, os.path.join(lbuild, f"{diagram}.d2")))
        p = os.path.join(ldist, f"{slug}-{FILES[lang]['technical']}.md")
        fresh.append(render(env, f"{lang}/technical.md.j2", {**ctx, "only_os": None}, p))
        docs.append((lang, p, True))
        for os_name in ctx["oses"]:
            p = os.path.join(ldist, f"{slug}-{FILES[lang]['laptop']}-{os_name}.md")
            fresh.append(render(env, f"{lang}/laptop-guide.md.j2", {**ctx, "only_os": os_name}, p))
            docs.append((lang, p, True))
    leak_gate(ab, out, slug, fresh)
    ok(f"documents written for {', '.join(a['lang'])}; no secret in them")

    # 3. The credentials file.
    kdbx = None
    cli = find_keepassxc()
    if ab.state_mode() == "none":
        warning("no-state", "no state/ here, so there is no credentials file")
    elif not cli:
        if not draft:
            needs_user("keepassxc", f"keepassxc-cli is missing: {install_lines()['keepassxc']}")
        warning("keepassxc", "keepassxc-cli is missing, so the draft has no credentials file")
    else:
        phrase = ab.read_passphrase(slug)
        if not phrase or args.new_passphrase:
            phrase = make_passphrase(cli)
            ab.write_passphrase(slug, phrase)
            ok("made a new passphrase; it is kept in state/handover/ (show it with: passphrase)")
        kname = f"{slug}-{'kredensial' if a['lang'][0] == 'id' else 'credentials'}.kdbx"
        kdbx = os.path.join(dist, kname)
        stamp = os.path.join(build, "vault.json")
        want = hashlib.sha256(json.dumps([facts["secrets"], facts["config_secrets"], a["lang"][0],
                                          a.get("ssh_handover"), a.get("attach")], sort_keys=True).encode()).hexdigest()
        current = load_json(stamp) if os.path.isfile(stamp) else {}
        if args.rebuild_vault or args.new_passphrase or not os.path.isfile(kdbx) or current.get("want") != want \
                or current.get("sha256") != sha256(kdbx):
            attachments = [("ansibro installer files", "internal", "ansibro-installer.tar.gz", installer_tar(ab))]
            for extra in a.get("attach") or []:
                with open(os.path.expanduser(extra), "rb") as fh:
                    attachments.append((os.path.basename(extra), "infra", os.path.basename(extra), fh.read()))
            if a.get("ssh_handover") == "generated":
                attachments.append(ssh_key_attachment(slug, a))
            build_vault(ab, cli, kdbx, phrase, facts, a, data, a["lang"][0], attachments)
            write_json(stamp, {"want": want, "sha256": sha256(kdbx)})
        else:
            ok("credentials file is up to date")
    leak_gate(ab, out, slug, fresh)

    # 4. PDFs, then the BAST with the hashes of everything else.
    if tools:
        for diagram in ("architecture", "access"):
            for lang in a["lang"]:
                d2 = os.path.join(build, lang, f"{diagram}.d2")
                svg = os.path.join(build, lang, f"{diagram}.svg")
                r = run(tools["d2"] + ["--layout=elk", "--pad", "20", d2, svg])
                if r.returncode != 0:
                    failed("d2", r.stderr.strip()[-400:])
                shutil.copyfile(svg, os.path.join(dist, lang, f"{diagram}.svg"))
        for lang in a["lang"]:
            shutil.copyfile(os.path.join(ASSETS, "handover.typst"), os.path.join(build, lang, "handover.typst"))
            for who in ("vendor", "client"):
                src = dig(a, who, "logo")
                if not src:
                    continue
                src = os.path.expanduser(str(src))
                shutil.copyfile(src, os.path.join(build, lang, logo_name(who, src)))
        for lang, md, toc in docs:
            b = shutil.copy(md, os.path.join(build, lang))
            typ = pdf(tools, os.path.join(build, lang), b, os.path.splitext(md)[0] + ".pdf", lang, toc,
                      dig(a, "bast", "date") or today())
            fresh.append(typ)
        leak_gate(ab, out, slug, fresh)
    files = []
    for p in sorted(walk(dist)):
        rel = os.path.relpath(p, dist)
        if os.path.basename(p) in ("SHA256SUMS",) or os.path.basename(rel).startswith(tuple(
                f"{slug}-{FILES[x]['bast']}" for x in LANGS)):
            continue
        if p.endswith((".pdf", ".kdbx", ".crt", ".txt")) and "README" not in p:
            files.append({"name": rel, "size": os.path.getsize(p), "sha256": sha256(p)})
    for lang in a["lang"]:
        env = jinja_env(lang)
        ctx = context(facts, a, lang, slug, {"groups": groups, "check": check, "draft": draft, "files": files,
                                             "kdbx": {"name": os.path.basename(kdbx), "sha256": sha256(kdbx),
                                                      "size": os.path.getsize(kdbx)} if kdbx else None})
        p = os.path.join(dist, lang, f"{slug}-{FILES[lang]['bast']}.md")
        fresh.append(render(env, f"{lang}/bast.md.j2", ctx, p))
        # The README lists the files, so it comes last too.
        fresh.append(render(env, f"{lang}/readme.txt.j2", ctx, os.path.join(dist, lang, "README.txt")))
        leak_gate(ab, out, slug, fresh)
        if tools:
            b = shutil.copy(p, os.path.join(build, lang))
            fresh.append(pdf(tools, os.path.join(build, lang), b, os.path.splitext(p)[0] + ".pdf", lang, False,
                             dig(a, "bast", "date") or today()))
    leak_gate(ab, out, slug, fresh)

    # 5. SHA256SUMS over everything handed over, and what was written (to spot hand edits).
    sums = []
    record = {}
    for p in sorted(walk(dist)):
        rel = os.path.relpath(p, dist)
        if rel == "SHA256SUMS":
            continue
        sums.append(f"{sha256(p)}  {rel}")
        if rel.endswith(".md"):
            record[rel] = sha256(p)
    with open(os.path.join(dist, "SHA256SUMS"), "w", encoding="utf-8") as f:
        f.write("\n".join(sums) + "\n")
    write_json(last, record)
    ok(f"handover pack ready in {dist}" + (" (DRAFT)" if draft else ""))
    left = [w["id"] for w in facts["warnings"]]
    if left:
        warning("open-warnings", f"still open: {', '.join(sorted(set(left)))}. Each one is in the known issues "
                "appendix; check them with the user.")
    if kdbx:
        say("needs the user", "give the credentials file and its passphrase on two different channels. "
            f"The user reads the passphrase in their own terminal: {sys.executable} {os.path.abspath(__file__)} "
            f"passphrase --out {out}", "deliver")
        raise Stop(3)
    raise Stop(0)


def ssh_key_attachment(slug, a):
    """A new SSH key for a client who cannot make one: the private key goes into the credentials
    file, the public key next to the documents."""
    with tempfile.TemporaryDirectory() as tmp:
        key = os.path.join(tmp, f"{slug}_ed25519")
        r = run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", f"{slug}-client", "-f", key])
        if r.returncode != 0:
            failed("ssh-keygen", r.stderr.strip())
        with open(key, "rb") as fh:
            private = fh.read()
        with open(key + ".pub", "rb") as fh:
            public = fh.read()
    a.setdefault("_generated_pub", public.decode().strip())
    return ("SSH key (client)", "infra", f"{slug}_ed25519", private)


def cmd_scan(ab, args, data):
    out = prepare_out(args.out or default_out(ab), create=False)
    a = load_answers(out)
    facts = load_json(os.path.join(out, "facts.json")) if os.path.isfile(os.path.join(out, "facts.json")) else {"domain": "x"}
    leak_gate(ab, out, slug_of(a, facts))
    ok("no secret value found in the output")
    raise Stop(0)


def cmd_passphrase(ab, args, data):
    if not sys.stdout.isatty():
        failed("not-a-terminal", "the passphrase is shown only in a real terminal, so it never reaches an AI agent "
               "or a log. Ask the user to run this command in their own Terminal.")
    out = prepare_out(args.out or default_out(ab), create=False)
    a = load_answers(out)
    facts = load_json(os.path.join(out, "facts.json"))
    phrase = ab.read_passphrase(slug_of(a, facts))
    if not phrase:
        needs_user("no-passphrase", "there is no passphrase yet. Run build first.")
    print(phrase)
    raise Stop(0)


def cmd_facts_only(ab, args, data):
    cmd_facts(ab, args, data)
    raise Stop(0)


COMMANDS = {"doctor": cmd_doctor, "init": cmd_init, "facts": cmd_facts_only, "check": cmd_check,
            "build": cmd_build, "scan": cmd_scan, "passphrase": cmd_passphrase}


def main(argv=None):
    p = argparse.ArgumentParser(prog="handover.py", description=__doc__.split("\n\n")[0])
    p.add_argument("command", choices=list(COMMANDS))
    p.add_argument("--ansibro", default=".", help="the ansibro folder (default: here)")
    p.add_argument("--config", default="config.yml", help="the config that was installed (default: config.yml)")
    p.add_argument("--out", help="the output folder (default: ~/Handover/<domain>-<config>)")
    p.add_argument("--draft", action="store_true", help="build with empty answers, marked DRAFT")
    p.add_argument("--force", action="store_true", help="overwrite documents edited by hand")
    p.add_argument("--rebuild-vault", action="store_true", help="make the credentials file again")
    p.add_argument("--new-passphrase", action="store_true", help="a new passphrase (when the old one leaked)")
    p.add_argument("--no-pdf", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--inventory-json", help=argparse.SUPPRESS)
    p.add_argument("--groupvars-json", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    if (args.inventory_json or args.groupvars_json or args.no_pdf) and not TEST:
        p.error("--inventory-json, --groupvars-json and --no-pdf are for dejavu's own tests")
    data = load_yaml(os.path.join(ASSETS, "apps.yml"))
    ab = Ansibro(args.ansibro, args.config)
    try:
        r = COMMANDS[args.command](ab, args, data)
        return 0 if r is None else r
    except Stop as s:
        return s.code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
