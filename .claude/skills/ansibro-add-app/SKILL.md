---
name: ansibro-add-app
description: Add a new app to the Ansibro catalog (a new role, catalog entry and pinned image). Use when someone wants Ansibro to support a new tool, like a database, gateway, queue or monitoring app.
---

# Add an app to Ansibro

## Rules (check these first)

- **Open source only.** The license must be OSI-approved. If it is not (for example BSL or SSPL), stop and tell the user.
- **Pinned version.** Tag + the digest of its image index, with an amd64 build. Never `latest`.
- **Works offline.** Images come from `versions.yml`, so the bundle and the local registry pick them up. Don't download anything else at install time.
- **Apps with data** (databases, caches, storage, queues, monitoring) use `runs_on: node` and Docker Compose.
  A swarm app that must keep data is pinned to the first manager (see `roles/portainer/`).
- **Keep it simple.** A beginner must be able to read every file. Simple English in comments.
- Each category has two choices at most. The popular one comes first.

## Steps

1. **catalog.yml**: add the app next to the other app of its category. (The installer deploys
   all server apps first, then all swarm apps, so a swarm app can use a server app's database.)

   ```yaml
   myapp:
     category: cache
     runs_on: node            # or swarm
     requires: [traefik]      # needed if it has a web page; can also name a category, e.g. database
     license: MIT
     info: "<ip>:1234 (password state/secrets/myapp)"
   ```

2. **versions.yml**: add the image under `images:`. Get the digest of its image index:

   ```bash
   docker buildx imagetools inspect docker.io/org/myapp:1.2.3
   ```

   Use the top `Digest:` (the index), not one of the per-platform digests. Check that `linux/amd64` is listed.

3. **roles/myapp/**: copy the closest role and rename things.
   - Server app: copy `roles/valkey/` (simple) or `roles/postgres/` (has a database).
   - Server app with a web page: copy `roles/uptimekuma/` (uses `traefik` `tasks_from: route`).
   - Swarm app: copy `roles/portainer/` (stack file + `swarm` `tasks_from: deploy`).
   - Pull the image with the `registry` role `tasks_from: mirror`. In templates use `{{ registry_addr }}/myapp:{{ images.myapp.tag }}`.
   - Passwords: `lookup('ansible.builtin.password', secrets_dir ~ '/myapp', ...)` in `defaults/main.yml`.
   - Server apps: use `network_mode: host`, **never `ports:`**. Published ports skip the firewall.
   - Add `diff: false` or `no_log: true` to tasks that write passwords.

4. **k3s** (swarm apps only): a swarm app must also work with `orchestrator: k3s`.
   - Write the stack only `when: orchestrator == 'swarm'`.
   - Add `templates/k3s.yaml.j2` and write it to `/var/lib/rancher/k3s/server/manifests/ansibro-myapp.yaml`
     `when: orchestrator == 'k3s'` (k3s applies it by itself). Copy both from `roles/portainer/`.
   - Add the app to `K3S_CLUSTER_APPS` in `inventory.py`. If it only works with Docker Swarm
     (like swarmpit), leave it out: the config check then stops it on k3s.

5. **Lists of apps in other roles** (add your app to each one that fits):
   - Server app: its ports in `common_app_ports` (`roles/common/defaults/main.yml`), so the other
     servers may reach them (all other ports stay closed), and its main port in `observability_app_ports`
     (`roles/observability/defaults/main.yml`), so monitoring checks that it answers.
   - Web page: its subdomain and path in `uptimekuma_pages` (`roles/uptimekuma/defaults/main.yml`),
     so Uptime Kuma gets a monitor for it.
   - Admin page: add it to `authelia_admin_hosts` (`roles/authelia/defaults/main.yml`, they need two
     factors) if it uses the `admin` login, and to the page list in the `admin_allow_from` comment in
     `config.example.yml`.

6. **Docs and tests**:
   - `README.md`: add a row to the Apps table.
   - `docs/apps.md`: add notes if the app has a special login or needs something.
   - `THIRD_PARTY.md`: add name, license and source link.
   - `config.example.yml`: mention it as a comment next to the other app in its category.
   - `tests/check.py`: add a `check_myapp()` that logs in to it for real, and add it to `CHECKS`.
   - `CHANGELOG.md`: one line about the new app.

## Check

No servers needed. The first line makes `.venv/` with Ansible:

```bash
./install.sh config.example.yml --syntax-check
.venv/bin/pip install ansible-lint==26.10.1
.venv/bin/python tests/test_config.py
.venv/bin/python tests/test_handover.py    # state/handover.json has no password
ANSIBRO_CONFIG=config.example.yml PATH="$PWD/.venv/bin:$PATH" ansible-lint --profile production
shellcheck install.sh build-bundle.sh scripts/*.sh
scripts/validate-versions.sh               # needs yq, docker and curl
```

Then test on new DigitalOcean droplets (tag them `ansibro-test`), never on local VMs or containers:
run `./install.sh` two times. The second run must show `changed=0`.
Then run `.venv/bin/python tests/check.py` where you ran `./install.sh`: every check must PASS.
Delete every droplet (and anything else you made) after the test.
