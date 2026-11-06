# Apps: logins and notes

Where the passwords are, what each app needs, and notes for some apps. The list of apps is in the [README](../README.md#apps).

## Where the passwords are

All addresses, users and passwords are in `state/summary.md`. Each password is also a file in
`state/secrets/`. (If `state/` is encrypted: `scripts/state.sh open` first, `scripts/state.sh close` after.)
For developers: the list is in [`catalog.yml`](../catalog.yml).
`state/handover.json` has the same facts for tools that write handover documents, without the passwords.

## What each app needs

- Every app with a web page needs traefik. (rabbitmq, nats and rustfs work without it, but then have no web page.)
- kong needs postgres. keycloak needs a database. authelia needs a database and a cache.
  The installer creates their databases for them.

## Swarmpit: ready to use

The installer makes the admin user (`admin`, password in `state/secrets/swarmpit_admin`).

## Uptime Kuma: ready to use

The installer makes the admin user (`admin`, password in `state/secrets/uptimekuma_admin`) and a
monitor for every app's web page, plus one for the monitoring server (its Watchdog alert) when
victoria is installed. Add a notification (Settings > Notifications) to get told when one is down.
The monitors are made once, at the first install; after that they are yours to change.

## With Keycloak, admin pages use Keycloak

When Keycloak is installed and Authelia is not, the installer makes the realm `ansibro` with the user
`admin` (password in `state/secrets/keycloak_sso_admin`), who sets up an authenticator app at the
first login. oauth2-proxy (`https://oauth.<domain>`) connects Traefik to Keycloak.

## With Authelia, admin pages use Authelia

When you install Authelia, the Traefik dashboard, Kong Manager, Alertmanager
and the other pages that ask for the Traefik login ask for the Authelia login instead (user `admin`, password in `state/secrets/authelia_admin`), with a second factor (an
authenticator app). The first time, Authelia asks for a code that it writes to
`/opt/ansibro/authelia/config/notification.txt` on the first manager.

## OpenBao

OpenBao keeps secrets (passwords, API keys) for your apps. Log in at `https://openbao.<domain>` with the
root token, the admin password (`state/secrets/openbao_root_token`). For each app, make a token or a user
with a policy (the list of secrets it may read). Apps read secrets from
`http://<server ip>:8200/v1/secret/data/<path>`.

After a restart, OpenBao is sealed (locked: it gives out no secrets). To unseal it,
run `./install.sh` again (it unseals it with `state/secrets/openbao_unseal_key`), or unseal it on
the web page. With monitoring, the alert `OpenBaoSealed` tells you.
