# How to

Keep your passwords safe, back up, add monitoring, and change your cluster.

- [Keep `state/` safe and encrypted](#keep-state-safe-and-encrypted)
- [Back up and restore](#back-up-and-restore)
- [Monitoring and alerts](#monitoring-and-alerts)
- [Add or remove an app or a server](#remove-an-app)
- [Upgrade an app](#upgrade-an-app)
- [Database replicas](#database-replicas) and [Garage on 3 servers](#garage-on-3-servers)

Commands that start with `sudo` run on a server: log in first with `ssh <user>@<server IP>`.
They need `sudo` because the passwords and data in `/opt/ansibro/` are readable by root only.
Commands that start with `./install.sh` run on your computer, in the ansibro folder.

## Keep `state/` safe and encrypted

The `state/` folder holds every password the installer made.
Keep a copy outside the cluster. To keep it encrypted, install [age](https://age-encryption.org)
(`brew install age` on a Mac, `sudo apt install age` on Ubuntu), then make a key once, on the computer
that runs the installer. Keep a copy of the key somewhere safe (a password manager):

```bash
# on your computer
mkdir -p ~/.config/ansibro && age-keygen -o ~/.config/ansibro/age.key
```

From then on `state/` is kept as `state.age`, encrypted.
`./install.sh` opens it while it runs and closes it at the end. To read a password:
`scripts/state.sh open`, and `scripts/state.sh close` when you are done.

## Back up and restore

Add `backup:` to `config.yml` (see [`config.example.yml`](../config.example.yml))
and run `./install.sh`. Every server then backs up each night with [restic](https://restic.net)
(encrypted), and the install runs the first backup right away. What is saved:

- databases (PostgreSQL, MariaDB) as a dump (one file with all the data), while they run. With
  Patroni the primary makes it; with Galera the first server that is in sync. If a dump does not work,
  the folders are still saved, but the backup ends with an error (with victoria the `BackupTooOld` alert follows).
- every other folder in `/opt/ansibro/`: the app is paused for a moment while its files are copied
- RustFS and Garage data as it is, while it runs
- on the first manager: the swarm (your stacks, secrets, configs, networks), `config.yml` and the passwords in `state/secrets/`
- k3s: the volumes on each server (local-path, in `/var/lib/rancher/k3s/storage`), while they run

Not saved: the image registry (the installer fills it again; push your own images again)
and Docker volumes. Keep your own stacks' files in `/opt/ansibro/<stack name>/` so they are saved too:
their containers are paused while copied, like the apps above.

```bash
# on a server, after ssh
sudo ansibro-backup              # back up now
sudo ansibro-backup snapshots    # list the backups
```

To move the cluster to new servers, or after you lost it: make new servers, keep the same node names
and `ip` values (with `wireguard: true` only `host` changes), keep `state/`, and run:

```bash
# on your computer, in the ansibro folder
./install.sh -e restore=true
```

(`-e name=value` gives the installer an extra option.)

Each server gets its newest backup back, the swarm comes back with your stacks, and the databases are
loaded from their dumps. Old servers are removed from the swarm. A restore only runs on new servers.
With a new `domain`, change Uptime Kuma's monitors to it in its web page: after the first install
they are yours, and the installer does not change them.
Lost `state/` too? Then you need the restic password that you saved outside the cluster
(it was in `state/secrets/restic`). Install [restic](https://restic.net) on your computer, then run this.
`<repository>` is `backup.repository` from `config.yml`:

```bash
# on your computer
restic -r <repository> restore latest \
  --host <first manager name> \
  --include /opt/ansibro/backup/stage/installer \
  --target .
```

## Monitoring and alerts

Add `victoria` to `apps` (on a server with at least 2 GB
of free memory), and `monitoring:` with where alerts go: Telegram, email or a webhook (for Slack or Discord,
paste their webhook URL: Ansibro knows their format). See [`config.example.yml`](../config.example.yml).

For a small setup, `beszel` is the light choice instead: CPU, memory, disk and containers of every
server, with alerts you set in its web page. It has no logs and does not use `monitoring:`.
The rest of this section is about victoria.

On every server, agents collect the server (CPU, memory, disk, clock), its containers, the logs of
every container and of the system, and the stats of PostgreSQL, MariaDB, Redis and Valkey. Each minute,
every server also checks that its apps answer on their port, and writes the state of the swarm, the
last backup and WireGuard. Alerts are sent for:

- a server, an app, a container or a swarm service that is down, or restarts again and again
- a disk that is almost full (or fills up within a day), memory or CPU that stays high, a wrong clock
- a backup older than 26 hours, a WireGuard link that is down, a certificate that ends within 14 days
- a database or cache that is down or out of connections, web apps that answer with errors
- the monitoring itself: an agent or exporter that does not answer, alerts that cannot be sent

The rules are in [`roles/observability/files/alerts.yml`](../roles/observability/files/alerts.yml).
Grafana has an "Ansibro overview" dashboard. Logs: `https://logs.<domain>/select/vmui`.

While the installer runs, alerts are muted (except `Watchdog`): servers and apps that are not up yet
would fire alerts for nothing. The mute ends 3 minutes after the install, or after 1 hour if the
install stops half way. You see it in Alertmanager as a silence by `ansibro`.

## Who watches the monitoring?

If the monitoring server stops, it cannot send an alert. So there is a
test alert, `Watchdog`, that is always on. Something on another server checks that it is still there.
If it is gone, the monitoring is broken:

- Uptime Kuma (put `uptimekuma` on another server): the installer adds the monitor
  "Monitoring server (its Watchdog alert)" for you. When the monitoring server, Alertmanager or the
  alert rules stop, the Watchdog alert is gone and Uptime Kuma tells you (add a notification in its
  Settings, for example Telegram). The monitoring server sends an alert when Uptime Kuma's
  server is down, so the two watch each other.
- Or a heartbeat service outside the cluster, like [healthchecks.io](https://healthchecks.io): put its URL
  in `monitoring.heartbeat_url`. Alertmanager sends it a POST about every 2 minutes; set its period to 5 minutes.
  (Uptime Kuma's "Push" monitor does not work here: it takes only GET.)

## Remove an app

Remove it from `config.yml` and run `./install.sh`. The installer stops it
(and its agents, Traefik page and timer). Its data stays in `/opt/ansibro/<app>` on its server:
`sudo rm -rf /opt/ansibro/<app>` if you do not need it. Not removed by itself: the app's database
(drop it in Postgres or MariaDB), its old images in the registry, and its Uptime Kuma monitor
(delete it in Uptime Kuma's web page).

## Remove a server

Move its server apps to other servers first, then remove it from `config.yml`
and run `./install.sh -e remove_nodes=true`. The installer takes it out of the swarm (a manager is
demoted first) and the other servers' firewalls forget it. Without `-e remove_nodes=true` the
installer stops and lists the servers it would remove, so a typo cannot remove one.
Then turn the server off. Never remove the first manager.

## Add a server

Add it to `config.yml`, after the first manager, and run `./install.sh`.

## Change a server's role

From worker to manager, or back. The installer does not do this; it stops and
shows the command: `sudo docker node promote <name>` or `sudo docker node demote <name>` on a manager.

## Add or remove a manager with PostgreSQL on more servers

With PostgreSQL on 2 or more servers (Patroni), etcd runs on every manager. etcd cannot add or
remove its members by itself, so the installer stops when the managers change. Then:

1. On every manager that runs etcd now, stop it and delete its data (it holds only Patroni's state):
   `cd /opt/ansibro/etcd && sudo docker compose down && sudo rm -rf data managers`
2. Run `./install.sh`. etcd starts again, empty, on the new list of managers, and Patroni writes its
   state into it again. PostgreSQL takes no writes for about a minute while etcd is down, and the
   primary may move to another database server (apps that use database-proxy follow it).

## Upgrade an app

Change its tag (the version name) and digest (a fingerprint of that exact image)
in `versions.yml`, then run `./install.sh`. To get the digest of a new version:
`docker buildx imagetools inspect <image>:<tag>` (the top `Digest:` line).
Big Postgres upgrades (for example 18 to 19) need a dump (one file with all the data) and a restore by hand.
A new Docker version is installed one server at a time, so the swarm keeps running.

## Database replicas

**PostgreSQL**: give it a list of servers, `postgres: [db1, db2, db3]`. It then runs with
[Patroni](https://patroni.readthedocs.io).
- What it does: one server is the primary, the others are copies that follow it. When the primary
  is down, another one becomes the primary by itself, in about 30 seconds.
- How apps connect: cluster apps (kong, keycloak, authelia) use `database-proxy`, which always goes
  to the primary. Your own apps in the cluster: `database-proxy_haproxy:5432` (Swarm) or
  `database-proxy.ansibro.svc.cluster.local:5432` (k3s).
- How to see it: `sudo docker exec postgres patronictl list`, on a database server.
- Needs: etcd, which runs on the managers. With 3 managers one can be down; with 1 manager,
  failover needs that manager.
- Alerts: `PostgresNoPrimary`, `PostgresReplicaBehind`.
- Going from 1 server to 2 or more (or back) keeps the data in another way, so the installer stops.
  Make a backup and restore it on new servers with the new `config.yml`.

**MariaDB**: on 3 servers, `mariadb: [m1, m2, m3]`, it is a [Galera](https://mariadb.com/docs/galera-cluster) cluster.
- What it does: every server has all the data, and stays up when one server is down.
- How apps connect: through `database-proxy` (port 3306). It uses the first server, and the
  others when the first is down or out of sync (each server answers a check on port 9200).
- If all 3 servers stop at the same time, start the cluster again by hand: see
  [Galera: recovering a primary component](https://mariadb.com/docs/galera-cluster/high-availability/recovering-a-primary-component).
- Alert: `MariadbClusterSmall`.

**Redis or Valkey**: on 3 servers, `valkey: [c1, c2, c3]`.
- What it does: one primary and two copies. Sentinel (port 26379) runs on each server and makes a
  copy the primary when the primary is down.
- How apps connect: they ask Sentinel where the primary is (Sentinel name `ansibro`, the cache
  password). Authelia does this. For your own app, its Redis client library must support Sentinel
  (most do); give it the three servers with port 26379 instead of one address with port 6379.
- Alert: `CacheNoPrimary`.

## Garage on 3 servers

`garage: [s1, s2, s3]` keeps every file on all 3 servers, so one can
go down. Set it on the first install: the number of copies cannot change later (the installer
stops if the number of Garage servers changes).
