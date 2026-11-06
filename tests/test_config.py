#!/usr/bin/env python3
"""Check that inventory.py accepts config.example.yml and refuses common mistakes.

Run it from the project folder (CI runs it too):

    .venv/bin/python tests/test_config.py

Each case changes config.example.yml a little and checks the error message.
No servers are needed.
"""

import copy
import glob
import json
import os
import subprocess
import sys
import tempfile

import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = yaml.safe_load(open(os.path.join(HERE, "config.example.yml")))

# (what we test, how we change the config, text the error must contain)
CASES = [
    ("missing domain", lambda c: c.pop("domain"), "domain is required"),
    ("letsencrypt without acme_email", lambda c: c.pop("acme_email"), "acme_email is required"),
    ("custom TLS without cert", lambda c: c.update(tls="custom"), "needs tls_cert and tls_key"),
    ("unknown tls value", lambda c: c.update(tls="tls13"), "tls must be"),
    ("typo in a setting", lambda c: c.update(timzone="x"), "unknown setting timzone"),
    ("typo inside ssh", lambda c: c["ssh"].update(alow_from=[]), "unknown setting ssh.alow_from"),
    ("typo inside a node", lambda c: c["nodes"][0].update(rol="manager"), "unknown setting rol"),
    ("removed setting arch", lambda c: c.update(arch="amd64"), "arch was removed"),
    ("removed setting gpu", lambda c: c["nodes"][0].update(gpu=True), "gpu was removed"),
    ("bad node name", lambda c: c["nodes"][0].update(name="Swarm_1"), "node name Swarm_1"),
    ("reserved node name", lambda c: c["nodes"][0].update(name="swarm"), "node name swarm"),
    ("duplicate ip", lambda c: c["nodes"][1].update(ip="10.0.0.11"), "duplicate ip"),
    ("IPv6 address", lambda c: c["nodes"][1].update(ip="fd00::1"), "must be an IPv4 address"),
    ("even number of managers", lambda c: c["nodes"][1].update(role="manager"), "odd number of managers"),
    ("no manager", lambda c: c["nodes"][0].update(role="worker"), "at least one manager"),
    ("unknown role", lambda c: c["nodes"][0].update(role="boss"), "role must be one of"),
    ("unknown app", lambda c: c["apps"].update(mysql="data1"), "unknown app mysql"),
    ("server app on swarm", lambda c: c["apps"].update(postgres="swarm"), "postgres runs on one server"),
    ("swarm app on a server", lambda c: c["apps"].update(traefik="data1"), "traefik runs as a swarm service"),
    ("app on unknown node", lambda c: c["apps"].update(postgres="nowhere"), "nowhere is not in nodes"),
    ("two apps in one category", lambda c: c["apps"].update(mariadb="data1"), "both database"),
    ("kong without postgres",
     lambda c: (c["apps"].update(kong="swarm", mariadb="data1"), c["apps"].pop("postgres")), "kong needs postgres"),
    ("portainer without traefik", lambda c: c["apps"].pop("traefik"), "portainer needs traefik"),
    ("authelia without cache",
     lambda c: (c["apps"].update(authelia="swarm"), c["apps"].pop("redis")), "needs a cache (redis or valkey)"),
    ("long app form", lambda c: c["apps"].update(postgres={"on": "data1"}), "write it as"),
    ("list for a one-server app", lambda c: c["apps"].update(rustfs=["data1", "swarm1"]), "runs on one server only"),
    ("cache on 2 servers", lambda c: c["apps"].update(redis=["data1", "swarm1"]), "list 1 or 3 servers"),
    ("garage on 2 servers", lambda c: c["apps"].update(rustfs=None) or c["apps"].pop("rustfs")
     or c["apps"].update(garage=["data1", "swarm1"]), "list 1 or 3 servers"),
    ("replica on unknown node", lambda c: c["apps"].update(postgres=["data1", "nowhere"]), "nowhere is not a node name"),
    ("same server twice", lambda c: c["apps"].update(postgres=["data1", "data1"]), "listed twice"),
    ("ssh port as text", lambda c: c["ssh"].update(port="22"), "ssh.port must be a number"),
    ("allow_from as text, not a list", lambda c: c["ssh"].update(allow_from="203.0.113.0/24"), "must be a list"),
    ("allow_from with a bad IP", lambda c: c["ssh"].update(allow_from=["300.1.1.1"]), "not an IP or range"),
    ("admin_allow_from as text", lambda c: c.update(admin_allow_from="203.0.113.0/24"), "must be a list"),
    ("labels on a standalone node", lambda c: c["nodes"][2].update(labels={"a": "b"}), "labels only work on swarm nodes"),
    ("acme_ca_cert without acme_server", lambda c: c.update(acme_ca_cert="ca.pem"), "only used with acme_server"),
    ("domain with https://", lambda c: c.update(domain="https://example.com"), "plain lowercase name"),
    ("nodes as a dict", lambda c: c.update(nodes={"swarm1": "10.0.0.11"}), "nodes must be a list"),
    ("labels as a list", lambda c: c["nodes"][1].update(labels=["tier=app"]), "labels must look like"),
    ("label with a space", lambda c: c["nodes"][1].update(labels={"tier": "my app"}), "may only use letters"),
    ("node named localhost", lambda c: c["nodes"][0].update(name="localhost"), "node name localhost"),
    ("server ip inside the swarm range", lambda c: c["nodes"][1].update(ip="10.200.1.5"), "which the cluster uses"),
    ("server ip inside the k3s pod range", lambda c: c["nodes"][1].update(ip="10.42.0.5"), "which the cluster uses"),
    ("unknown orchestrator", lambda c: c.update(orchestrator="nomad"), "orchestrator must be swarm or k3s"),
    ("swarmpit on k3s", lambda c: (c.update(orchestrator="k3s"), c["apps"].pop("portainer", None),
     c["apps"].update(swarmpit="swarm")), "manages Docker Swarm"),
    ("firewall_allow as text", lambda c: c.update(firewall_allow="51820/udp"), "firewall_allow must be a list"),
    ("firewall_allow bad port", lambda c: c.update(firewall_allow=[{"port": 70000}]), "port must be a number"),
    ("firewall_allow bad proto", lambda c: c.update(firewall_allow=[{"port": 53, "proto": "icmp"}]), "proto must be tcp or udp"),
    ("firewall_allow typo", lambda c: c.update(firewall_allow=[{"port": 53, "prot": "udp"}]), "must look like"),
    ("firewall_allow bad from", lambda c: c.update(firewall_allow=[{"port": 53, "from": "lan"}]), "not an IP or range"),
    ("wireguard as text", lambda c: c.update(wireguard="yes"), "wireguard must be true or false"),
    ("wireguard without host", lambda c: c.update(wireguard=True), "every node needs host"),
    ("host that is not an IP", lambda c: c["nodes"][0].update(host="swarm1.example.com"), "host must be an IPv4 address"),
    ("duplicate host",
     lambda c: (c["nodes"][0].update(host="203.0.113.5"), c["nodes"][1].update(host="203.0.113.5")), "duplicate host"),
    ("backup as text", lambda c: c.update(backup="s3://bucket"), "backup must look like"),
    ("backup without repository", lambda c: c.update(backup={"time": "02:00"}), "backup.repository is required"),
    ("backup typo", lambda c: c.update(backup={"repository": "/mnt/b", "keep_days": 7}), "unknown setting backup.keep_days"),
    ("s3 bucket name too short", lambda c: c.update(backup={"repository": "s3:http://10.0.0.5:9000/v1",
                                                             "s3_access_key": "a", "s3_secret_key": "b"}),
     "bucket name must be 3 to 63"),
    ("s3 backup without keys", lambda c: c.update(backup={"repository": "s3:https://s3.example.com/b"}), "needs s3_access_key"),
    ("backup time without quotes", lambda c: c.update(backup={"repository": "/mnt/b", "time": 120}), "must look like"),
    ("backup keep as text", lambda c: c.update(backup={"repository": "/mnt/b", "keep_daily": "7"}), "must be a number"),
    ("wireguard with host same as ip",
     lambda c: (c.update(wireguard=True), [n.update(host=n["ip"]) for n in c["nodes"]]), "must differ from host"),
    ("monitoring app without monitoring", lambda c: c["apps"].update(victoria="data1"), "needs monitoring: in config.yml"),
    ("monitoring without the app", lambda c: c.update(monitoring={"webhook": "https://x.example.com"}), "victoria is not installed"),
    ("two monitoring apps", lambda c: (monitored(c), c["apps"].update(beszel="swarm2")), "both monitoring"),
    ("monitoring: with beszel only", lambda c: (c["apps"].update(beszel="data1"), c.update(monitoring={"webhook": "https://x.example.com"})), "victoria is not installed"),
    ("monitoring with no place for alerts", lambda c: (monitored(c), c.update(monitoring={"keep_days": 30})), "at least one place"),
    ("monitoring typo", lambda c: (monitored(c), c["monitoring"].update(slack="x")), "unknown setting monitoring.slack"),
    ("telegram chat_id as text",
     lambda c: (monitored(c), c["monitoring"].update(telegram={"bot_token": "1:A", "chat_id": "abc"})), "must be a number"),
    ("telegram without chat_id", lambda c: (monitored(c), c["monitoring"].update(telegram={"bot_token": "1:A"})), "must look like"),
    ("email without smarthost",
     lambda c: (monitored(c), c["monitoring"].update(email={"to": "a@x.com", "from": "b@x.com"})), "email.smarthost is required"),
    ("email smarthost without port",
     lambda c: (monitored(c), c["monitoring"].update(email={"to": "a@x.com", "from": "b@x.com", "smarthost": "smtp.x.com"})),
     "must be host:port"),
    ("email user without password",
     lambda c: (monitored(c), c["monitoring"].update(email={"to": "a@x.com", "from": "b@x.com", "smarthost": "s:25", "username": "u"})),
     "both username and password"),
    ("webhook not a URL", lambda c: (monitored(c), c["monitoring"].update(webhook="hooks.slack.com/x")), "must be a URL"),
    ("keep_days as text", lambda c: (monitored(c), c["monitoring"].update(keep_days="30d")), "must be a number of days"),
    ("uptimekuma on the monitoring server",
     lambda c: (monitored(c), c["apps"].update(uptimekuma="data1")), "put it on another server"),
]


