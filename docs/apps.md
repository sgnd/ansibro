# Apps: logins and notes

Where the passwords are, what each app needs, and notes for some apps. The list of apps is in the [README](../README.md#apps).

## Where the passwords are

All addresses, users and passwords are in `state/summary.md`. Each password is also a file in
`state/secrets/`. (If `state/` is encrypted: `scripts/state.sh open` first, `scripts/state.sh close` after.)
For developers: the list is in [`catalog.yml`](../catalog.yml).
`state/handover.json` has the same facts for tools that write handover documents, without the passwords.

## What each app needs

- Every app with a web page needs traefik. (rabbitmq, nats, rustfs and openbao work without it, but then have no web page.)
- kong needs postgres. keycloak needs a database. authelia needs a database and a cache.
  The installer creates their databases for them.

## Swarmpit: ready to use

The installer makes the admin user (`admin`, password in `state/secrets/swarmpit_admin`).

## Uptime Kuma: ready to use

The installer makes the admin user (`admin`, password in `state/secrets/uptimekuma_admin`) and a
monitor for every app's web page, plus one for the monitoring server (its Watchdog alert) when
victoria is installed. Add a notification (Settings > Notifications) to get told when one is down.
The monitors are made once, at the first install; after that they are yours to change. One exception:
the Watchdog monitor logs in to Alertmanager (user `ansibro`, password in `state/secrets/alertmanager`),
and every install sets that login on it again (on the monitor with the name and address the installer
gave it).

## With Keycloak, admin pages use Keycloak

When Keycloak is installed and Authelia is not, the installer makes the realm `ansibro` with the user
`admin` (password in `state/secrets/keycloak_sso_admin`), who sets up an authenticator app at the
first login. oauth2-proxy (`https://oauth.<domain>`) connects Traefik to Keycloak.

## With Authelia, admin pages use Authelia

When you install Authelia, the Traefik dashboard, Kong Manager, Alertmanager
and the other pages that ask for the Traefik login ask for the Authelia login instead (user `admin`, password in `state/secrets/authelia_admin`), with a second factor (an
authenticator app). The first time, Authelia asks for a code that it writes to
`/opt/ansibro/authelia/config/notification.txt` on the first manager.

## With Authelia or Keycloak, every admin page asks for that login

Portainer, Swarmpit, Grafana, OpenBao, RabbitMQ, the RustFS console, Uptime Kuma and Beszel have their
own login. With Authelia or Keycloak installed, they ask for the Authelia or Keycloak login (with a
second factor) first, then for their own. Without Authelia or Keycloak they only have their own login.
Some requests skip the Authelia or Keycloak login (but not `admin_allow_from`, and not the app's own login):

- requests from your servers' `ip` (and on k3s from pods): Uptime Kuma checks the pages from there.
  (A call to the web address through the public IP comes from a public address: it gets the login.)
- paths that programs call: Uptime Kuma's status pages, push monitors and badges, Portainer's
  webhooks (to redeploy from CI) and health check, and the health checks of Grafana, OpenBao and Beszel.

A program that calls one of these apps' API by its web address (for example the `bao` command,
Terraform, or `rabbitmqadmin` on your laptop) cannot pass the Authelia or Keycloak login. Your apps in
the cluster use the app's port on its server's `ip` instead (like `http://<ip>:8200` for OpenBao); from
your laptop, use an SSH tunnel (`ssh -L 8200:<server ip>:8200 <user>@<server>`).

Keycloak's own admin console (`/admin`) only follows `admin_allow_from`: Keycloak is the admin login,
and if its realm broke you could not get in to fix it.

## Alertmanager, VictoriaMetrics and VictoriaLogs

Alertmanager asks for a login (user `ansibro`, password in `state/secrets/alertmanager`), because its
API can mute every alert. vmalert, Grafana, Uptime Kuma and the installer use it. The web page
`https://alertmanager.<domain>` asks only for the admin login: Traefik adds Alertmanager's login.
From a server: `curl -u ansibro:<password> http://<monitoring server ip>:9093/api/v2/alerts`.

VictoriaMetrics and VictoriaLogs ask for a key (`state/secrets/victoria_admin_key`) on their pages that
delete or move data (delete series, snapshots, partitions, force merge), for example
`curl -g -X POST 'http://<ip>:8428/api/v1/admin/tsdb/delete_series?match[]=<series>&authKey=<key>'`.
Reading and adding metrics and logs needs no login: any container in the cluster can still read
them, so run only containers you trust.

## OpenBao

OpenBao keeps secrets (passwords, API keys) for your apps. Log in at `https://openbao.<domain>` with the
root token, the admin password (`state/secrets/openbao_root_token`). For each app, make a token or a user
with a policy (the list of secrets it may read). Apps read secrets from
`http://<server ip>:8200/v1/secret/data/<path>`.

After a restart, OpenBao is sealed (locked: it gives out no secrets). To unseal it,
run `./install.sh` again (it unseals it with `state/secrets/openbao_unseal_key`), or unseal it on
the web page. With monitoring, the alert `OpenBaoSealed` tells you.
