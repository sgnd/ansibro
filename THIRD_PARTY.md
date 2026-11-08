# Third-party software

This project is MIT licensed. The repository has no other software in it, but the installer
downloads and runs the software below. Each one keeps its own license.

The offline bundle (`build-bundle.sh`) contains copies of this software: Docker images,
Ubuntu and Docker apt packages, Python packages, and k3s with its system images. If you share a bundle, you share them too.
Their source code is at the links below and at https://launchpad.net/ubuntu (apt packages).

| Software | License | Source |
|----------|---------|--------|
| Docker Engine | Apache-2.0 | https://github.com/moby/moby |
| containerd | Apache-2.0 | https://github.com/containerd/containerd |
| Docker Buildx and Compose plugins | Apache-2.0 | https://github.com/docker/buildx, https://github.com/docker/compose |
| k3s (with `orchestrator: k3s`; the binary has containerd, runc and flannel in it) | Apache-2.0 | https://github.com/k3s-io/k3s |
| k3s system images (`k3s-airgap-images-amd64.tar.zst` in the bundle): CoreDNS, local-path-provisioner, metrics-server, klipper-helm, klipper-lb, pause (Traefik: see below) | Apache-2.0 | https://github.com/k3s-io/k3s (list in each release's `k3s-images.txt`) |
| BusyBox (in the k3s system images) | GPL-2.0 | https://busybox.net |
| Ansible (ansible-core) | GPL-3.0 | https://github.com/ansible/ansible |
| Python packages for Ansible (bcrypt, cffi, cryptography, Jinja2, MarkupSafe, packaging, pycparser, PyYAML, resolvelib) | MIT, BSD, Apache-2.0 | https://pypi.org (versions in `requirements.txt`) |
| Ansible collections: ansible.posix, community.general, community.library_inventory_filtering_v1 | GPL-3.0 | https://github.com/ansible-collections |
| Docker Registry (distribution) | Apache-2.0 | https://github.com/distribution/distribution |
| Traefik | MIT | https://github.com/traefik/traefik |
| Portainer CE | zlib | https://github.com/portainer/portainer |
| Kong Gateway (OSS) | Apache-2.0 | https://github.com/Kong/kong |
| Swarmpit | EPL-1.0 | https://github.com/swarmpit/swarmpit |
| CouchDB (for Swarmpit) | Apache-2.0 | https://github.com/apache/couchdb |
| InfluxDB 1.x (for Swarmpit) | MIT | https://github.com/influxdata/influxdb |
| Keycloak | Apache-2.0 | https://github.com/keycloak/keycloak |
| Authelia | Apache-2.0 | https://github.com/authelia/authelia |
| Uptime Kuma | MIT | https://github.com/louislam/uptime-kuma |
| Beszel | MIT | https://github.com/henrygd/beszel |
| OpenBao | MPL-2.0 | https://github.com/openbao/openbao |
| Spilo (PostgreSQL + Patroni, with postgres on 2 or more servers) | Apache-2.0 | https://github.com/zalando/spilo |
| Patroni (in Spilo) | MIT | https://github.com/patroni/patroni |
| etcd (for Patroni) | Apache-2.0 | https://github.com/etcd-io/etcd |
| HAProxy (database-proxy) | GPL-2.0 | https://www.haproxy.org |
| socket-proxy (in front of the Docker socket) | MIT | https://github.com/wollomatic/socket-proxy |
| oauth2-proxy (with keycloak) | MIT | https://github.com/oauth2-proxy/oauth2-proxy |
| PostgreSQL | PostgreSQL | https://www.postgresql.org |
| MariaDB | GPL-2.0 | https://github.com/MariaDB/server |
| Redis 8 | AGPL-3.0 (one of its three licenses) | https://github.com/redis/redis |
| Valkey | BSD-3-Clause | https://github.com/valkey-io/valkey |
| RustFS | Apache-2.0 | https://github.com/rustfs/rustfs |
| Garage | AGPL-3.0 | https://git.deuxfleurs.fr/Deuxfleurs/garage |
| RabbitMQ | MPL-2.0 | https://github.com/rabbitmq/rabbitmq-server |
| NATS | Apache-2.0 | https://github.com/nats-io/nats-server |
| Alertmanager, node-exporter, mysqld-exporter, postgres-exporter (Prometheus project) | Apache-2.0 | https://github.com/prometheus |
| Grafana | AGPL-3.0 | https://github.com/grafana/grafana |
| VictoriaMetrics, VictoriaLogs, vmalert | Apache-2.0 | https://github.com/VictoriaMetrics/VictoriaMetrics, https://github.com/VictoriaMetrics/VictoriaLogs |
| cAdvisor | Apache-2.0 | https://github.com/google/cadvisor |
| Vector | MPL-2.0 | https://github.com/vectordotdev/vector |
| redis_exporter | MIT | https://github.com/oliver006/redis_exporter |

Versions are in [`versions.yml`](versions.yml). We use the official images without changes.