def monitored(c):
    """Victoria on data1, alerts to a webhook."""
    c["apps"]["victoria"] = "data1"
    c["monitoring"] = {"webhook": "https://hooks.example.com/alerts"}


def with_wireguard(c):
    c["wireguard"] = True
    for i, node in enumerate(c["nodes"]):
        node["host"] = node["ip"]
        node["ip"] = f"10.99.0.{i + 1}"


# Settings that must be accepted.
GOOD = [
    ("host on one node", lambda c: c["nodes"][0].update(host="203.0.113.5")),
    ("wireguard with host on every node", with_wireguard),
    ("backup to S3", lambda c: c.update(backup={"repository": "s3:https://s3.example.com/my-bucket", "s3_access_key": "a",
                                                 "s3_secret_key": "b", "time": "03:30", "keep_daily": 14})),
    ("backup to a folder", lambda c: c.update(backup={"repository": "/mnt/backup"})),
    ("victoria with a webhook", monitored),
    ("uptimekuma and beszel together", lambda c: c["apps"].update(uptimekuma="data1", beszel="data1")),
    ("beszel without monitoring:", lambda c: c["apps"].update(beszel="data1")),
    ("victoria with every alert channel", lambda c: (
        c["apps"].update(victoria="data1", uptimekuma="swarm2"),
        c.update(monitoring={
            "telegram": {"bot_token": "123:ABC", "chat_id": -1001234},
            "email": {"to": "ops@example.com", "from": "alerts@example.com", "smarthost": "smtp.example.com:587",
                      "username": "u", "password": "p", "tls": True},
            "webhook": "https://hooks.slack.com/services/x",
            "heartbeat_url": "https://hc-ping.com/abc",
            "keep_days": 14}))),
    ("k3s with server apps and traefik", lambda c: (c.update(orchestrator="k3s"),
     [c["apps"].pop(a) for a in list(c["apps"]) if a not in ("traefik", "postgres", "redis", "rustfs")])),
    ("k3s with portainer, kong and authelia", lambda c: (c.update(orchestrator="k3s"),
     c["apps"].update(portainer="cluster", kong="cluster", authelia="cluster"))),
    ("redis and mariadb on 3 servers", lambda c: (c["apps"].pop("postgres"), [c["apps"].pop(a, None) for a in ("kong",)],
     c["apps"].update(redis=["data1", "swarm1", "swarm2"], mariadb=["data1", "swarm1", "swarm2"]))),
    ("postgres with a replica", lambda c: c["apps"].update(postgres=["data1", "swarm2"])),
]


