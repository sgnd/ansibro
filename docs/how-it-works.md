# How it works

What the installer does, step by step, and things good to know.

`install.sh` installs Ansible into `.venv/`, reads `config.yml` through
[`inventory.py`](../inventory.py) (which also checks it), and runs [`site.yml`](../site.yml):

1. **removed servers** leave the cluster (only with `-e remove_nodes=true`)
2. **bundle** (offline only): copies the bundle to the servers
3. **common**: hostname, packages, time sync, SSH hardening, firewall
4. **wireguard** (if `wireguard: true`): the encrypted network between the servers
5. **docker**: installs Docker
6. **registry**: a private image registry on every manager, with the same images. All servers pull from it.
7. **swarm** or **k3s**: creates the cluster and joins the servers
8. **server apps**: `roles/<app>/`, Docker Compose in `/opt/ansibro/<app>/`
9. **agents** on every server, for the monitoring app: victoria or beszel
10. **swarm apps**: `roles/<app>/`, swarm stacks in `/opt/ansibro/<app>/` (k3s: its built-in Traefik)
11. **removed apps** stop, then **backup** (if `backup:` is set)

## Firewall

| Open | To |
|------|----|
| SSH | `ssh.allow_from` (or anyone), and always the other servers' `host` (the installer may run on the first manager) |
| 80, 443 | anyone, only on the servers Traefik runs on (see **Where Traefik runs** below) |
| the ports a server needs: swarm, registry, its apps, monitoring agents | other servers in `config.yml` (from their `ip`) |
| UDP 51820 | other servers' `host`, with `wireguard: true` |
| everything | containers on Docker networks of the same server, also your own Docker Compose networks (with k3s also its pods, `10.42.0.0/16`, on `cni0` and `flannel.1`) |
| your own ports | `firewall_allow` in `config.yml` (for example a VPN) |

Everything else is blocked. Server apps use the host network, so the firewall controls them.
Even between your servers only those ports are open (the list is `common_app_ports` in
`roles/common/defaults/main.yml`). An app of your own on a server's host network needs a `firewall_allow` rule.
Admin web pages can be limited to some IPs with `admin_allow_from` (the servers themselves are always
let in too: Uptime Kuma checks the pages from there; on k3s also the pod range `10.42.0.0/16`, for the
pods). Traefik sees each visitor's real IP: on k3s it takes ports 80 and 443 of its server itself. k3s NodePorts answer only on a server's `ip`.

The installer owns the firewall. The first run, and every run where the rules change, resets it:
rules you added by hand are removed (put them in `firewall_allow`). During that reset the firewall
is off for a few seconds.

## SSH and updates

On every server the installer also:

- turns off SSH login with a password. Only an SSH key works, also for `root`
  (in `/etc/ssh/sshd_config.d/00-ansibro.conf`).
- starts **fail2ban**: an IP with 5 failed SSH logins in 10 minutes is blocked for 10 minutes.
  The other servers and `ssh.allow_from` are never blocked.
- turns on automatic **security updates** from Ubuntu (unattended-upgrades). Docker is not updated
  this way: it stays at the version in `versions.yml`. The server never restarts by itself; when
  `/var/run/reboot-required` exists, restart it when it suits you.

**Warning:** a port you open yourself with `docker run -p`, or with `ports:` in your own swarm stack,
is open to everyone: the firewall cannot block it (that is how Docker works). Use Traefik for web apps.
(Traefik's own metrics port 8082 is limited to the other servers: on Swarm with a rule in Docker's
`DOCKER-USER` chain, on k3s with a NetworkPolicy.)

**Between your servers.** A container on one server reaches another server with its server's IP,
so it can use the same ports as that server. Most of them need a password. These do not, so they
show their data to every container in the cluster: the monitoring agents and the monitoring
server's pages (metrics, logs, Alertmanager), etcd for Patroni, and Patroni's API for reading
(changes on it need a login). Run only containers you trust.

## Good to know

