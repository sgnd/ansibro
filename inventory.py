#!/usr/bin/env python3
"""Ansible inventory built from config.yml (path taken from $ANSIBRO_CONFIG).

It also checks config.yml, so mistakes stop the install early with a clear message.
"""

import ipaddress
import json
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
GROUPS = {"manager": "managers", "worker": "workers", "standalone": "standalone"}
CONFIG_KEYS = {
    "domain", "acme_email", "acme_server", "acme_ca_cert", "tls", "tls_cert", "tls_key", "timezone",
    "ssh", "admin_allow_from", "firewall_allow", "wireguard", "backup", "monitoring", "nodes", "apps",
    "orchestrator",
}
ORCHESTRATORS = ("swarm", "k3s")
# k3s uses these for its pods and services; server IPs must be outside them.
K3S_CIDRS = ("10.42.0.0/16", "10.43.0.0/16")
# Apps that run as cluster services and also work on k3s. Swarmpit manages Docker Swarm only.
K3S_CLUSTER_APPS = ("traefik", "portainer", "kong", "keycloak", "authelia")
# Node names become hostnames, and must not clash with "swarm" or group names.
NODE_NAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
RESERVED_NAMES = {"swarm", "all", "managers", "workers", "standalone", "localhost"}
DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
LABEL = re.compile(r"^[A-Za-z0-9._-]+$")
SSH_KEYS = {"user", "key", "port", "allow_from"}
BACKUP_KEYS = {"repository", "s3_access_key", "s3_secret_key", "time", "keep_daily", "keep_weekly", "keep_monthly"}
MONITORING_KEYS = {"telegram", "email", "webhook", "heartbeat_url", "keep_days"}
MONITORING_APPS = ("victoria",)
URL = re.compile(r"^https?://\S+$")
TIME = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
# Swarm's own networks use this range. Docker's default (10.0.0.0/8) often clashes with servers' IPs.
SWARM_ADDRESS_POOL = "10.200.0.0/16"
REGISTRY_PORT = 5000  # the local image registry, on every manager
KONG_SUBNET = "10.200.255.0/24"  # Kong's own network, inside the pool
NODE_KEYS = {"name", "ip", "host", "role", "labels"}
WIREGUARD_PORT = 51820  # UDP port of the WireGuard network between the servers


def fail(msg):
    sys.exit(f"config error: {msg}")


def warn(msg):
    """Something to fix soon, but the install can go on (stderr: install.sh shows it)."""
    print(f"warning: {msg}", file=sys.stderr)


def load_yaml(path):
    with open(path) as f:
        try:
            return yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            # A tab or a wrong indent: say where, not a long Python error.
            mark = getattr(e, "problem_mark", None)
            where = f" line {mark.line + 1}" if mark else ""
            hint = "use spaces, not tabs" if "\\t" in str(e) else "check the spaces at the start of this line and the line above"
            fail(f"{os.path.basename(path)}{where}: {hint}")


def load_config():
    path = os.path.abspath(os.environ.get("ANSIBRO_CONFIG", "config.yml"))
    if not os.path.exists(path):
        fail(f"{path} not found (copy config.example.yml)")
    return load_yaml(path), os.path.dirname(path)


def load_bundle():
    """Return the bundle info (offline install), or {} when there is no bundle."""
    path = os.path.join(HERE, "bundle", "info.yml")
    return load_yaml(path) if os.path.exists(path) else {}


def check_ip_list(name, value):
    """A list of IPs or ranges, like [203.0.113.0/24, 198.51.100.7]. Empty is fine."""
    if value is None:
        return
    if not isinstance(value, list):
        fail(f"{name} must be a list, like [203.0.113.0/24]")
    for item in value:
        try:
            ipaddress.ip_network(str(item), strict=False)
        except ValueError:
            fail(f"{name}: {item} is not an IP or range")


def check_firewall_allow(rules):
    """firewall_allow: a list like [{port: 51820, proto: udp, from: 203.0.113.0/24}]."""
    if rules is None:
        return
    if not isinstance(rules, list):
        fail("firewall_allow must be a list, like [{port: 51820, proto: udp}]")
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) - {"port", "proto", "from"}:
            fail(f"firewall_allow: {rule} must look like {{port: 51820, proto: udp, from: 203.0.113.0/24}}")
        if not isinstance(rule.get("port"), int) or not 1 <= rule["port"] <= 65535:
            fail(f"firewall_allow: port must be a number from 1 to 65535, got {rule.get('port')}")
        if rule.get("proto", "tcp") not in ("tcp", "udp"):
            fail(f"firewall_allow: proto must be tcp or udp, got {rule.get('proto')}")
        if rule.get("from", "any") != "any":
            check_ip_list("firewall_allow from", [rule["from"]])


