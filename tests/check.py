#!/usr/bin/env python3
"""End-to-end check: test every installed app for real.

Run it after ./install.sh, on the same machine and in the same folder:

    .venv/bin/python tests/check.py [config.yml]

It reads config.yml, logs in to each app with the passwords in state/secrets/,
and prints PASS or FAIL per check. Exit code 0 = everything passed.
The checks run on the first manager: here if this is the first manager,
otherwise over SSH with the same settings as the installer.
Passwords are sent through stdin, so they never show up in a process list.
"""

import atexit
import datetime
import hashlib
import hmac
import json
import os
import shlex
import socket
import subprocess
import sys
import time

import yaml

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
if len(sys.argv) > 1:
    os.environ["ANSIBRO_CONFIG"] = sys.argv[1]
os.environ.setdefault("ANSIBRO_CONFIG", "config.yml")

# state/ (the passwords) may be kept encrypted: open it like install.sh does, and close it at the end.
# Only when it is closed now: if you (or install.sh) opened it, it stays open.
STATE_SH = os.path.join(HERE, "scripts", "state.sh")
if os.path.exists(os.path.join(HERE, "state.age")):
    subprocess.run([STATE_SH, "open"], check=True)
    atexit.register(subprocess.run, [STATE_SH, "close"], check=True)

import inventory  # noqa: E402

inv = inventory.build(*inventory.load_config())
CFG = inv["all"]["vars"]
HOSTS = inv["_meta"]["hostvars"]
APPS = CFG["apps"]
DOMAIN = CFG["domain"]
LEADER = inv["managers"]["hosts"][0]
LEADER_IP = HOSTS[LEADER]["node_ip"]
REGISTRY = f"{LEADER_IP}:{CFG['registry_port']}"
# Where Traefik answers: on k3s the first tier=app server (a worker, if any), on Swarm the first manager.
CLUSTER = inv["managers"]["hosts"] + inv["workers"]["hosts"]
WEB_IP = next((HOSTS[h]["node_ip"] for h in CLUSTER if CFG["orchestrator"] == "k3s"
               and HOSTS[h]["node_labels"].get("tier") == "app"), LEADER_IP)
IMAGES = CFG["images"]
WEB = "traefik" in APPS  # web pages only exist with traefik
# psql comes from the PostgreSQL image in the registry: spilo with Patroni (2 or more servers).
PG_IMAGE = "spilo" if len(CFG["app_nodes"].get("postgres", [])) > 1 else "postgres"
ON_LEADER = socket.gethostname() == LEADER  # the installer sets each server's hostname to its name
results = []


# ---------- helpers ----------

def secret(name):
    with open(os.path.join(HERE, "state", "secrets", name)) as f:
        return f.read().strip()


def ip_of(app):
    return HOSTS[APPS[app]]["node_ip"]


def on_node(node, cmd, stdin=None):
    """Run a command on a server: here if this is that server, else over SSH from here.
    Returns (exit code, output)."""
    if socket.gethostname() != node:
        cmd = ["ssh", "-i", CFG["ansible_ssh_private_key_file"], "-p", str(CFG["ansible_port"]),
               "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
               f"{CFG['ansible_user']}@{HOSTS[node]['node_host']}", shlex.join(cmd)]
    p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=180)
    return p.returncode, (p.stdout + p.stderr).strip()


def on_leader(cmd, stdin=None):
    """Run a command on the first manager. Returns (exit code, output)."""
    return on_node(LEADER, cmd, stdin)


def curl(url, user=None, data=None, headers=(), resolve=None, method=None):
    """HTTP request from the first manager. Returns (status, body). Secrets go in through stdin."""
    config = [f'url = "{url}"', 'silent', 'insecure', 'max-time = 20', 'write-out = "\\n%{http_code}"']
    if method:
        config.append(f'request = "{method}"')
    if resolve:
        config.append(f'resolve = "{resolve}"')
    if user:
        config.append(f'user = "{user}"')
    if data is not None:
        config.append(f"data = {json.dumps(data)}")
    config += [f'header = "{h}"' for h in headers]
    _, out = on_leader(["curl", "--config", "-"], stdin="\n".join(config) + "\n")
    body, _, code = out.rpartition("\n")
    return code, body


