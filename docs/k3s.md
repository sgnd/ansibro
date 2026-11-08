# Docker Swarm or k3s

Ansibro sets up Docker Swarm by default. It can set up k3s (a small Kubernetes) instead.

To choose, set `orchestrator: swarm` (the default) or `orchestrator: k3s` in `config.yml`. Everything around the
cluster is the same: firewall, WireGuard, registry, server apps (databases, storage, monitoring...),
backup, monitoring and alerts, offline bundle.

With k3s:
- Managers are k3s servers (3 managers = the cluster survives one down), workers are k3s agents.
  Standalone servers run server apps and are not in the cluster. The pinned k3s version is in `versions.yml`.
- Workers join with the agent token (`state/secrets/k3s_agent_token`), managers with the server token
  (`state/secrets/k3s_token`). A worker never gets the server token: with it, it could read the cluster's
  keys. A cluster made by Ansibro 1.3.0 or older gets the agent token at the next `./install.sh`: the
  managers restart one by one, then the workers (running pods keep running).
- Use `kubectl` on a manager: `sudo k3s kubectl get nodes`. To use it from your laptop, copy
  `/etc/rancher/k3s/k3s.yaml` from a manager and change `127.0.0.1` in it to the manager's address.
  The firewall opens port 6443 only to the other servers, so also do one of these: keep `127.0.0.1` and
  open an SSH tunnel first (`ssh -L 6443:127.0.0.1:6443 <user>@<manager>`), or open 6443 to your own IP
  with `firewall_allow: [{ port: 6443, proto: tcp, from: <your IP> }]` in `config.yml`.
- Traefik is k3s's built-in one: `traefik: cluster` in `apps`. Server apps get their web pages through it
  like with Swarm. It runs on the workers, so the masters only run the cluster (no workers: on the masters).
  With `tls: letsencrypt` it runs on the first worker only: point DNS there. Else on every worker: point DNS to all of them. Your own apps: an `Ingress` or Traefik `IngressRoute`.
- Pods pull from the cluster's registry: `registry.ansibro:5000/<image>:<tag>`. To push your images there, open it
  first with `sudo ansibro-registry open` (see [How to](how-to.md#your-own-images)).
- portainer, kong, keycloak and authelia run on k3s too, in the `ansibro` namespace (`kong: cluster`, ...).
  Only Traefik can reach Kong (a NetworkPolicy). swarmpit is for Swarm only.
- The backup has a k3s (etcd) snapshot, and `-e restore=true` puts the cluster back from it.
