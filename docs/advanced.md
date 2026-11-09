# Advanced

Extra options: installer flags, Kong, Swarmpit, and the Authelia login for your own apps.
You do not need these for a normal install.

## More installer options

Extra `ansible-playbook` options go after the config file,
for example `./install.sh config.yml -v` (more output). Check mode (`--check`) is not supported.

## Kong

Kong runs on its own network, `kong`, shared only with Traefik. Put your API services on that
network too (`networks: [kong]`, external) so Kong can reach them. Other apps cannot reach Kong's admin API.

## Swarmpit

Swarmpit needs CouchDB 2.3 and InfluxDB 1.8, which are old. They are only on Swarmpit's own
network, but if you want only up-to-date software, choose Portainer.

## Authelia login in front of an app

Add `authelia@file` to the app's Traefik middlewares:
for a swarm app in `roles/<app>/templates/stack.yml.j2` (the `...middlewares` label, comma-separated),
for a server app with a web page set `traefik_route_middleware: authelia@file` in `roles/<app>/tasks/main.yml`.
A server app has one middleware, so this replaces its `admin_allow_from` limit (on Swarm and k3s).
For an admin page that has its own login, `traefik_route_middleware: sso` keeps `admin_allow_from` and
adds the Authelia or Keycloak login when one is installed (the servers skip it; see
[`roles/traefik/tasks/route.yml`](../roles/traefik/tasks/route.yml)).