def https(sub, path="/", **kwargs):
    """Request https://<sub>.<domain><path> through Traefik.

    Traefik looks for new apps every 5 seconds, so right after an install a page can
    answer 404 or 502 for a moment. Try again a few times before reporting it.
    """
    host = f"{sub}.{DOMAIN}"
    for _ in range(4):
        code, body = curl(f"https://{host}{path}", resolve=f"{host}:443:{WEB_IP}", **kwargs)
        if code not in ("404", "502", "503") or (sub == "kong" and "no Route matched" in body):
            break
        time.sleep(3)
    return code, body


def client(image, *args, env=()):
    """Run a tool from an app image (for example psql) on the first manager. env goes in through stdin."""
    cmd = ["sudo", "docker", "run", "--rm", "--quiet", "--network", "host", "--env-file", "/dev/stdin",
           f"{REGISTRY}/{image}:{IMAGES[image]['tag']}", *args]
    return on_leader(cmd, stdin="\n".join(env) + "\n")


def python_on_leader(code, data):
    """Run a small Python program on the first manager; data goes in as JSON on stdin."""
    return on_leader(["python3", "-c", code], stdin=json.dumps(data))


def admin_login(name, sub, path="/", ok=("200",)):
    """An admin page needs a login: the Traefik password, or Authelia or Keycloak (with a second factor)
    when installed. Returns (status, body) after logging in with the Traefik password, or None with SSO."""
    sso = "Authelia" if "authelia" in APPS else "Keycloak" if "keycloak" in APPS else ""
    code, body = https(sub, path)
    check(f"{name} needs a login", code in ("401", "302", "403"), code)
    if sso == "Keycloak":
        check(f"{name} sends you to the Keycloak login", f"keycloak.{DOMAIN}/realms/ansibro" in body or code == "302", body[-120:])
    if sso:
        print(f"SKIP  {name} opens after login  ({sso} login with a second factor)")
        return None
    code, body = https(sub, path, user="admin:" + secret("traefik_admin"))
    check(f"{name} opens with the password", code in ok, code)
    return code, body


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if not ok and detail else ""))


