# Roadmap

What is planned next. What is already done is in [CHANGELOG.md](../CHANGELOG.md).
Ideas are welcome: open an issue.

- **TLS for etcd (Patroni).** etcd asks for a login, and only the PostgreSQL servers and the other
  managers can reach it, but its traffic is not encrypted (use a private network or `wireguard: true`),
  and its peer port has no client certificate. Moving a running etcd to TLS needs two rounds of
  restarts, one member at a time, with both listeners open in between.

The rules every change follows are in [CONTRIBUTING.md](../CONTRIBUTING.md).