def run(cfg, output=None):
    """Write cfg to a file, run inventory.py on it. Returns (exit code, error text).
    With output=[], the inventory (JSON) is added to that list."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.yml")
        with open(path, "w") as f:
            yaml.safe_dump(cfg, f)
        p = subprocess.run([sys.executable, os.path.join(HERE, "inventory.py"), "--list"],
                           capture_output=True, text=True, cwd=HERE, env={**os.environ, "ANSIBRO_CONFIG": path})
    if output is not None and p.returncode == 0:
        output.append(json.loads(p.stdout))
    return p.returncode, p.stderr.strip()


failed = 0
code, err = run(BASE)
print(f"{'PASS' if code == 0 else 'FAIL'}  config.example.yml is accepted" + (f"  ({err})" if code else ""))
failed += code != 0

for name, change, expected in CASES:
    cfg = copy.deepcopy(BASE)
    change(cfg)
    code, err = run(cfg)
    ok = code != 0 and expected in err
    failed += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name} is refused" + ("" if ok else f"  (got: {err or 'accepted'})"))

for name, change in GOOD:
    cfg = copy.deepcopy(BASE)
    change(cfg)
    code, err = run(cfg)
    failed += code != 0
    print(f"{'PASS' if code == 0 else 'FAIL'}  {name} is accepted" + (f"  ({err})" if code else ""))

# install.sh --ready: example values are refused, but a domain that only ends in "example.com" is fine.
KEY = os.path.join(HERE, "inventory.py")  # any file that exists, as ssh.key
READY = [
    ("example.com domain", {"domain": "example.com"}, "domain is still"),
    ("sub.example.com domain", {"domain": "apps.example.com"}, "domain is still"),
    ("example.com email", {"acme_email": "me@example.com"}, "acme_email is still"),
    ("sub.example.com email", {"acme_email": "me@mail.example.com"}, "acme_email is still"),
    ("myexample.com domain and email", {"acme_email": "me@myexample.com"}, None),
]
for name, change, expected in READY:
    cfg = copy.deepcopy(BASE)
    cfg.update(domain="myexample.com", acme_email="ops@myexample.com", ssh={**cfg.get("ssh", {}), "key": KEY})
    cfg.update(change)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.yml")
        with open(path, "w") as f:
            yaml.safe_dump(cfg, f)
        p = subprocess.run([sys.executable, os.path.join(HERE, "inventory.py"), "--list", "--ready"],
                           capture_output=True, text=True, cwd=HERE, env={**os.environ, "ANSIBRO_CONFIG": path})
    ok = p.returncode == 0 if expected is None else p.returncode != 0 and expected in p.stderr
    failed += not ok
    print(f"{'PASS' if ok else 'FAIL'}  --ready: {name} is {'accepted' if expected is None else 'refused'}"
          + ("" if ok else f"  (got: {p.stderr.strip() or 'accepted'})"))

# The ready-to-use configs in examples/: accepted online and offline (tls: selfsigned),
# and every server gets the tier its comment promises.
TIERS = {
    "swarm-1-server.yml": {"server1": "data"},  # one server: it keeps the data, and apps may run anywhere
    "swarm-2-servers.yml": {"manager1": "app"},
    "swarm-3-servers.yml": {"manager1": "gateway", "worker1": "app"},
    "swarm-ha.yml": {"manager1": "gateway", "manager3": "gateway", "worker1": "app", "worker3": "app"},
    "k3s-4-servers.yml": {"master1": "control", "worker1": "app", "worker2": "app"},
    "k3s-ha.yml": {"master1": "control", "master3": "control", "worker1": "app", "worker3": "app"},
}
examples = sorted(glob.glob(os.path.join(HERE, "examples", "*.yml")))
for path in examples:
    name = os.path.basename(path)
    for mode in ("online", "offline"):
        cfg = yaml.safe_load(open(path))
        if mode == "offline":
            cfg["tls"] = "selfsigned"
            cfg.pop("acme_email", None)
        inventory = []
        code, err = run(cfg, inventory)
        tiers = {host: hv["node_labels"].get("tier") for host, hv in inventory[0]["_meta"]["hostvars"].items()} if inventory else {}
        wrong = {host: tiers.get(host) for host, tier in TIERS.get(name, {}).items() if tiers.get(host) != tier}
        ok = code == 0 and name in TIERS and not wrong
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  examples/{name} ({mode}) is accepted, tiers as described"
              + ("" if ok else f"  ({err or wrong or 'no tiers listed in TIERS'})"))

total = len(CASES) + len(GOOD) + len(READY) + 1 + 2 * len(examples)
print(f"\n{total - failed} passed, {failed} failed")
sys.exit(1 if failed else 0)