def check_backup(backup):
    """backup: where restic keeps the backups, and how long."""
    if backup is None:
        return
    if not isinstance(backup, dict):
        fail("backup must look like { repository: s3:https://s3.example.com/my-bucket }")
    unknown = set(backup) - BACKUP_KEYS
    if unknown:
        fail(f"unknown setting backup.{', backup.'.join(sorted(unknown))} (typo?)")
    if not backup.get("repository"):
        fail("backup.repository is required, like s3:https://s3.example.com/my-bucket or /mnt/backup")
    if str(backup["repository"]).startswith("s3:") and not (backup.get("s3_access_key") and backup.get("s3_secret_key")):
        fail("backup: an s3: repository needs s3_access_key and s3_secret_key")
    if str(backup["repository"]).startswith("s3:"):
        # s3:https://<server>/<bucket>[/<folder>]: restic would retry a wrong bucket name for many minutes.
        parts = str(backup["repository"])[3:].split("://")[-1].split("/")
        bucket = parts[1] if len(parts) > 1 else ""
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
            fail(f"backup.repository: the bucket name must be 3 to 63 small letters, numbers, dots or -, "
                 f"like s3:https://s3.example.com/my-bucket, got '{bucket}'")
    if not TIME.fullmatch(str(backup.get("time", "02:00"))):
        fail(f"backup.time must look like \"02:00\", in quotes (without quotes it is read as a number), "
             f"got {backup.get('time')}")
    for key in ("keep_daily", "keep_weekly", "keep_monthly"):
        value = backup.get(key, 1)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            fail(f"backup.{key} must be a number, got {value}")


def check_monitoring(monitoring):
    """monitoring: where alerts go. Only used with the victoria app."""
    if monitoring is None:
        return
    if not isinstance(monitoring, dict):
        fail("monitoring must look like { telegram: { bot_token: ..., chat_id: ... } }")
    unknown = set(monitoring) - MONITORING_KEYS
    if unknown:
        fail(f"unknown setting monitoring.{', monitoring.'.join(sorted(unknown))} (typo?)")
    if not any(monitoring.get(key) for key in ("telegram", "email", "webhook")):
        fail("monitoring needs at least one place for alerts: telegram, email or webhook")
    telegram = monitoring.get("telegram")
    if telegram is not None:
        if not isinstance(telegram, dict) or set(telegram) != {"bot_token", "chat_id"}:
            fail("monitoring.telegram must look like { bot_token: \"123:ABC\", chat_id: -1001234 }")
        if not isinstance(telegram["chat_id"], int) or isinstance(telegram["chat_id"], bool):
            fail(f"monitoring.telegram.chat_id must be a number, got {telegram['chat_id']}")
    email = monitoring.get("email")
    if email is not None:
        if not isinstance(email, dict) or set(email) - {"to", "from", "smarthost", "username", "password", "tls"}:
            fail("monitoring.email must look like { to: ops@example.com, from: alerts@example.com, smarthost: smtp.example.com:587 }")
        for key in ("to", "from", "smarthost"):
            if not email.get(key):
                fail(f"monitoring.email.{key} is required")
        if not re.fullmatch(r"\S+:[0-9]+", str(email["smarthost"])):
            fail(f"monitoring.email.smarthost must be host:port, like smtp.example.com:587, got {email['smarthost']}")
        if bool(email.get("username")) != bool(email.get("password")):
            fail("monitoring.email: set both username and password, or neither")
        if email.get("tls", True) not in (True, False):
            fail("monitoring.email.tls must be true or false")
    for key in ("webhook", "heartbeat_url"):
        if monitoring.get(key) and not URL.fullmatch(str(monitoring[key])):
            fail(f"monitoring.{key} must be a URL like https://..., got {monitoring[key]}")
    days = monitoring.get("keep_days", 30)
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        fail(f"monitoring.keep_days must be a number of days, got {days}")


