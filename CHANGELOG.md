# Changelog

## Unreleased

Python on a Mac
- `./install.sh` finds Python 3.12 to 3.14 also when `python3` is Apple's old 3.9 (or a too new
  3.15, which breaks Ansible 2.21): it tries `python3`, `python3.14`, `python3.13` and `python3.12`
  (in PATH and in Homebrew's folders), then uv and mise. With none, on a Mac it installs Python 3.13
  with `brew` (or uv or mise), without sudo. Homebrew is found in `/opt/homebrew/bin` or
  `/usr/local/bin` also when it is not in PATH.
- A `.venv` made with a Python that is too old or too new, or a broken one, is made again.

Handover facts
- The installer also writes `state/handover.json`: the servers, the apps and where they run, and the
  settings the installer worked out (database, cache, Traefik servers, admin login, ...). Tools that
  write handover documents (like dejavu) read it. It has no passwords, only the names of the files
  in `state/secrets/`. `tests/test_handover.py` checks this.

Summary fixes
- `state/summary.md` says how to change each password: some only in the file (the installer sets them
  every run), some in the app and the file together (the installer logs in with them).
- "Runs on" names k3s on k3s (not swarm), and every server of an app on more servers.
- The login shown for the Traefik dashboard, Kong Manager, NATS and the monitoring pages is the
  Authelia or Keycloak login when one of them is installed (not the Traefik password).

Release readiness
- `./install.sh --help` prints the usage. A missing config file names the file you gave and points
  to `examples/` (not always `config.yml`).
- A real run makes `state/` readable by you only (0700) before Ansible starts, not only at the end.
  A restore's database dump goes into `state/` for a while.
- `config.yml` values that end in a new line (domain, node name, label, backup time, URLs, smarthost)
  are refused, like other bad values.
- New in [docs/how-to.md](docs/how-to.md): how to upgrade Ansibro itself, and how to start over.
  [docs/k3s.md](docs/k3s.md): `kubectl` from a laptop needs an SSH tunnel or a `firewall_allow` rule
  for port 6443.
- Releases: the release workflow checks that `CHANGELOG.md` has the tag's section and that the config
  tests pass before it publishes, and uses that section as the release notes.

## 1.3.0

Safer servers
- SSH accepts only keys (no passwords), also for root.
- fail2ban blocks an IP for 10 minutes after 5 failed SSH logins. The other servers and
  `ssh.allow_from` are never blocked.
- Automatic security updates from Ubuntu (unattended-upgrades). Docker stays at its pinned version,
  and the server never restarts by itself.
- `tests/check.py` checks these on every server.
- Tested on DigitalOcean with WireGuard and `ssh.allow_from`: k3s (8 servers), Docker Swarm (3 servers),
  and Docker Swarm offline (bundle built on a server, no internet). Each: install, a second run with
  `changed=0`, all hardening checks pass, SSH still works after the reload, and no server is banned.
  Offline, fail2ban came from the bundle.

Fixes from a full review of the project.

Data and backups
- MariaDB backup: a table row with text like `healthcheck@...` no longer drops the whole table from
  the dump. The app users (for example authelia) are in the dump again: on MariaDB 11 a filter left out
  every user. Only the image's own users (root, healthcheck, mariadb.sys) are left out.
- PostgreSQL restore stops on an error instead of saying it worked.
- A failed database dump no longer stops the backup: the folders are still saved, and the backup
  ends with an error. With Galera the first server in sync makes the dump (not only the first server).
- PostgreSQL with Patroni: the name and addresses now really reach Patroni (Spilo ignored them, so a
  replica could use 127.0.1.1). A new replica that copies a big database no longer fails the install.
- The installer stops when PostgreSQL changes between 1 and 2+ servers, or the number of Garage
  servers changes (both would start with new, empty data).
- Galera: a first install that stopped half way can be run again. Redis/Valkey: a re-run after a
  failover no longer restarts the primary; a restore no longer brings back an old Sentinel state.

Security
- Keycloak's admin console (`/admin`) follows `admin_allow_from`.
- Kong's admin API on Swarm answers only Traefik (a key), not your API services on the kong network.
- NATS's monitoring page listens only on the cluster address.
- Swarmpit and Uptime Kuma get their web address only after the installer made their admin user.
- Traefik on Swarm: apps no longer answer on the metrics port 8082. k3s Traefik sends no usage data.
- k3s: NodePorts answer only on the server's `ip`; the pod rule is limited to the pod network.
- With `ssh.allow_from`, the servers can still reach each other over SSH (the installer on the first
  manager needs it).

Monitoring
- `CacheNoPrimary` fires (it never could), per cache app.
- Galera: the health check no longer fails (and fires `SystemdServiceFailed`) when HAProxy closes
  the connection early.
- Traefik on k3s is monitored too (web apps down, errors, certificates).
- Uptime Kuma checks a page that answers without a login, so a down app shows as down. The servers
  pass `admin_allow_from`, so the checks work with it set.

Other
- Docker and k3s restarts wait until the server is back before the next one; WireGuard loads new
  peers without a restart, and k3s starts after WireGuard.
- k3s: changing a server between manager and worker stops with a clear message; a removed server
  stops k3s, so it does not join again.
- Offline bundle: fails if the apt package list is empty; the Ubuntu image is pinned by digest.
- CI checks that each image tag still points to its digest, checks anchors in links, and Dependabot
  watches `requirements.txt`. The release job alone may write.
- Docs and skills: where DNS must point on k3s, steps for a new app, k3s in THIRD_PARTY.md.
- CI: a pinned image whose tag points to a newer build (official images build a version again) is a note.

Tested on DigitalOcean, two clusters with WireGuard, `ssh.allow_from` and `admin_allow_from` set:
- Swarm (3 managers, 3 data servers: Patroni, Valkey, Garage, Kong, Keycloak, Swarmpit, NATS, victoria,
  Uptime Kuma): install, `tests/check.py` (all pass apart from the test's fake alert webhook), a second
  run with `changed=0`, Patroni failover, backup to a rest-server, and a full restore on 6 new servers
  (`check.py` passes there too, the PostgreSQL data is back on all 3 servers).
- k3s (3 masters, 2 workers, 3 data servers: Galera, Redis, Authelia, Portainer, victoria, Uptime Kuma):
  install, `check.py`, `changed=0`, Galera backup (one dump, the users and data load into an empty
  MariaDB), the role-change stop, removing a worker and adding it back (then `changed=0`, `check.py`
  passes), and a Redis failover (the re-run changes only `replica.conf` and restarts nothing).
- Found and fixed by these tests: WireGuard lost its private key on new peers; k3s admin pages refused
  the servers; the Garage check crashed on re-runs; MariaDB dumps had no users; the PostgreSQL restore
  stopped on the `postgres` database; removing a k3s server failed, stayed in the inventory, was
  skipped without its label, and left an old pod network that broke the server when it joined again.

- **k3s: `admin_allow_from` works again.** k3s's load balancer hid the visitor's IP behind a pod address,
  and that pod range was let in, so the admin pages were open to everyone. Traefik now takes ports 80 and
  443 of its server itself (host ports) and sees the real IP; its service is only inside the cluster
  (the chart reads the type from `service.spec.type`).
- **Removing a Swarm server failed** (`./install.sh -e remove_nodes=true`): a k3s step read an address
  that is not there on Swarm.
- **WireGuard: a new server could not be reached.** New peers are loaded without a restart, but that
  did not add their routes. Now it adds the routes of new servers and removes those of old ones.
- **PostgreSQL with Patroni: a server can leave and join again.** A server removed from the `postgres`
  list stops PostgreSQL at the start of the install, while the others can still reach it, so Patroni hands
  the primary over. A server that joins again with an old copy of the data (it can differ from the
  primary's, and then the server cannot follow) keeps it aside in `data/pgroot.old` and gets a new copy.
- **Docker stays held after an update.** apt took the hold away when it installed the new version, so
  until the next install unattended-upgrades could change Docker.
- Offline: Ubuntu's daily firmware check (`fwupd-refresh`) is turned off; without internet it failed
  every day and fired `SystemdServiceFailed`.
- **k3s restore on new servers works.** The new servers were refused ("Node password rejected": the
  snapshot had the old servers' node passwords), and k3s volumes (local-path, with Traefik's
  certificates) were not in the backup, so Traefik and apps with a volume could not start. Now the old
  node passwords are forgotten, and each server's volumes are saved (while they run).
- **Backup with a new S3 bucket on Ubuntu 26.04 waited 15 minutes.** restic 0.17 and newer try a missing
  bucket again for that long, before it could be made. The installer now creates the repository first.
- The config check stops on an S3 bucket name restic cannot use (before, the install waited for many
  minutes while restic tried again).
- Alerts are muted while the installer runs (except `Watchdog`): a first install no longer sends
  `NodeDown` for servers whose agent was not installed yet. The mute ends 3 minutes after the install.
- A removed app no longer shows as a change on every install after it stopped.
- `tests/check.py` opens `state/` when it is kept encrypted (like `install.sh`), and closes it after.
  It skips the Uptime Kuma monitor of a removed app.
- `AlertRulesFailing` waits 10 minutes: one error while vmalert starts before the metrics database
  no longer fires it.
- Docs: offline time sync on Ubuntu 26.04 (its chrony uses only signed time servers while it has them),
  and what to change by hand in Uptime Kuma after removing an app or restoring with a new domain.

Tested on DigitalOcean for 1.3.0, each with a second run at `changed=0` and `tests/check.py` passing:
- Ubuntu 24.04 and 26.04: swarm-1-server (real Let's Encrypt), swarm-2-servers (labels, timezone),
  swarm-3-servers (Authelia, victoria with a webhook), k3s-4-servers.
- swarm-ha (26.04): install, `changed=0`, `tests/check.py`, `admin_allow_from`, a new S3 bucket for backups.
- swarm-ha (24.04): the installer on a separate machine, S3 backup and encrypted `state/`, Patroni and
  Redis failover, an app upgrade. With WireGuard: a Docker update one server at a time (and back), the
  stop when two servers swap roles, removing a manager and a worker and adding two new ones (with the
  etcd steps from the docs), a Patroni server that leaves and joins again (as a replica and as the
  primary), a backup to a rest-server and a restore on 9 new servers (the PostgreSQL data is back on all 3).
- k3s-ha (24.04 and 26.04): Galera with a first install stopped half way and run again (3 servers in
  sync), Redis with Sentinel, Garage, victoria, Uptime Kuma, S3 backup, and a restore on new servers
  (the MariaDB data is back on all 3 servers, Traefik keeps its certificates).
- k3s `admin_allow_from`: an upgrade from 1.2.0 and new installs (Let's Encrypt with one Traefik, and
  self-signed with a Traefik on each worker): an IP outside the list gets 403, an allowed one gets in.
- Swarm variant (24.04 and 26.04): Kong, Swarmpit, Keycloak, Valkey with Sentinel, NATS, OpenBao, RustFS,
  Uptime Kuma, `tls: selfsigned`, `ssh.port`, `firewall_allow`, WireGuard, removing an app.
- k3s variant (24.04 and 26.04): Kong, Keycloak, PostgreSQL on 2 servers, Valkey, RabbitMQ, Garage,
  OpenBao, `tls: custom`, removing an app.
- Offline (bundle built on a server, no internet): Swarm and k3s on Ubuntu 24.04 and 26.04, with
  `tls: selfsigned`, `admin_allow_from`, and backup to a folder and to a rest-server.
- `acme_server` with Let's Encrypt staging (26.04).

## 1.2.0

Clearer app categories, and one monitoring stack less.
- **Removed: `prometheus`.** `victoria` does the same (metrics, logs, alerts, Grafana) with less
  memory and disk. Use `victoria` in `apps` instead.
- The category `monitoring` is now `victoria` (full) or `beszel` (light: servers and containers,
  alerts set in its web page, no logs). `monitoring:` in `config.yml` is where victoria sends alerts.
- `uptimekuma` has its own category, `uptime` (it checks from outside that your sites answer), so it
  can run next to either monitoring app.
- The Apps table in the README has a "What it does" column, and uses the exact category names.

Ready-to-use configs in `examples/`: Swarm on 1, 2, 3 and 9 servers, k3s on 4 and 9 servers, each with
the offline change in its first lines. CI checks every one, online and offline.
- Servers get their `tier` from their role: with workers, a swarm manager is `gateway` (Traefik only)
  and a k3s master `control` (the cluster only); apps go to the `tier=app` workers.
- k3s: Traefik runs on the workers, not the masters (with Let's Encrypt on the first worker).
- Ports 80 and 443 are open only on the servers Traefik runs on.

Every app is ready to use: you only log in.
- Uptime Kuma: the installer makes the admin user (`state/secrets/uptimekuma_admin`), a monitor for
  every app's web page, and one for the monitoring server (its Watchdog alert). No Traefik login in front.
- Swarmpit: the installer makes the admin user (`state/secrets/swarmpit_admin`). No Traefik login in front.

Tested on DigitalOcean with every config in `examples/`: swarm-1, swarm-2, swarm-3 and k3s-4 (with
Let's Encrypt on a real domain) online; swarm-ha (9 servers) online; swarm-3 and k3s-ha (9 servers)
offline, with no internet. `tests/check.py` passes (apart from alerts to the test's fake webhook), and a
second run changes nothing. Found and fixed by these tests: k3s's load balancer opened 80/443 on every
server (now only on the Traefik servers), and two problems in the new Uptime Kuma setup.

## 1.1.0

**Removed: GPU servers and ARM (arm64) servers.** Ansibro now runs on Intel/AMD (amd64) servers only,
to keep it small and fully tested. `gpu:` on a node and `arch:` in `config.yml` are gone (the installer
says so if they are still there), and so are the NVIDIA driver and toolkit, dcgm-exporter and the GPU
alerts. The offline bundle is one per Ubuntu version: `./build-bundle.sh [24.04|26.04]` makes
`dist/ansibro-<ubuntu>.tar.gz`. An ARM server stops the install with a clear message.
Tested on DigitalOcean after the change: Swarm with 3 managers online, and k3s from the new bundle
with no internet. On k3s the installer now waits until Traefik runs (offline it takes some minutes),
so the web pages work when the install ends.

Annible (the old name) is now called Ansibro: the repo is github.com/sgnd/ansibro, app files are in
`/opt/ansibro`, and the commands are `ansibro-backup` and `ansibro-metrics`.

Easier for beginners: a step-by-step guide with a list of words ([docs/getting-started.md](docs/getting-started.md)),
a simpler README, and clearer messages. A real install now stops early when `domain` or `acme_email`
are still example.com, or `ssh.key` is missing. A tab or a wrong indent in `config.yml` gives the line number.
The README is short now: details moved to [docs/](docs/) (how to, apps, check and fix, offline, k3s, advanced, how it works).

Tested on real servers (Ubuntu 24.04), with `tests/check.py` passing and a second run with no changes:
- Docker Swarm, 3 managers + 3 data servers (DigitalOcean): the registry and Traefik on every manager
  (also with the first manager turned off), tier labels, Garage on 3 servers, OpenBao, the per-port
  firewall, `state.age`, monitoring with webhook alerts, backup to a folder and to S3, removing an app
  and a server; PostgreSQL with Patroni (the primary stopped: another took over, writes through
  database-proxy kept working, the old one came back as a copy); Valkey with Sentinel (the same);
  Keycloak as the login for admin pages; Kong through database-proxy.
- k3s, 3 servers + 3 data servers over WireGuard: portainer, authelia, MariaDB Galera, Redis with
  Sentinel, prometheus monitoring; then all servers deleted and new ones made, and `-e restore=true`
  brought back the cluster (etcd snapshot) and the data.
- k3s from the offline bundle, on a server with no internet.
- A mixed cluster: an amd64 manager (DigitalOcean) and an arm64 worker (Google Cloud), over WireGuard.
- A GPU server (NVIDIA H100): driver, toolkit, GPU metrics.
- Alerts to Telegram, email and a webhook.
- A release: the workflow builds the four bundles and attaches them to the release (pre-release v1.1.0-rc1).

Fixed by these tests: the NVIDIA driver choice (the "open" one first), Spilo's data folder owner,
the MariaDB Galera health check, MariaDB dumps without Galera's own tables, Kong reaching
database-proxy, Authelia on k3s (service links), k3s offline (the program comes from the bundle),
a swarm that is "pending" right after Docker restarts, the backup repository on S3 servers that
show a new repository a moment later.

New
- Keycloak as the login for admin pages (when Authelia is not installed): realm `ansibro`, user
  `admin` with a second factor, through oauth2-proxy. Works on Swarm and k3s.
- k3s: `orchestrator: k3s` makes a k3s (Kubernetes) cluster instead of Docker Swarm: managers are
  k3s servers (embedded etcd), workers agents. Pinned version, offline bundle, WireGuard, registry
  mirror, firewall, built-in Traefik with routes to server apps, metrics and alerts (K3sNodeDown,
  K3sDeploymentDown, K3sPodsStuck), etcd snapshot in the backup and `-e restore=true`, node removal.
  portainer, kong, keycloak and authelia run on k3s too; swarmpit is Swarm only. In `apps`, `cluster`
  is the same as `swarm`.
- `gpu: true` on a node: NVIDIA driver, NVIDIA Container Toolkit (pinned), `nvidia` as Docker's
  default runtime, label `gpu=true`, and GPU monitoring with dcgm-exporter (3 GPU alerts).
- Each GitHub release gets the offline bundles for amd64 and arm64, Ubuntu 24.04 and 26.04,
  built by GitHub Actions (`.github/workflows/release.yml`).
- Remove an app: take it out of `config.yml` and run `./install.sh`. It stops (data kept).
- Remove a server: take it out of `config.yml` and run `./install.sh -e remove_nodes=true`.
  Without that option the installer stops and lists the servers it would remove.
- `openbao` app: secrets for your apps. The installer sets it up, saves the unseal key and root
  token in `state/secrets/`, unseals it on every run, and turns on `secret/` (KV version 2).
  Alert `OpenBaoSealed` when it needs unsealing after a restart.
- Zero trust:
  - Between your servers, only the ports in use are open (swarm, registry, each server's apps,
    monitoring agents). Before, servers could reach every port of each other.
  - With Authelia, every admin page uses the Authelia login with a second factor, instead of the
    Traefik password.
  - `state/` can be kept encrypted as `state.age` (with [age](https://age-encryption.org)):
    create a key in `~/.config/ansibro/age.key` and the installer does the rest. `scripts/state.sh`.
  - CI scans every pinned image for known security problems (`scripts/scan-images.sh`), each Monday.
- PostgreSQL on 2 or more servers (`postgres: [db1, db2, db3]`) runs with Patroni (Spilo image) and
  etcd on the managers: automatic failover. Cluster apps connect through database-proxy (HAProxy),
  which always goes to the primary. Alert `PostgresNoPrimary`.
- MariaDB on 3 servers is a Galera cluster (through database-proxy). Redis or Valkey on 3 servers
  run with Sentinel (automatic failover; Authelia uses Sentinel). Alerts `MariadbClusterSmall`,
  `CacheNoPrimary`.
- Garage on 3 servers: `garage: [s1, s2, s3]` keeps 3 copies of every file.
- HA: every manager runs the image registry with the same images (apps use the name
  `registry.ansibro`), so images can be pulled when a manager is down. Traefik runs on every
  manager, except with `tls: letsencrypt` (see README). Swarm servers get the label `tier=data`
  (they run server apps) or `tier=app`; Kong and Keycloak run on `tier=app` servers.
- Monitoring and alerts: `prometheus` (Prometheus + Loki) or `victoria` (VictoriaMetrics + VictoriaLogs),
  both with Alertmanager and Grafana. Agents on every server collect the server, its containers, all
  logs and the database stats. Alerts for servers, apps, containers, swarm services, disks, memory,
  clock, backups, WireGuard, certificates, databases and the monitoring itself, sent to Telegram,
  email or a webhook (`monitoring:` in `config.yml`). An always-firing `Watchdog` alert, checked by
  Uptime Kuma on another server (or a heartbeat service), tells you when the monitoring itself is down.
- `backup:` nightly backup of every server with restic (S3, rest-server or a mounted folder):
  database dumps, app folders (paused for a moment while copied), RustFS/Garage data, and on the
  first manager the swarm state, `config.yml` and `state/`. The install runs the first backup.
- `./install.sh -e restore=true`: put the newest backup back on new servers. The swarm comes back
  with your stacks, the databases are loaded from their dumps, and old servers leave the swarm.
- `host` per node: the address the installer connects to over SSH, when it is not the node's `ip`.
  For servers with more than one IP, like a public IP for SSH and a private IP for the cluster.
- `wireguard: true`: an encrypted WireGuard network between all servers. The swarm uses only the
  WireGuard addresses (`ip`), so a server's real address (`host`) can change.
- Swarm networks get the right MTU (smallest server MTU minus 50), so big requests do not hang on
  WireGuard or on clouds with a smaller network MTU. New networks only.
- The installer finds each server's CPU type itself; `arch:` in `config.yml` is now optional.
  With internet, amd64 and arm64 servers can be in one cluster: the local registry keeps every
  image for each CPU type in use.
- On cloud servers, cloud-init keeps the hostname and `/etc/hosts` after a reboot.
- The install stops with a clear message if a server's swarm address differs from its `ip` in `config.yml`
  (for example after a snapshot restore on a new IP).

Updates
- Traefik v3.7.17.

Fixes
- From the final review, tested on DigitalOcean: Swarm 3 managers + 3 data servers (Patroni, Redis
  Sentinel, Garage, Keycloak, prometheus) with backup, then all servers rebuilt and `-e restore=true`;
  k3s 3 servers + 3 data servers (MariaDB Galera, Authelia, victoria); offline from the bundle with
  3 managers and no internet. `tests/check.py` passes and a second run changes nothing. Also k3s with
  `tls: letsencrypt` on a real domain (3 servers + 1 data server, Keycloak, Portainer). And with
  `wireguard: true`: Swarm with Patroni grown from 1 to 3 managers (the installer stops, the steps in
  docs/how-to.md work, Patroni stays healthy), and k3s with MariaDB Galera and Authelia.
  - Offline with more than one manager: every manager gets the registry image from the bundle.
  - PostgreSQL with Patroni: etcd compacts its old values (it filled up after some weeks), etcd's
    data is no longer in the backup, a restore loads the dump on the new primary (it may be another
    server than at backup time), and the backup waits for a primary during a failover. The installer
    stops when the managers change; docs/how-to.md shows the steps. Patroni's API needs a login for changes.
  - MariaDB with Galera: database-proxy uses a server only when it is in sync (a check on port 9200).
    Authelia goes through database-proxy too.
  - Garage's key may make buckets.
  - k3s: with `tls: letsencrypt`, Traefik runs on the first manager (point DNS there); else on every
    cluster server. `acme_ca_cert` works on k3s. Pod logs and container metrics reach the monitoring.
  - Traefik's metrics port 8082 is open only to the other servers (Docker skipped the firewall for it).
    The SSH replies rule opens only the short-lived local ports.
  - Turning off a database on more servers removes etcd, database-proxy and the Galera check.
    Redis and Valkey restart one server at a time. Beszel's login token is not shown in logs.
  - Found by these tests: k3s without WireGuard sent its pod network (flannel) over the public IP,
    which the firewall closes, so pods on different servers could not reach each other; it now uses
    the interface of `ip`. Patroni's API login is set through Spilo's own setting. A second install
    no longer reports a change (the backup copied `state/summary.md`; now `state/secrets/` only).
  - k3s with `tls: letsencrypt`: only the Traefik dashboard got a Let's Encrypt certificate. Each
    route's own `tls: {}` hid the Let's Encrypt setting; the routes now name it.
- Docker Hub allows few downloads without a login (429 Too Many Requests). Images are now copied
  from Google's copy of Docker Hub (mirror.gcr.io, same pinned digest) when they can be, each image
  is downloaded once (the other managers copy it from the first), and Docker and k3s use the mirror too.
- With `wireguard: true` and the installer on one of the servers, the install could hang on new
  servers when the firewall or Docker started. The firewall now always lets SSH replies from the
  other servers in.
- The local registry kept only one CPU type of each image. It now copies the image for every
  CPU type in the cluster (`docker buildx imagetools`). The first manager trusts the registry
  certificate for this.

## 1.0.1

Fixes from a full independent review of 1.0.0. Upgrade: pull, then run `./install.sh` again.

Security
- Swarmpit and Uptime Kuma now ask for the Traefik dashboard login first. Before, anyone could
  open them and create the first admin user.
- The local registry needs a login. Every server logs in; Swarm passes the login to its tasks.
- Kong runs on its own `kong` network, so other apps cannot reach its admin API.
- Swarm join tokens, the Redis/Valkey password and the Garage key no longer show up in output or
  process lists.

Fixes
- Swarm networks use `10.200.0.0/16`, so servers on `10.0.0.x` work. (New swarms only.)
- A renewed custom TLS certificate is loaded (Traefik restarts).
- Docker upgrades run one server at a time.
- The install stops with a clear message, before it changes anything, if the first manager is not
  the one that made the swarm, or if a server's role in `config.yml` differs from the swarm.
- If one server fails a check, the whole install stops (not only that server).
- A mistake in `config.yml` stops `./install.sh` with an error. Before, it could end with "success"
  and do nothing.
- Stack deploys wait until a rolling update is finished.
- Kong restarts when its database password changes.
- Downloading an image (install and `build-bundle.sh`) tries again (3 times) after a network error.
- Database passwords are set on every run, so they always match `state/secrets/`.
- Kong `migrations finish` runs after the new Kong is up.
- The offline bundle only contains files committed to git.
- More config checks: `domain`, `nodes`, `labels`, `localhost`, `firewall_allow`.

New
- `firewall_allow` in `config.yml` for your own open ports (for example a VPN).

Other
- LICENSE names Annible, CI actions pinned to commits, `ansible-lint` pinned, this changelog.

## 1.0.0

First release.