def s3_list_buckets(endpoint, access_key, secret_key, region, method="GET", path="/"):
    """Call S3 with AWS signature v4: ListBuckets, or with method="PUT", path="/<name>" CreateBucket.
    Returns the HTTP status."""
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    host = endpoint.split("//")[1]
    payload = hashlib.sha256(b"").hexdigest()
    canonical = f"{method}\n{path}\n\nhost:{host}\nx-amz-content-sha256:{payload}\nx-amz-date:{amz_date}\n\nhost;x-amz-content-sha256;x-amz-date\n{payload}"
    scope = f"{day}/{region}/s3/aws4_request"
    to_sign = f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{hashlib.sha256(canonical.encode()).hexdigest()}"
    key = ("AWS4" + secret_key).encode()
    for part in (day, region, "s3", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    auth = f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature={signature}"
    code, _ = curl(endpoint + path, method=method,
                   headers=[f"Authorization: {auth}", f"x-amz-date: {amz_date}", f"x-amz-content-sha256: {payload}"])
    return code


TCP_OPEN = """
import json, socket, sys
d = json.load(sys.stdin)
socket.create_connection((d["ip"], d["port"]), timeout=5).close()
"""

NATS_LOGIN = """
import json, socket, sys
d = json.load(sys.stdin)
s = socket.create_connection((d["ip"], 4222), timeout=5)
s.recv(4096)  # INFO line
s.sendall(("CONNECT " + json.dumps({"user": "admin", "pass": d["password"], "verbose": False}) + "\\r\\nPING\\r\\n").encode())
print(s.recv(4096).decode().strip())
"""


# ---------- checks ----------

def check_swarm():
    _, out = on_leader(["sudo", "docker", "service", "ls", "--format", "{{.Name}} {{.Replicas}}"])
    for line in out.splitlines():
        name, replicas = (line.split() + ["?"])[:2]
        running, _, wanted = replicas.partition("/")
        check(f"swarm service {name} running ({replicas})", running == wanted)
    _, out = on_leader(["sudo", "docker", "node", "ls", "--format", "{{.Hostname}} {{.Status}}"])
    for node in inv["managers"]["hosts"] + inv["workers"]["hosts"]:
        check(f"swarm node {node} ready", f"{node} Ready" in out)
    # A swarm made before v1.0.1 keeps Docker's old range (shown as []), so only check newer ones.
    _, pool = on_leader(["sudo", "docker", "info", "--format", "{{.Swarm.Cluster.DefaultAddrPool}}"])
    if pool == "[]":
        print("SKIP  swarm networks use the 10.200.0.0/16 range  (swarm made before v1.0.1)")
    else:
        _, out = on_leader(["sudo", "docker", "network", "inspect", "public", "--format", "{{range .IPAM.Config}}{{.Subnet}}{{end}}"])
        check("swarm networks use the 10.200.0.0/16 range", out.startswith("10.200."), out)
    code, _ = curl(f"https://{REGISTRY}/v2/")
    check("registry refuses access without login", code == "401", code)
    for node in inv["managers"]["hosts"] + inv["workers"]["hosts"]:
        _, addr = on_leader(["sudo", "docker", "node", "inspect", node, "--format", "{{.Status.Addr}}"])
        check(f"swarm node {node} uses its ip {HOSTS[node]['node_ip']}", addr == HOSTS[node]["node_ip"], addr)
    # Networks made before the MTU setting have none (Docker then uses 1450), so only check newer ones.
    _, mtu = on_leader(["sudo", "docker", "network", "inspect", "public", "--format",
                        '{{index .Options "com.docker.network.driver.mtu"}}'])
    if mtu in ("", "<no value>"):
        print("SKIP  swarm network MTU is set  (network made before MTU was set)")
    else:
        # The biggest packet must fit through the servers' network: ping it with "do not split".
        for node in HOSTS:
            if node != LEADER:
                code, out = on_leader(["ping", "-c", "1", "-W", "2", "-M", "do", "-s", str(int(mtu) + 50 - 28),
                                       HOSTS[node]["node_ip"]])
                check(f"packets of {int(mtu) + 50} bytes reach {node} (swarm MTU {mtu})", code == 0, out[-200:])


def check_k3s():
    _, out = on_leader(["sudo", "k3s", "kubectl", "get", "nodes", "--no-headers"])
    status = {line.split()[0]: line.split()[1] for line in out.splitlines() if line.strip()}
    for node in inv["managers"]["hosts"] + inv["workers"]["hosts"]:
        check(f"k3s node {node} ready", status.get(node, "").split(",")[0] == "Ready", status.get(node, "missing"))
    _, out = on_leader(["sudo", "k3s", "kubectl", "get", "pods", "-A", "--no-headers",
                        "--field-selector=status.phase!=Running,status.phase!=Succeeded"])
    check("no stuck k3s pods", not out.strip() or "No resources" in out, out[-300:])
    code, _ = curl(f"https://{REGISTRY}/v2/")
    check("registry refuses access without login", code == "401", code)
    # k3s pulls from the cluster's own registry (registries.yaml): pull an image that is in it.
    _, body = curl(f"https://{REGISTRY}/v2/_catalog", user="ansibro:" + secret("registry"))
    repos = [r for r in json.loads(body or "{}").get("repositories", []) if r in IMAGES]
    if repos:
        image = f"registry.ansibro:{CFG['registry_port']}/{repos[0]}:{IMAGES[repos[0]]['tag']}"
        code, out = on_leader(["sudo", "k3s", "crictl", "pull", image])
        check(f"k3s pulls {repos[0]} from the cluster's registry", code == 0, out[-200:])
    # Servers know the agent token (a file, not the link to the server token that k3s makes without it).
    # Workers have only the agent token: the server token would give them the cluster's keys.
    for node in inv["managers"]["hosts"]:
        code, _ = on_node(node, ["sudo", "test", "!", "-L", "/var/lib/rancher/k3s/server/agent-token"])
        check(f"k3s server {node} has its own agent token", code == 0)
    for node in inv["workers"]["hosts"]:
        # grep reads the token from stdin, so it is not on a command line. Exit code 1: not found.
        code, _ = on_node(node, ["sudo", "grep", "-qFf", "/dev/stdin", "/etc/rancher/k3s/config.yaml"],
                          stdin=secret("k3s_token") + "\n")
        check(f"k3s worker {node} does not have the server token", code == 1, f"grep exit code {code}")


def check_backup():
    """Every server has a backup in the repository, and the nightly timer is on."""
    # A folder repository (/mnt/...) is on each server; S3 and rest-server hold all of them.
    folder = str(CFG["backup"]["repository"]).startswith("/")
    for node in HOSTS if folder else [LEADER]:
        code, out = on_node(node, ["sudo", "ansibro-backup", "snapshots", "--json"])
        hosts = {s["hostname"] for s in json.loads(out)} if code == 0 else set()
        for host in [node] if folder else HOSTS:
            check(f"backup of {host} in the repository", host in hosts, out[-200:] if code else "no backup")
    code, out = on_leader(["systemctl", "is-active", "ansibro-backup.timer"])
    check("nightly backup timer is on", out == "active", out)


def check_wireguard():
    """Every other server has made a WireGuard handshake with the first manager in the last 3 minutes."""
    _, out = on_leader(["sudo", "wg", "show", "wg0", "latest-handshakes"])
    _, now = on_leader(["date", "+%s"])
    handshakes = dict(line.split() for line in out.splitlines())
    for node in HOSTS:
        if node == LEADER:
            continue
        # Peers are listed by public key; find the one for this node through its allowed IP.
        _, peers = on_leader(["sudo", "wg", "show", "wg0", "allowed-ips"])
        key = next((line.split()[0] for line in peers.splitlines() if f"{HOSTS[node]['node_ip']}/32" in line), None)
        age = int(now) - int(handshakes.get(key, 0))
        check(f"wireguard link to {node}", age < 180, f"last handshake {age}s ago" if key else "no peer")


def check_hardening():
    """On every server: SSH takes no passwords, fail2ban guards SSH, security updates are on."""
    for node in HOSTS:
        _, sshd = on_node(node, ["sudo", "sshd", "-T"])
        check(f"{node}: SSH without passwords", "passwordauthentication no" in sshd.splitlines())
        _, jail = on_node(node, ["sudo", "fail2ban-client", "status", "sshd"])
        check(f"{node}: fail2ban guards SSH", "Currently banned" in jail, jail[:200])
        _, auto = on_node(node, ["apt-config", "dump", "APT::Periodic::Unattended-Upgrade"])
        check(f"{node}: security updates on", '"1"' in auto, auto)


def check_traefik():
    code, _ = curl(f"http://traefik.{DOMAIN}/", resolve=f"traefik.{DOMAIN}:80:{WEB_IP}")
    check("traefik redirects HTTP to HTTPS", code in ("301", "308"), code)
    admin_login("traefik dashboard", "traefik", "/dashboard/")


def check_portainer():
    code, body = https("portainer", "/api/auth", data=json.dumps({"username": "admin", "password": secret("portainer_admin")}))
    check("portainer admin login", code == "200" and "jwt" in body, code)


def check_swarmpit():
    check("swarmpit page", https("swarmpit")[0] == "200")
    code, body = https("swarmpit", "/login", user="admin:" + secret("swarmpit_admin"), method="POST")
    check("swarmpit admin login (made by the installer)", code == "200" and "token" in body, code)


def check_kong():
    code, body = https("kong")
    check("kong proxy answers", code == "404" and "no Route matched" in body, code)
    admin_login("kong manager", "kong-manager")
    result = admin_login("kong admin API", "kong-manager", "/api/")
    if result:
        check("kong admin API works", "version" in result[1])
    # From where other apps are, the admin API must not be reachable.
    curl_cmd = ["curl", "-s", "-m", "5", "-o", "/dev/null", "-w", "%{http_code}"]
    if CFG.get("orchestrator") == "k3s":
        _, out = on_leader(["sudo", "k3s", "kubectl", "run", "ansibro-check-kong", "-n", "default", "--rm", "-i",
                            "--restart=Never", f"--image=registry.ansibro:{CFG['registry_port']}/kong:{IMAGES['kong']['tag']}",
                            "--command", "--", *curl_cmd, "http://kong.ansibro.svc.cluster.local:8001/"])
    else:
        _, out = on_leader(["sudo", "docker", "run", "--rm", "--network", "public", f"{REGISTRY}/kong:{IMAGES['kong']['tag']}",
                            *curl_cmd, "http://kong_kong:8001/"])
    check("kong admin API is not reachable from other apps", "200" not in out, out[-80:])


def check_keycloak():
    form = f"grant_type=password&client_id=admin-cli&username=admin&password={secret('keycloak_admin')}"
    code, body = https("keycloak", "/realms/master/protocol/openid-connect/token", data=form)
    check("keycloak admin login", code == "200" and "access_token" in body, code)
    if "authelia" not in APPS:
        check("keycloak has the ansibro realm for admin pages", https("keycloak", "/realms/ansibro")[0] == "200")


def check_authelia():
    hdr = ["Content-Type: application/json"]
    code, body = https("authelia", "/api/firstfactor", data=json.dumps({"username": "admin", "password": secret("authelia_admin")}), headers=hdr)
    check("authelia login with the right password", '"OK"' in body, code)
    _, body = https("authelia", "/api/firstfactor", data=json.dumps({"username": "admin", "password": "wrong"}), headers=hdr)
    check("authelia refuses a wrong password", '"KO"' in body)


def check_postgres():
    _, out = client(PG_IMAGE, "psql", "-h", ip_of("postgres"), "-U", "postgres", "-tAc", "select 1", env=[f"PGPASSWORD={secret('postgres')}"])
    check("postgres login", out.strip() == "1", out[-200:])
    for app in ("kong", "keycloak", "authelia"):
        if app in APPS:
            _, out = client(PG_IMAGE, "psql", "-h", ip_of("postgres"), "-U", app, "-tAc", "select 1",
                            env=[f"PGPASSWORD={secret(app + '_db')}"])
            check(f"postgres database for {app}", out.strip() == "1", out[-200:])


def check_postgres_replicas():
    """Patroni: one primary, and a row written there shows up on every replica."""
    nodes = CFG["app_nodes"]["postgres"]
    primary = [n for n in nodes if curl(f"http://{HOSTS[n]['node_ip']}:8008/primary")[0] == "200"]
    check("postgres has exactly one primary (Patroni)", len(primary) == 1, str(primary))
    if len(primary) != 1:
        return
    stamp = str(int(time.time()))
    env = [f"PGPASSWORD={secret('postgres')}"]
    client(PG_IMAGE, "psql", "-h", HOSTS[primary[0]]["node_ip"], "-U", "postgres", "-tAc",
           f"CREATE TABLE IF NOT EXISTS ansibro_check (v text); INSERT INTO ansibro_check VALUES ('{stamp}')", env=env)
    for node in nodes:
        if node == primary[0]:
            continue
        ip = HOSTS[node]["node_ip"]
        _, out = client(PG_IMAGE, "psql", "-h", ip, "-U", "postgres", "-tAc", "SELECT pg_is_in_recovery()", env=env)
        check(f"postgres on {node} is a replica", out.strip() == "t", out[-200:])
        for _ in range(10):
            _, out = client(PG_IMAGE, "psql", "-h", ip, "-U", "postgres", "-tAc",
                            f"SELECT count(*) FROM ansibro_check WHERE v = '{stamp}'", env=env)
            if out.strip() == "1":
                break
            time.sleep(2)
        check(f"postgres replica on {node} has the new row", out.strip() == "1", out[-200:])


def check_openbao():
    base = f"http://{ip_of('openbao')}:8200"
    code, body = curl(base + "/v1/sys/seal-status")
    check("openbao is unsealed", code == "200" and '"sealed":false' in body.replace(" ", ""), body[-200:])
    token = "X-Vault-Token: " + secret("openbao_root_token")
    code, _ = curl(base + "/v1/secret/data/ansibro-check", data='{"data": {"hello": "world"}}', headers=[token])
    check("openbao saves a secret", code in ("200", "204"), code)
    code, body = curl(base + "/v1/secret/data/ansibro-check", headers=[token])
    check("openbao reads the secret back", code == "200" and "world" in body, body[-200:])
    code, _ = curl(base + "/v1/secret/data/ansibro-check")
    check("openbao refuses without a token", code in ("400", "401", "403"), code)
    if WEB:
        check("openbao web page", https("openbao", "/ui/")[0] in ("200", "307"))


def check_mariadb():
    _, out = client("mariadb", "mariadb", "-h", ip_of("mariadb"), "-uroot", "-N", "-e", "select 1", env=[f"MYSQL_PWD={secret('mariadb')}"])
    check("mariadb login", out.strip() == "1", out[-200:])
    for app in ("keycloak", "authelia"):
        if app in APPS:
            _, out = client("mariadb", "mariadb", "-h", ip_of("mariadb"), f"-u{app}", "-N", "-e", "select 1",
                            env=[f"MYSQL_PWD={secret(app + '_db')}"])
            check(f"mariadb database for {app}", out.strip() == "1", out[-200:])


def check_cache_replicas(app):
    """3 cache servers: one primary, copies get its data, and Sentinel knows the primary."""
    cli = "redis-cli" if app == "redis" else "valkey-cli"
    env = [f"REDISCLI_AUTH={secret(app)}"]
    nodes = CFG["app_nodes"][app]
    roles = {}
    for node in nodes:
        _, out = client(app, cli, "-h", HOSTS[node]["node_ip"], "INFO", "replication", env=env)
        roles[node] = "master" if "role:master" in out else "replica" if "role:slave" in out else "?"
    primary = [n for n, r in roles.items() if r == "master"]
    check(f"{app} has exactly one primary", len(primary) == 1, str(roles))
    if len(primary) != 1:
        return
    _, out = client(app, cli, "-h", HOSTS[nodes[0]]["node_ip"], "-p", "26379", "SENTINEL", "get-master-addr-by-name", "ansibro", env=env)
    check(f"{app} Sentinel knows the primary", HOSTS[primary[0]]["node_ip"] in out, out[-120:])
    stamp = str(int(time.time()))
    client(app, cli, "-h", HOSTS[primary[0]]["node_ip"], "SET", "ansibro-check", stamp, env=env)
    for node in nodes:
        if node != primary[0]:
            time.sleep(1)
            _, out = client(app, cli, "-h", HOSTS[node]["node_ip"], "GET", "ansibro-check", env=env)
            check(f"{app} copy on {node} has the new value", stamp in out, out[-80:])


def check_galera():
    """3 MariaDB servers: one Galera cluster, every server synced, and data written on one is on all."""
    env = [f"MYSQL_PWD={secret('mariadb')}"]
    nodes = CFG["app_nodes"]["mariadb"]
    stamp = str(int(time.time()))
    client("mariadb", "mariadb", "-h", HOSTS[nodes[0]]["node_ip"], "-uroot", "-e",
           f"CREATE DATABASE IF NOT EXISTS ansibro_check; CREATE TABLE IF NOT EXISTS ansibro_check.t (v varchar(20) PRIMARY KEY); "
           f"INSERT INTO ansibro_check.t VALUES ('{stamp}')", env=env)
    for node in nodes:
        ip = HOSTS[node]["node_ip"]
        _, out = client("mariadb", "mariadb", "-h", ip, "-uroot", "-N", "-e",
                        "SHOW STATUS WHERE Variable_name IN ('wsrep_cluster_size', 'wsrep_local_state_comment')", env=env)
        check(f"mariadb on {node} is synced in a cluster of {len(nodes)}", f"wsrep_cluster_size\t{len(nodes)}" in out and "Synced" in out, out[-160:])
        _, out = client("mariadb", "mariadb", "-h", ip, "-uroot", "-N", "-e", f"SELECT count(*) FROM ansibro_check.t WHERE v = '{stamp}'", env=env)
        check(f"mariadb on {node} has the new row", out.strip() == "1", out[-120:])
        code, _ = curl(f"http://{ip}:9200/")  # mariadb_check_port in group_vars/all.yml
        check(f"mariadb on {node}: the check for database-proxy says synced", code == "200", code)


def check_cache(app):
    cli = "redis-cli" if app == "redis" else "valkey-cli"
    _, out = client(app, cli, "-h", ip_of(app), "ping", env=[f"REDISCLI_AUTH={secret(app)}"])
    check(f"{app} login", "PONG" in out, out[-200:])
    _, out = client(app, cli, "-h", ip_of(app), "ping", env=["REDISCLI_AUTH=wrong"])
    check(f"{app} refuses a wrong password", "PONG" not in out)


def check_rustfs():
    status = s3_list_buckets(f"http://{ip_of('rustfs')}:9000", secret("rustfs_access_key"), secret("rustfs_secret_key"), "us-east-1")
    check("rustfs S3 login with the keys", status == "200", status)
    if WEB:
        check("rustfs console", https("rustfs", "/rustfs/console/index.html")[0] == "200")


def check_garage():
    endpoint, keys = f"http://{ip_of('garage')}:3900", ("GK" + secret("garage_access_key"), secret("garage_secret_key"))
    status = s3_list_buckets(endpoint, *keys, "garage")
    check("garage S3 login with the keys", status == "200", status)
    bucket = f"/ansibro-check-{int(time.time())}"
    status = s3_list_buckets(endpoint, *keys, "garage", method="PUT", path=bucket)
    check("garage key can make a bucket", status == "200", status)
    s3_list_buckets(endpoint, *keys, "garage", method="DELETE", path=bucket)


def check_rabbitmq():
    code, out = python_on_leader(TCP_OPEN, {"ip": ip_of("rabbitmq"), "port": 5672})
    check("rabbitmq AMQP port open", code == 0, out[-200:])
    if WEB:
        code, body = https("rabbitmq", "/api/overview", user="admin:" + secret("rabbitmq"))
        check("rabbitmq UI login", code == "200" and "rabbitmq_version" in body, code)


def check_nats():
    _, out = python_on_leader(NATS_LOGIN, {"ip": ip_of("nats"), "password": secret("nats")})
    check("nats login", out.startswith("PONG"), out[-200:])
    if WEB:
        admin_login("nats monitoring", "nats", "/varz")


def check_uptimekuma():
    check("uptime kuma page", https("uptimekuma")[0] in ("200", "302"))
    # /metrics needs the admin login, and lists every monitor with its state (1 = up).
    code, body = curl(f"http://{ip_of('uptimekuma')}:3001/metrics", user="admin:" + secret("uptimekuma_admin"))
    check("uptime kuma admin login (made by the installer)", code == "200", code)
    monitors = [line for line in body.splitlines() if line.startswith("monitor_status{")]
    check(f"uptime kuma has its monitors ({len(monitors)})", len(monitors) >= 2, str(len(monitors)))
    down = [line.split('monitor_name="')[1].split('"')[0] for line in monitors if not line.endswith(" 1")]
    # The monitor of a removed app stays (after the first install the monitors are yours): skip it.
    # Monitor names come from roles/uptimekuma (monitors.json.j2): "<page host> web page".
    with open(os.path.join(HERE, "roles", "uptimekuma", "defaults", "main.yml")) as f:
        pages = yaml.safe_load(f)["uptimekuma_pages"]
    removed = [f"{page['host']} web page" for app, page in pages.items() if app not in APPS]
    if not any(app in APPS for app in inventory.MONITORING_APPS):
        removed.append("Monitoring server (its Watchdog alert)")
    down = [name for name in down if name not in removed]
    if monitors:
        check("uptime kuma monitors are up", not down, ", ".join(down))


def check_beszel():
    url = f"http://{ip_of('beszel')}:8090"
    code, body = curl(url + "/api/collections/users/auth-with-password",
                      data=json.dumps({"identity": f"admin@{DOMAIN}", "password": secret("beszel_admin")}),
                      headers=["Content-Type: application/json"])
    check("beszel admin login", code == "200", code)
    if code != "200":
        return
    token = json.loads(body)["token"]
    _, body = curl(url + "/api/collections/systems/records?perPage=500", headers=[f"Authorization: {token}"])
    systems = {s["name"]: s["status"] for s in json.loads(body)["items"]}
    for host in HOSTS:
        check(f"beszel sees {host} up", systems.get(host) == "up", systems.get(host, "missing"))
    check("beszel page", https("beszel")[0] == "200")


def check_monitoring(app):
    ip = ip_of(app)
    metrics = f"http://{ip}:8428"
    alertmanager = "ansibro:" + secret("alertmanager")
    code, _ = curl(f"http://{ip}:3000/api/user", user="admin:" + secret("grafana_admin"))
    check("grafana admin login", code == "200", code)
    check("grafana page", https("grafana", path="/login")[0] == "200")
    admin_login("alertmanager", "alertmanager", "/-/healthy")

    # Every target answers: servers, containers, log agents, exporters, Traefik, the monitoring apps.
    _, body = curl(metrics + "/api/v1/query?query=up")
    up = json.loads(body)["data"]["result"]
    down = [f"{r['metric'].get('job')}@{r['metric'].get('node')}" for r in up if r["value"][1] != "1"]
    check(f"all {len(up)} metric targets answer", up and not down, ", ".join(down))
    for host in HOSTS:
        check(f"metrics script runs on {host}",
              any(r["metric"].get("node") == host and r["metric"].get("job") == "node" for r in up))
    _, body = curl(metrics + "/api/v1/query?query=ansibro_app_up")
    apps = {r["metric"]["app"]: r["value"][1] for r in json.loads(body)["data"]["result"]}
    check(f"every server app answers ({len(apps)})", apps and all(v == "1" for v in apps.values()), str(apps))

    # The alert rules are loaded and Watchdog fires: alerts reach Alertmanager.
    _, body = curl(f"http://{ip}:8880/api/v1/rules")
    rules = sum(len(g["rules"]) for g in json.loads(body)["data"]["groups"])
    check(f"alert rules loaded ({rules})", rules >= 30, str(rules))
    _, body = curl(f"http://{ip}:9093/api/v2/alerts", user=alertmanager)
    names = {a["labels"]["alertname"] for a in json.loads(body)}
    check("watchdog alert reaches alertmanager", "Watchdog" in names, str(names))
    real = names - {"Watchdog"}
    check("no other alerts firing", not real, ", ".join(sorted(real)))

    # Without the login or the admin key, nobody can mute alerts or delete data. (If a check fails,
    # the request did nothing harmful: the names match nothing.)
    code, _ = curl(f"http://{ip}:9093/api/v2/silences")
    check("alertmanager refuses requests without its login", code == "401", code)
    code, _ = curl(metrics + "/api/v1/admin/tsdb/delete_series?match%5B%5D=ansibro_check_none", method="POST")
    check("victoriametrics refuses to delete without the admin key", code in ("401", "403"), code)
    code, _ = curl(f"http://{ip}:9428/internal/force_merge?partition_prefix=19700101")
    check("victorialogs refuses admin requests without the admin key", code in ("401", "403"), code)

    # Logs arrive from every server.
    _, body = curl(f"http://{ip}:9428/select/logsql/field_values?query=_time:15m&field=node")
    nodes = {v["value"] for v in json.loads(body).get("values", [])}
    for host in HOSTS:
        check(f"logs arrive from {host}", host in nodes, str(sorted(nodes)))


CHECKS = {
    "traefik": check_traefik, "kong": check_kong, "portainer": check_portainer, "swarmpit": check_swarmpit,
    "keycloak": check_keycloak, "authelia": check_authelia, "postgres": check_postgres, "mariadb": check_mariadb,
    "openbao": check_openbao,
    "redis": lambda: check_cache("redis"), "valkey": lambda: check_cache("valkey"),
    "rustfs": check_rustfs, "garage": check_garage, "rabbitmq": check_rabbitmq, "nats": check_nats,
    "uptimekuma": check_uptimekuma, "beszel": check_beszel,
    "victoria": lambda: check_monitoring("victoria"),
}

if __name__ == "__main__":
    print(f"Checking {', '.join(APPS)} on {DOMAIN} (from {'the first manager' if ON_LEADER else 'here, over SSH'})\n")
    todo = [("k3s", check_k3s) if CFG.get("orchestrator") == "k3s" else ("swarm", check_swarm)]
    todo.append(("hardening", check_hardening))
    if CFG.get("wireguard"):
        todo.append(("wireguard", check_wireguard))
    if CFG.get("backup"):
        todo.append(("backup", check_backup))
    if len(CFG["app_nodes"].get("postgres", [])) > 1:
        todo.append(("postgres replicas", check_postgres_replicas))
    if len(CFG["app_nodes"].get("mariadb", [])) > 1:
        todo.append(("galera", check_galera))
    for cache in ("redis", "valkey"):
        if len(CFG["app_nodes"].get(cache, [])) > 1:
            todo.append((f"{cache} replicas", lambda cache=cache: check_cache_replicas(cache)))
    todo += [(app, CHECKS[app]) for app in APPS]
    for name, run in todo:
        try:
            run()
        except Exception as e:  # a crash in one check must not hide the others
            check(f"{name} check ran", False, repr(e))
    failed = [name for name, ok in results if not ok]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)