def check_settings(cfg, bundle):
    if "arch" in cfg:
        fail("arch was removed: Ansibro runs on Intel/AMD (amd64) servers only. Delete arch from config.yml")
    unknown = set(cfg) - CONFIG_KEYS
    if unknown:
        fail(f"unknown setting {', '.join(sorted(unknown))} (typo?)")
    unknown = set(cfg.get("ssh") or {}) - SSH_KEYS
    if unknown:
        fail(f"unknown setting ssh.{', ssh.'.join(sorted(unknown))} (typo?)")
    if not cfg.get("domain"):
        fail("domain is required")
    if not DOMAIN.fullmatch(str(cfg["domain"])):
        fail(f"domain must be a plain lowercase name like example.com, got {cfg['domain']}")
    tls = cfg.get("tls", "letsencrypt")
    if tls not in ("letsencrypt", "selfsigned", "custom"):
        fail("tls must be letsencrypt, selfsigned or custom")
    if tls == "letsencrypt" and not cfg.get("acme_email"):
        fail("acme_email is required for tls: letsencrypt")
    if tls == "custom" and not (cfg.get("tls_cert") and cfg.get("tls_key")):
        fail("tls: custom needs tls_cert and tls_key")
    if bundle and tls == "letsencrypt" and not cfg.get("acme_server"):
        fail("offline install: Let's Encrypt needs internet. Use tls: selfsigned or custom, "
             "or set acme_server to an ACME server in your network")
    if cfg.get("acme_ca_cert") and not cfg.get("acme_server"):
        fail("acme_ca_cert is only used with acme_server")
    port = (cfg.get("ssh") or {}).get("port", 22)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        fail(f"ssh.port must be a number from 1 to 65535, got {port}")
    check_ip_list("ssh.allow_from", (cfg.get("ssh") or {}).get("allow_from"))
    check_ip_list("admin_allow_from", cfg.get("admin_allow_from"))
    check_firewall_allow(cfg.get("firewall_allow"))
    check_backup(cfg.get("backup"))
    check_monitoring(cfg.get("monitoring"))
    if cfg.get("wireguard", False) not in (True, False):
        fail("wireguard must be true or false")
    if cfg.get("orchestrator", "swarm") not in ORCHESTRATORS:
        fail("orchestrator must be swarm or k3s")


def build_nodes(nodes, wireguard):
    if not nodes:
        fail("nodes is empty")
    if not isinstance(nodes, list) or not all(isinstance(node, dict) for node in nodes):
        fail("nodes must be a list, like - { name: swarm1, ip: 10.0.0.11, role: manager }")

    groups = {g: [] for g in GROUPS.values()}
    hostvars = {}
    for node in nodes:
        name, ip, role = node.get("name"), node.get("ip"), node.get("role")
        if "gpu" in node:
            fail(f"node {name}: gpu was removed (Ansibro no longer sets up GPU servers). Delete gpu from config.yml")
        unknown = set(node) - NODE_KEYS
        if unknown:
            fail(f"node {name}: unknown setting {', '.join(sorted(unknown))} (typo?)")
        if not name or not ip:
            fail(f"every node needs name and ip: {node}")
        if not NODE_NAME.fullmatch(str(name)) or name in RESERVED_NAMES:
            fail(f"node name {name}: use only lowercase letters, numbers and -. "
                 f"These names are taken: {', '.join(sorted(RESERVED_NAMES))}")
        if role not in GROUPS:
            fail(f"{name}: role must be one of {', '.join(GROUPS)}")
        if node.get("labels") and role == "standalone":
            fail(f"{name}: labels only work on swarm nodes (manager or worker)")
        labels = node.get("labels") or {}
        if not isinstance(labels, dict):
            fail(f"{name}: labels must look like {{ tier: app }}")
        for key, value in labels.items():
            if not LABEL.fullmatch(str(key)) or not LABEL.fullmatch(str(value)):
                fail(f"{name}: label {key}: {value} may only use letters, numbers, . _ and -")
        if name in hostvars:
            fail(f"duplicate node name {name}")
        try:
            address = ipaddress.IPv4Address(ip)
        except ValueError:
            fail(f"{name}: ip must be an IPv4 address, got {ip}")
        for cidr in (SWARM_ADDRESS_POOL,) + K3S_CIDRS:
            if address in ipaddress.ip_network(cidr):
                fail(f"{name}: ip {ip} is inside {cidr}, which the cluster uses for its own networks")
        if any(h["node_ip"] == ip for h in hostvars.values()):
            fail(f"duplicate ip {ip}")

        # host: the server's own address (SSH, WireGuard). ip: the address the cluster uses.
        host = node.get("host") or ip
        if wireguard and not node.get("host"):
            fail(f"{name}: with wireguard, every node needs host (its real address); ip is its WireGuard address")
        try:
            ipaddress.IPv4Address(host)
        except ValueError:
            fail(f"{name}: host must be an IPv4 address, got {host}")
        if wireguard and host == ip:
            fail(f"{name}: with wireguard, ip is a new address on the WireGuard network, so it must differ from host")
        if node.get("host") and any(h["node_host"] == host for h in hostvars.values()):
            fail(f"duplicate host {host}")

        groups[GROUPS[role]].append(name)
        hostvars[name] = {
            "ansible_host": host,
            "node_ip": ip,
            "node_host": host,
            "node_role": role,
            "node_labels": {str(k): str(v) for k, v in (node.get("labels") or {}).items()},
            "node_apps": [],
        }

    if not groups["managers"]:
        fail("at least one manager is required")
    if len(groups["managers"]) % 2 == 0:
        fail("use an odd number of managers (1, 3 or 5)")
    return groups, hostvars


