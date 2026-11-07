# Ansibro

[![Validate](https://github.com/sgnd/ansibro/actions/workflows/validate.yml/badge.svg)](https://github.com/sgnd/ansibro/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Set up your servers to run apps, with one command.

## What is it?

You have one or more Linux servers, and you want to run apps on them: your own apps, and the
usual helpers like a web gateway, a database and monitoring. By hand that is a lot of work:
install Docker, join the servers into a cluster, set up a firewall, HTTPS, passwords, backups and alerts.

Ansibro does all of that for you. You write what you want in one file, `config.yml`, and run
`./install.sh`. At the end you get the web address and password of every app.

**Who is it for?** Anyone who can use a terminal and log in to a server with SSH.
You do not need to know Ansible, Docker Swarm or Kubernetes.

**New to this?** Start with [Getting started](docs/getting-started.md): a step-by-step first install,
from renting a server to opening your first app. Words you do not know are explained in
[Words](docs/getting-started.md#words).

**What you get:**

- A Docker Swarm cluster (the default), or k3s (a small Kubernetes).
- 1 server or many. You pick the apps and the server each app runs on.
- A firewall, HTTPS, and a password for every app, made for you.
- Safer servers: SSH with a key only, fail2ban, and automatic security updates.
- Optional: backups each night, monitoring with alerts, an encrypted network between servers.
- Only open-source apps. Every version is pinned in [`versions.yml`](versions.yml), nothing uses `latest`.
- Works without internet, with an offline bundle.

## Requirements

- **Servers** with Ubuntu 24.04 or 26.04, with an Intel or AMD CPU (amd64). ARM servers are not supported.
- **At least 2 CPUs and 4 GB of memory** on each server (a server for monitoring needs 2 GB more).
- **SSH login with a key**, and a user that can use `sudo` without a password.
- **A computer to run the installer**, with Python 3.12 to 3.14 (on a Mac
  `./install.sh` installs it with `brew` if needed): your laptop (macOS or Linux),
  or the first manager server. It logs in to every server with SSH. It uses the server's `host`
  address, or its `ip` if `host` is not set.
- **Internet** on the servers and on that computer (it downloads Ansible from PyPI and Ansible Galaxy),
  or an [offline bundle](docs/offline.md).
- **A domain**, for HTTPS with Let's Encrypt (`tls: letsencrypt`): DNS for `*.<domain>` must already point
  to the public IP of the server Traefik runs on: the first manager (Docker Swarm), or the first worker
  (k3s; the first manager if there are no workers). See [where Traefik runs](docs/how-it-works.md#good-to-know).

Two things used everywhere in these docs:
- Text in `<...>`, like `<domain>`, means: put your own value here (for example `example.com`).
- **The first manager** is the first server with `role: manager` in the `nodes:` list of `config.yml`.

## Quick start

First time? Follow [Getting started](docs/getting-started.md) instead. It shows every step.

```bash
git clone --branch v1.3.0 https://github.com/sgnd/ansibro.git   # the latest release
cd ansibro
cp examples/swarm-1-server.yml config.yml   # or another ready-to-use config, see below
./install.sh
```

**Ready-to-use configs** in [`examples/`](examples/). Copy the one that fits, change the lines marked
`change` (servers, SSH key, domain), and run `./install.sh`. Each one also works offline (see its first lines).

| Config | Servers | Layout |
|--------|---------|--------|
| [`swarm-1-server.yml`](examples/swarm-1-server.yml) | 1 | everything on one server |
| [`swarm-2-servers.yml`](examples/swarm-2-servers.yml) | 2 | manager (gateway + apps), data server |
| [`swarm-3-servers.yml`](examples/swarm-3-servers.yml) | 3 | manager (gateway), worker (apps), data server |
| [`swarm-ha.yml`](examples/swarm-ha.yml) | 9 | 3 managers (gateway), 3 workers (apps), 3 data servers; apps and data keep running when one server stops (with Let's Encrypt, the web pages and the admin login need manager1) |
| [`k3s-4-servers.yml`](examples/k3s-4-servers.yml) | 4 | k3s: master, 2 workers (gateway + apps), data server |
| [`k3s-ha.yml`](examples/k3s-ha.yml) | 9 | k3s: 3 masters, 3 workers (gateway + apps), 3 data servers; apps and data keep running when one server stops (with Let's Encrypt, the web pages need worker1 and the admin login needs master1) |

Data servers keep the databases, cache, storage and monitoring, outside the cluster.
[`config.example.yml`](config.example.yml) explains every setting.

Point DNS for `*.<domain>` to the public IP of the server Traefik runs on **before** you run it, so
Let's Encrypt can check the domain: the first manager with Docker Swarm, the first worker with k3s
(each config in `examples/` says which). Did you set DNS later? With Docker Swarm, log in to the first manager
(`ssh <user>@<its IP>`) and run `sudo docker service update --force traefik_traefik`. With k3s, run
`sudo k3s kubectl -n kube-system rollout restart deployment traefik` on the first manager.
It asks Let's Encrypt for the certificates again.

At the end it prints how to reach each app, and saves it with all passwords in `state/summary.md`.

Run `./install.sh` again any time. It changes what is different in `config.yml`
(an app removed from `config.yml` stops; to remove a server, see [How to](docs/how-to.md#remove-a-server)).

> **Back up the `state/` folder.** It holds all generated passwords. If you lose it,
> the next run makes new passwords that do not match your running databases.
> Always run the installer from the same machine, or copy `state/` with it.
> See [Keep `state/` safe](docs/how-to.md#keep-state-safe-and-encrypted).

## A small example

One server with a gateway, a page to manage your apps, and a database:

```yaml
nodes:
  - { name: server1, ip: 10.0.0.10, host: 203.0.113.10, role: manager }
apps:
  traefik: swarm
  portainer: swarm
  postgres: server1
```

More examples (many servers, servers with two IPs, an encrypted network): [docs/configuration.md](docs/configuration.md).

## Apps

Pick one per category. In `config.yml`, a [swarm app](docs/getting-started.md#words) gets `swarm` (for example `traefik: swarm`).
A server app gets the name of the server it runs on (for example `postgres: server1`);
it runs there with [Docker Compose](docs/getting-started.md#words).
Click a name to open its official website.

| Category | What it does | App | Runs on | Port | Web page |
|----------|--------------|-----|---------|------|----------|
| gateway | HTTPS entry for all web pages | [traefik](https://traefik.io/traefik/) | swarm | 80, 443 | `traefik.<domain>` |
| api-gateway | API keys, limits and routes for your APIs | [kong](https://konghq.com/products/kong-gateway) | swarm | | `kong.<domain>`, `kong-manager.<domain>` |
| management | manage containers in a web page | [portainer](https://www.portainer.io) / [swarmpit](https://swarmpit.io) | swarm | | `portainer.<domain>` / `swarmpit.<domain>` |
| auth | login with a second factor | [keycloak](https://www.keycloak.org) / [authelia](https://www.authelia.com) | swarm | | `keycloak.<domain>` / `authelia.<domain>` |
| database | SQL database | [postgres](https://www.postgresql.org) / [mariadb](https://mariadb.org) | server | 5432 / 3306 | |
| cache | key-value cache | [redis](https://redis.io) / [valkey](https://valkey.io) | server | 6379 | |
| storage | S3 file storage | [rustfs](https://rustfs.com) / [garage](https://garagehq.deuxfleurs.fr) | server | 9000 / 3900 | `rustfs.<domain>/rustfs/console/` |
| queue | messages between apps | [rabbitmq](https://www.rabbitmq.com) / [nats](https://nats.io) | server | 5672 / 4222 | `rabbitmq.<domain>` / `nats.<domain>` |
| uptime | checks from outside that your sites answer, status page | [uptimekuma](https://uptime.kuma.pet) | server | | `uptimekuma.<domain>` |
| monitoring | servers, containers and alerts. victoria: full (also logs, Grafana, `monitoring:` in config.yml); beszel: light | [victoria](https://victoriametrics.com) / [beszel](https://beszel.dev) | server | | `grafana.<domain>` and more, see [How to](docs/how-to.md#monitoring-and-alerts) / `beszel.<domain>` |
| secrets | passwords and keys for your apps | [openbao](https://openbao.org) | server | 8200 | `openbao.<domain>` |

Logins, what each app needs, and notes: [docs/apps.md](docs/apps.md).

## Documentation

| Read this | When you want to |
|-----------|------------------|
| [Getting started](docs/getting-started.md) | install for the first time, step by step. It also explains the words. |
| [Examples of config.yml](docs/configuration.md) | see how to set up one or many servers |
| [Apps](docs/apps.md) | find a password, or read notes about an app |
| [How to](docs/how-to.md) | keep `state/` safe, back up and restore, add monitoring, add or remove apps and servers, upgrade |
| [Check and fix](docs/troubleshooting.md) | check that everything works, or fix a problem |
| [Offline install](docs/offline.md) | install on servers without internet |
| [Docker Swarm or k3s](docs/k3s.md) | use k3s (Kubernetes) instead of Docker Swarm |
| [Advanced](docs/advanced.md) | Kong, Swarmpit, Authelia in front of your own apps |
| [How it works](docs/how-it-works.md) | know what the installer does, and the firewall rules |

## Contributing

Ideas, bug reports and pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).
Plans for later: [docs/roadmap.md](docs/roadmap.md).

## License

[MIT](LICENSE). The apps it installs have their own licenses, see [THIRD_PARTY.md](THIRD_PARTY.md).
Changes: see [CHANGELOG.md](CHANGELOG.md).
Security issues: see [SECURITY.md](SECURITY.md).
