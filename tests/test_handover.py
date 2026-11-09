#!/usr/bin/env python3
"""Check that state/handover.json has the facts, and no password.

Run it from the project folder (CI runs it too):

    .venv/bin/python tests/test_handover.py

It writes templates/handover.json.j2 for config.example.yml, with fake passwords
in a temporary state/secrets/. No servers are needed.
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.dirname(sys.executable)  # .venv/bin, with Ansible and the Python that inventory.py needs
# Some of the files the installer makes. Each gets a fake password that must not show up.
SECRETS = ["traefik_admin", "postgres", "redis", "registry", "rustfs_access_key", "rustfs_secret_key", "restic",
           "k3s_agent_token", "alertmanager", "victoria_admin_key"]
FIELDS = {
    "ansibro_version", "domain", "orchestrator", "tls", "nodes", "apps", "traefik_nodes", "admin_sso",
    "database_app", "database_ha", "database_host", "database_port", "postgres_patroni", "mariadb_galera",
    "cache_app", "cache_ha", "monitoring_app", "swarm_app_constraint", "registry_addr", "secret_files",
}
# Runs only on this computer: the play is for the first manager, but the task is delegated to localhost.
PLAYBOOK = f"""
- name: Handover
  hosts: managers[0]
  gather_facts: false
  tasks:
    - name: Save facts to state/handover.json
      ansible.builtin.template:
        src: {HERE}/templates/handover.json.j2
        dest: "{{{{ playbook_dir }}}}/state/handover.json"
        mode: "0600"
      delegate_to: localhost
      become: false
"""

with tempfile.TemporaryDirectory() as tmp:
    # The playbook is in tmp, so secrets_dir (playbook_dir/state/secrets) is tmp/state/secrets.
    os.makedirs(os.path.join(tmp, "state", "secrets"))
    for name in SECRETS:
        with open(os.path.join(tmp, "state", "secrets", name), "w") as f:
            f.write(f"Fake{name.title().replace('_', '')}Pw9")
    with open(os.path.join(tmp, "handover.yml"), "w") as f:
        f.write(PLAYBOOK)
    p = subprocess.run([os.path.join(BIN, "ansible-playbook"), os.path.join(tmp, "handover.yml")], capture_output=True, text=True,
                       cwd=HERE, env={**os.environ, "ANSIBRO_CONFIG": "config.example.yml",
                            "PATH": BIN + os.pathsep + os.environ["PATH"]})
    if p.returncode != 0:
        print(p.stdout + p.stderr)
        sys.exit("FAIL  could not write handover.json")
    text = open(os.path.join(tmp, "state", "handover.json")).read()

data = json.loads(text)
checks = [
    ("it has every field", FIELDS <= set(data), sorted(FIELDS - set(data))),
    ("it lists the secret file names", data["secret_files"] == sorted(SECRETS), data["secret_files"]),
    ("it has no password", not [n for n in SECRETS if f"Fake{n.title().replace('_', '')}Pw9" in text], ""),
    ("nodes have name, ip, host, role, tier and apps",
     all({"name", "ip", "host", "role", "tier", "apps"} <= set(n) for n in data["nodes"]), data["nodes"][:1]),
    ("apps have their nodes", data["apps"].get("postgres", {}).get("nodes") == ["data1"], data["apps"].get("postgres")),
]
failed = 0
for name, ok, got in checks:
    failed += not ok
    print(f"{'PASS' if ok else 'FAIL'}  handover.json: {name}" + ("" if ok else f"  (got: {got})"))
print(f"\n{len(checks) - failed} passed, {failed} failed")
sys.exit(1 if failed else 0)