def build_apps(apps, catalog, hostvars, monitoring=None):
    """Return ({app: "swarm" or first node name}, {app: [all its node names]}) in catalog order.

    Apps with "servers" in the catalog can run on more than one server: [db1, db2].
    The first one is the main server (the primary), apps use that one.
    """
    apps = dict(apps or {})
    app_nodes = {}
    for name, target in apps.items():
        if name not in catalog:
            fail(f"unknown app {name}, available: {', '.join(catalog)}")
        if isinstance(target, list):
            allowed = catalog[name].get("servers")
            if not allowed:
                fail(f"{name} runs on one server only, write it as '{name}: <node name>'")
            if len(target) not in allowed:
                fail(f"{name}: list {' or '.join(map(str, allowed))} servers, got {len(target)}")
            if len(set(target)) != len(target):
                fail(f"{name}: a server is listed twice")
            for node in target:
                if node not in hostvars:
                    fail(f"{name}: {node} is not a node name")
            app_nodes[name] = target
            apps[name] = target[0]
            continue
        if not isinstance(target, str):
            fail(f"{name}: write it as '{name}: swarm' or '{name}: <node name>'")
        if target == "cluster":  # the same as swarm; reads better with orchestrator: k3s
            target = apps[name] = "swarm"
        runs_on = catalog[name]["runs_on"]
        if target == "swarm" and runs_on != "swarm":
            fail(f"{name} runs on one server, set it to a node name")
        elif target != "swarm" and target not in hostvars:
            fail(f"{name}: {target} is not in nodes. Use one of your node names: {', '.join(hostvars)}")
        elif target != "swarm" and runs_on != "node":
            fail(f"{name} runs as a swarm service, set it to swarm")

    seen = {}
    for name in apps:
        category = catalog[name]["category"]
        if category in seen:
            fail(f"{seen[category]} and {name} are both {category}, pick one")
        seen[category] = name
    categories = {catalog[name]["category"] for name in apps}
    for name in apps:
        for dep in catalog[name].get("requires", []):
            if dep not in apps and dep not in categories:
                choices = [app for app, info in catalog.items() if info["category"] == dep]
                what = f"a {dep} ({' or '.join(choices)})" if choices else dep
                fail(f"{name} needs {what}, add it to apps")

    # Monitoring sends alerts, so it needs to know where; and someone must watch the monitoring server.
    monitoring_app = next((name for name in MONITORING_APPS if name in apps), None)
    if monitoring_app and not monitoring:
        fail(f"{monitoring_app} needs monitoring: in config.yml, to know where to send alerts (telegram, email or webhook)")
    if monitoring and not monitoring_app:
        fail("monitoring: is set, but victoria is not installed. monitoring: tells victoria where to send alerts "
             "(beszel has its own alert settings in its web page). Add victoria to apps, or remove monitoring:")
    if monitoring_app and apps.get("uptimekuma") == apps[monitoring_app]:
        fail(f"uptimekuma watches the monitoring server, so put it on another server than {monitoring_app}")

    ordered = {name: apps[name] for name in catalog if name in apps}
    for name, target in ordered.items():
        if target != "swarm":
            app_nodes.setdefault(name, [target])
            for node in app_nodes[name]:
                hostvars[node]["node_apps"].append(name)
    return ordered, app_nodes


