---
name: ansibro-install
description: Run the Ansibro installer, online or offline (bundle), and fix common problems. Use when someone wants to install, re-run, build an offline bundle, or debug a failed install.
---

# Install Ansibro

The installer changes real servers. **Ask the user before you run `./install.sh`.**

## Before you start

- `config.yml` exists and is valid. If not, use the `ansibro-setup` skill first.
- Servers run Ubuntu 24.04 or 26.04 on Intel/AMD (amd64), with SSH key login and passwordless sudo.
- The machine that runs the installer has Python 3.12 to 3.14 (on a Mac `./install.sh` finds or installs one) and can reach every server over SSH (at its `host`, or its `ip` if `host` is not set).
- Always run it from the same machine, because the `state/` folder holds all passwords.

## Online (servers have internet)

```bash
./install.sh                 # uses config.yml
./install.sh other.yml       # another config file
```

You can run it again any time. It only changes what is different in `config.yml`.

## Offline (no internet on the servers)

1. On a machine with internet and Docker (a Mac works too), build the bundle for the **servers'** Ubuntu version:

   ```bash
   ./build-bundle.sh          # Ubuntu 24.04
   ./build-bundle.sh 26.04    # Ubuntu 26.04
   ```

   This makes `dist/ansibro-<ubuntu>.tar.gz` (about 4 GB).
2. Copy it **and the SSH private key** to the **first manager** (plus any `tls_cert`, `tls_key` or
   `acme_ca_cert` files: the bundle leaves out keys and certificates). The key must be allowed on
   every server, the first manager itself too. Unpack, add `config.yml` with `tls: selfsigned`
   (or `custom`, or `acme_server`) and `ssh.key` pointing at the key, then run `./install.sh` there.

The installer sees the `bundle/` folder and uses it instead of the internet.

## After the install

- Run `.venv/bin/python tests/check.py` where you ran `./install.sh`. Every check must PASS.
- Read `state/summary.md`. It lists every app's address and names the file of each password in
  `state/secrets/` (`state/` is encrypted: `scripts/state.sh open` first). Don't paste the passwords into chat.
- Tell the user to **back up `state/`**. If it is lost, the next run makes new passwords that don't match the running databases.
- DNS for `*.<domain>` must point to the public IP of the servers Traefik runs on. The end of the install
  and `state/summary.md` (section DNS) name them. Swarm: the first manager with Let's Encrypt, else every manager.
  k3s: the workers (with Let's Encrypt the first one only); no workers: the managers.
  With Let's Encrypt, set DNS before the install. If it came later: Swarm, run
  `sudo docker service update --force traefik_traefik` on the first manager; k3s, run
  `sudo k3s kubectl -n kube-system rollout restart deployment traefik` on the first manager.
- Swarmpit and Uptime Kuma: the installer makes the admin user. The passwords are in
  `state/secrets/swarmpit_admin` and `state/secrets/uptimekuma_admin` (and in `state/summary.md`).

## When it fails

| Problem | Try |
|---------|-----|
| `config error: ...` | Fix `config.yml` as the message says. |
| Wrong CPU or Ubuntu version | Servers must be Intel/AMD (amd64); ARM is not supported. Offline: the bundle has one Ubuntu version; build one that matches. |
| Locked out of SSH | Check `ssh.allow_from`. Use the provider's console to run `sudo ufw disable`. |
| No HTTPS certificate | DNS must point to the server Traefik runs on (see `state/summary.md`), and port 80 must be open. Then restart Traefik (see After the install). Let's Encrypt has rate limits. |
| Swarm app not starting | `sudo docker service ls`, `sudo docker service logs <stack>_<service>` on a manager. |
| Server app not starting | `sudo docker ps`, `sudo docker logs <app>` on that server. |
| `toomanyrequests` | Docker Hub limit. Wait, or run `sudo docker login` on the first manager. |
| `cannot reach ... over WireGuard` | Open UDP 51820 between the servers' `host` addresses in the cloud firewall (security group). Check each `host`. `sudo wg show` on a server shows the last handshake. |
| Backup fails | `sudo ansibro-backup` on the server shows the error. Check `backup.repository` and the S3 keys. |
| No alerts arrive | Check `https://alertmanager.<domain>`, then `sudo docker logs alertmanager` on the monitoring server. Telegram `chat_id` must be a number; email `smarthost` is `host:port`. |
| `TargetDown` alert after the install | An agent or exporter does not answer. `sudo docker ps` on that server; the firewall must allow the monitoring server (it does for cluster servers). |
| `restore=true is only for new, empty servers` | A restore replaces the swarm and data, so it only runs on new servers. |
| `is in the swarm with address ...` | A swarm server cannot change its address. Put the old address back as `ip`. If the server's real address changed, set it as `host`. |

Read the failed Ansible task name first. It usually says what went wrong.