- **The first manager is special.** Portainer, Authelia and Swarmpit's databases run there and
  keep their data there. Keep it first in the `nodes` list: the installer stops if the first manager
  is not the one that made the swarm.
- **With 3 managers, one can go down.** The swarm keeps working, and every manager has the registry
  with all images. Workers and standalone servers pull from the first manager's registry: while it is
  down, they can still run the images they have, but not pull new ones.
- **Where Traefik runs.** Swarm: on the managers. k3s: on the workers (the `tier=app` servers), so the
  masters only run the cluster; with no workers, on the masters. With `tls: letsencrypt` it runs on the
  first of them only: point DNS there (Let's Encrypt checks a domain by calling it, and the call must
  reach the Traefik that asked). With `tls: selfsigned` or `tls: custom` (for example a wildcard
  certificate) it runs on all of them: point DNS to all of them. Only those servers open ports 80 and 443.
- **Tiers.** Each cluster server gets a label `tier`:
  `data` (it runs server apps like a database), `app` (workers, or the managers when there are no
  workers), `gateway` (a swarm manager when there are workers: Traefik only) or `control` (a k3s master
  when there are workers: the cluster only). Kong and Keycloak run on `tier=app` servers. Use
  `node.labels.tier == app` (Swarm) or `nodeSelector: { tier: app }` (k3s) in your own apps too.
  Set `labels: { tier: ... }` on a node to choose yourself. Portainer, Authelia and Swarmpit keep
  their data on the first manager, so they run there.
- **The registry needs a login.** Every server logs in (password in `state/secrets/registry`),
  so a container cannot push a fake image into it.
- **Swarm networks use `10.200.0.0/16`, k3s uses `10.42.0.0/16` and `10.43.0.0/16`.** Your servers' IPs must be outside them.
- **Use a private network between servers, or `wireguard: true`.** Without WireGuard, traffic between servers is not encrypted.
- **The `ip` of a node is its private IP** (or its WireGuard address). DNS must point to the public IP of the servers Traefik runs on.
- **A swarm server cannot change its `ip`.** The installer stops if a server's swarm address differs from `ip`
  (for example after a snapshot restore on a new IP). With `wireguard: true` you only change `host`.
- **Network size (MTU, the biggest network packet) is set for you.** Swarm networks use the smallest MTU of the servers minus 50
  (1370 with WireGuard), so big requests do not hang. This applies to networks the installer creates.
  For your own overlay networks, add `driver_opts: { com.docker.network.driver.mtu: "1370" }` with WireGuard.
- **On cloud servers** the installer tells cloud-init to keep the hostname after a reboot, because
  swarm apps are placed by hostname.
- **Let's Encrypt** needs port 80 reachable from the internet. Without internet use `tls: selfsigned`.

## Files in this repo

| File or folder | What it is |
|----------------|------------|
| `install.sh` | The installer you run. It installs Ansible in `.venv/` and runs `site.yml`. |
| `config.example.yml` | The example config. Copy it to `config.yml`. |
| `inventory.py` | Reads and checks `config.yml`, and tells Ansible about your servers. |
| `site.yml` | The list of steps (the Ansible playbook). |
| `roles/` | One folder per step or app, with its tasks and files. |
| `catalog.yml` | All apps: category, where they run, license, how to reach them. |
| `versions.yml` | Every pinned version: images, packages, k3s. |
| `group_vars/`, `templates/`, `ansible.cfg` | Settings shared by all steps, the summary and `state/handover.json` templates, Ansible's settings. |
| `requirements.txt`, `requirements.yml` | The Python packages (Ansible) and Ansible add-ons the installer downloads. |
| `build-bundle.sh` | Builds an offline bundle. |
| `scripts/` | Small helpers: open and close `state/`, check versions, scan images. |
| `tests/` | `check.py` checks a real install; `test_config.py` checks `config.yml` mistakes; `test_handover.py` checks that `state/handover.json` has no password. |
| `.claude/skills/` | Help for AI agents (set up, install, add an app, update versions). |