def build(cfg, base_dir):
    bundle = load_bundle()
    check_settings(cfg, bundle)
    groups, hostvars = build_nodes(cfg.get("nodes"), cfg.get("wireguard", False))
    catalog = load_yaml(os.path.join(HERE, "catalog.yml"))
    apps, app_nodes = build_apps(cfg.get("apps"), catalog, hostvars, cfg.get("monitoring"))
    orchestrator = cfg.get("orchestrator", "swarm")
    if orchestrator == "k3s":
        for name, target in apps.items():
            if target == "swarm" and name not in K3S_CLUSTER_APPS:
                fail(f"{name} manages Docker Swarm, so it does not run on k3s (use portainer)")
    # The tier of each cluster server (a tier in config.yml labels wins). Apps run on tier=app servers.
    #   data:     runs server apps (databases, ...)
    #   app:      runs the apps. Workers, or the managers when there are no workers.
    #   gateway:  a swarm manager when there are workers: Traefik runs there, the apps on the workers.
    #   control:  a k3s manager when there are workers: only runs the cluster; Traefik and apps run on the workers.
    manager_tier = "control" if orchestrator == "k3s" else "gateway"
    for name in groups["managers"] + groups["workers"]:
        if hostvars[name]["node_apps"]:
            tier = "data"
        elif hostvars[name]["node_role"] == "manager" and groups["workers"]:
            tier = manager_tier
        else:
            tier = "app"
        hostvars[name]["node_labels"].setdefault("tier", tier)

    def from_config_dir(path):
        return os.path.join(base_dir, os.path.expanduser(path))

    ssh = cfg.get("ssh") or {}
    all_vars = {k: v for k, v in cfg.items() if k not in ("nodes", "apps")}
    all_vars.setdefault("tls", "letsencrypt")  # so roles can use tls without a default
    for key in ("tls_cert", "tls_key", "acme_ca_cert"):
        if key in cfg:
            all_vars[key] = from_config_dir(cfg[key])
    all_vars.update(load_yaml(os.path.join(HERE, "versions.yml")))
    all_vars.update(
        offline=bool(bundle),
        bundle=bundle,
        apps=apps,
        app_nodes=app_nodes,
        catalog=catalog,
        swarm_apps=[name for name, target in apps.items() if target == "swarm"],
        swarm_address_pool=SWARM_ADDRESS_POOL,
        registry_port=REGISTRY_PORT,
        kong_subnet=KONG_SUBNET,
        wireguard=cfg.get("wireguard", False),
        orchestrator=orchestrator,
        wireguard_port=WIREGUARD_PORT,
        ansible_user=ssh.get("user", "ubuntu"),
        ansible_port=ssh.get("port", 22),
        ansible_ssh_private_key_file=from_config_dir(ssh.get("key", "~/.ssh/id_ed25519")),
    )

    return {
        "_meta": {"hostvars": hostvars},
        "all": {"children": ["swarm", "standalone"], "vars": all_vars},
        "swarm": {"children": ["managers", "workers"]},
        "managers": {"hosts": groups["managers"]},
        "workers": {"hosts": groups["workers"]},
        "standalone": {"hosts": groups["standalone"]},
    }


def check_ready(cfg, base_dir):
    """Values a first install often forgets to change. install.sh checks these before a real run.
    A wrong value stops the install; a risky one (admin pages open to everyone) is a warning, because
    clusters that already run with it must still be able to upgrade."""
    domain = str(cfg.get("domain", ""))
    if domain == "example.com" or domain.endswith(".example.com"):
        fail(f"domain is still {cfg['domain']}. Write your own domain.")
    email = str(cfg.get("acme_email", ""))
    if cfg.get("tls", "letsencrypt") == "letsencrypt" and (email.endswith("@example.com") or email.endswith(".example.com")):
        fail("acme_email is still an example.com address. Write your own email (Let's Encrypt refuses example.com).")
    key = os.path.normpath(os.path.join(base_dir, os.path.expanduser((cfg.get("ssh") or {}).get("key", "~/.ssh/id_ed25519"))))
    if not os.path.exists(key):
        fail(f"ssh.key: {key} not found. Use the private SSH key that logs in to your servers.")
    if "traefik" in (cfg.get("apps") or {}) and not cfg.get("admin_allow_from"):
        warn("admin_allow_from is empty, so the admin web pages (Traefik, Portainer, Grafana, ...) are open to "
             "the whole internet, protected only by their logins. Set admin_allow_from in config.yml to the IPs "
             "you work from (office, VPN), then run ./install.sh again.")


def main():
    if "--host" in sys.argv:
        print("{}")
        return
    cfg, base_dir = load_config()
    inventory = build(cfg, base_dir)
    if "--ready" in sys.argv:
        check_ready(cfg, base_dir)
    print(json.dumps(inventory, indent=2))


if __name__ == "__main__":
    main()
