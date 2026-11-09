# Check and fix

Check that every app works, and what to do when something goes wrong.

## Check that everything works

After an install, check every app for real (logins, databases, S3 keys, web pages).
Run it on the computer where you ran `./install.sh`, in the same folder:

```bash
.venv/bin/python tests/check.py          # or: .venv/bin/python tests/check.py other.yml
```

It prints PASS or FAIL for each check. The checks run on the first manager
(over SSH if you are on another machine), because the firewall only lets cluster servers reach the apps.

## Troubleshooting

Commands that start with `sudo` run on a server: log in first with `ssh <user>@<server IP>`.

| Problem | Try |
|---------|-----|
| `UNREACHABLE` or `Permission denied (publickey)` | The installer cannot log in. Try it yourself: `ssh <user>@<host>`. Check `ssh.user`, `ssh.key` and each node's `host` in `config.yml`. Port 22 must be open in your cloud firewall. |
| `Missing sudo password` | The user must use `sudo` without a password. Use `root`, or the user your cloud made (often `ubuntu`). |
| `command not found: python3` or `Python 3.12, 3.13 or 3.14 is needed` | Install Python: `brew install python@3.13` on a Mac ([brew.sh](https://brew.sh) if you have no `brew`; with `brew`, uv or mise the installer does this itself), `sudo apt install python3 python3-venv` on Ubuntu. |
| `config error: ...` | The message says what to fix in `config.yml`. |
| Locked out of SSH | Check `ssh.allow_from`. Use your provider's console to run `sudo ufw disable`. Too many failed logins block your IP for 10 minutes (fail2ban): wait, or run `sudo fail2ban-client unban <your IP>`. Passwords do not work for SSH: use your key. |
| `cannot reach ... over WireGuard` | Open UDP 51820 between the servers' `host` addresses in your cloud firewall. `sudo wg show` shows the last handshake. |
| `docker push` to the registry says `405 Method Not Allowed` | The registry is read-only. Run `sudo ansibro-registry open` on the manager first (see [How to](how-to.md#your-own-images)). |
| The install stops: "The registry has another image than the one the installer pushed" | Someone with the registry password pushed an image under an ansibro image's name and tag. The apps still run the right image (by digest). Find out who (the registry's log: `sudo docker logs registry-registry-1`), then `./install.sh -e registry_repush=true` pushes the right images again. |
| The install stops: "etcd's login could not be turned on" | A Patroni could not log in to etcd. The login is off again and PostgreSQL runs as before. Read `sudo docker logs postgres` on the PostgreSQL servers, fix it, and run `./install.sh` again. |
| No HTTPS certificate | DNS must point to the server Traefik runs on (`state/summary.md`, section DNS, names it; with `tls: letsencrypt` on Docker Swarm the first manager, on k3s the first worker), and port 80 must be open there. Then restart Traefik on the first manager. Docker Swarm: `sudo docker service update --force traefik_traefik`. k3s: `sudo k3s kubectl -n kube-system rollout restart deployment traefik`. Let's Encrypt has rate limits. |
| App not starting | Swarm apps: `sudo docker service ls`, `sudo docker service logs <stack>_<service>`. Server apps: `sudo docker ps`, `sudo docker logs <app>`. |
| `no such host` or a timeout while downloading | A network problem on the server. Check its internet, then run `./install.sh` again. It is safe to run again: it continues where it stopped. |
| No alerts arrive | Look at `https://alertmanager.<domain>`: if alerts are there, check `monitoring:` in `config.yml` and the `AlertsNotSent` alert. Logs: `sudo docker logs alertmanager` on the monitoring server. |
| An alert you do not want | Silence it in `https://alertmanager.<domain>` (for a time), or change the rule in `roles/observability/files/alerts.yml`. |
| `401 Unauthorized` from Alertmanager (port 9093) | It needs its login: user `ansibro`, password in `state/secrets/alertmanager` (`curl -u ansibro:<password> ...`). |
| A script or CLI that calls Portainer, Grafana, OpenBao, ... by its web address stopped working | With Authelia or Keycloak installed, these pages ask for that login first. Use the app's port on its server's `ip` (OpenBao: `http://<ip>:8200`) from a server, or an SSH tunnel from your laptop. See [Apps](apps.md#with-authelia-or-keycloak-every-admin-page-asks-for-that-login). |
| `warning: admin_allow_from is empty` | The admin pages are open to the whole internet. Set `admin_allow_from` in `config.yml` to the IPs you work from, then run `./install.sh` again. |
| `toomanyrequests` from Docker Hub | Docker Hub limits pulls. Wait, or run `sudo docker login` on the first manager. |
| Another error, in red, with `FAILED` | Run `./install.sh` again: it is safe, and some errors go away (a slow download, for example). Still failing? Open a [bug report](https://github.com/sgnd/ansibro/issues/new?template=bug-report.yml) with the red lines. |
