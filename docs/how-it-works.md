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
| etcd for Patroni (managers): 12380 | the other managers only |
| etcd for Patroni (managers): 12379 | the PostgreSQL servers only |
| UDP 51820 | other servers' `host`, with `wireguard: true` |
| everything except etcd | containers on Docker networks of the same server, also your own Docker Compose networks (with k3s also its pods, `10.42.0.0/16`, on `cni0` and `flannel.1`) |
| your own ports | `firewall_allow` in `config.yml` (for example a VPN) |

Everything else is blocked. Server apps use the host network, so the firewall controls them.
Even between your servers only those ports are open (the list is `common_app_ports` in
`roles/common/defaults/main.yml`). An app of your own on a server's host network needs a `firewall_allow` rule.
Admin web pages can be limited to some IPs with `admin_allow_from` (the servers themselves are always
let in too: Uptime Kuma checks the pages from there; on k3s also the pod range `10.42.0.0/16`, for the
pods). Traefik sees each visitor's real IP: on k3s it takes ports 80 and 443 of its server itself. k3s NodePorts answer only on a server's `ip`.
When `admin_allow_from` is empty, `./install.sh` warns at the start and at the end (and in `state/summary.md`):
the admin pages are then open to the whole internet. With Authelia or Keycloak installed, every admin
page asks for that login too, also the ones with their own login (Portainer, Grafana, ...); requests from
the servers, and a few paths that programs call, skip it (see [Apps](apps.md#with-authelia-or-keycloak-every-admin-page-asks-for-that-login)).

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
show their data to every container in the cluster: the monitoring agents, the metrics and logs
(VictoriaMetrics and VictoriaLogs: reading and adding; deleting needs a key), and Patroni's API for
reading (changes on it need a login). Alertmanager needs a login, so a container cannot mute the alerts.
etcd for Patroni is closed to every container (also on other servers: the firewall drops their calls
to it before they leave their server), and it asks for a login (user `patroni`). Run only containers you trust.

## Good to know

- **etcd for Patroni asks for a login.** User `patroni` (`state/secrets/etcd_patroni`) may only read and
  write Patroni's keys; `root` (`state/secrets/etcd_root`) is for the installer. A change to etcd restarts
  its members one at a time, and a change to PostgreSQL with Patroni restarts the servers one at a time,
  the primary last after a switchover (writes stop for a few seconds).
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
- **The registry needs a login, and is read-only.** Every server logs in (password in `state/secrets/registry`).
  Only the installer pushes images, and only while it runs; to push your own, run `sudo ansibro-registry open`
  on a manager first (see [How to](how-to.md#your-own-images)).
- **Apps run their images by digest** (`registry.ansibro:5000/<name>:<tag>@sha256:...`, the fingerprint of the
  exact image), not only by tag. The installer reads each digest right after it pushed the image itself, and keeps
  it in `state/images.yml`. An image pushed later under the same tag is never run, and the next install stops and says so.
- **Traefik, Vector and the Beszel agent only read Docker**, through a socket proxy
  ([socket-proxy](https://github.com/wollomatic/socket-proxy)): GET on a few parts of Docker's API, nothing that
  starts or changes a container. Traefik faces the internet, so this matters most there. Portainer and Swarmpit
  manage containers, so they use the Docker socket itself (see [Apps](apps.md#portainer-and-swarmpit-full-control-of-docker)).
  cAdvisor runs privileged anyway (it reads the kernel's container stats).
- **Swarm secrets.** Keycloak (and its oauth2-proxy) and Kong get their passwords as swarm secrets (files in
  `/run/secrets`), not in their settings: whoever may read the swarm's services does not see them. (k3s: Kubernetes secrets.)
- **k3s workers join with the agent token** (`state/secrets/k3s_agent_token`), the managers with the
  server token (`state/secrets/k3s_token`). The server token also gives the cluster's keys, so it stays
  on the managers.
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
| `requirements.txt`, `requirements.yml` | The Python packages (Ansible, each with the sha256 of its files: pip refuses others) and Ansible add-ons the installer downloads. |
| `build-bundle.sh` | Builds an offline bundle. |
| `scripts/` | Small helpers: open and close `state/` (and make its key), check versions, scan images, write the hashes in `requirements.txt`. |
| `tests/` | `check.py` checks a real install; `test_config.py` checks `config.yml` mistakes; `test_handover.py` checks `state/handover.json` has the facts and no password. |
| `.claude/skills/` | Help for AI agents (set up, install, add an app, update versions). |
