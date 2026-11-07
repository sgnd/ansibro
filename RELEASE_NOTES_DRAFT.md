# Ansibro 1.4.0 (draft release notes)

Draft. Not tagged. The version number and the date are the maintainer's to choose.

Why a new version and not "1.3.0": the tag `v1.3.0` already exists. It points to commit `f4a2bd0`
("release: 1.3.0 (#23)"), and its GitHub release was published on 2026-11-07. `main` has 5 commits
after it (#24, #25, #26, #27, #28) plus the release-readiness fixes on this branch. Those changes are
not in v1.3.0. In `CHANGELOG.md` on `main`, some of them are listed under `## 1.3.0` and the rest under
`## Unreleased`. 1.4.0 rather than 1.3.1, because it adds features (`state/handover.json`, Python set up
on a Mac, `./install.sh --help`).

## Upgrade from 1.3.0

- **k3s with `admin_allow_from`: upgrade soon.** In 1.3.0 on k3s, the admin pages were open to everyone
  even with `admin_allow_from` set (see Fixes). Run `./install.sh` with this version to apply the fix.
- Steps: [docs/how-to.md, Upgrade Ansibro](docs/how-to.md#upgrade-ansibro). Back up `state/` and
  `config.yml`, `git fetch --tags && git checkout v1.4.0`, `./install.sh --syntax-check`, then `./install.sh`.
- `config.yml` values that end in a new line (domain, node name, label, `backup.time`, monitoring URLs,
  smarthost) are now refused. This affects only odd configs, for example a YAML block scalar used for the domain.
- `./install.sh -h` and `--help` now print the usage. Before, they went to `ansible-playbook`.

## Fixes (found in the 1.3.0 test round, not in the v1.3.0 tag)

- **k3s: `admin_allow_from` works again.** k3s's load balancer hid the visitor's IP behind a pod address,
  and that pod range was let in, so the admin pages were open to everyone. Traefik now uses host ports 80
  and 443 and sees the real IP. Its service is only inside the cluster.
- **Removing a Swarm server** (`./install.sh -e remove_nodes=true`) no longer fails on a k3s-only step.
- **WireGuard:** new servers get their routes, and removed servers lose theirs, without a restart.
- **PostgreSQL with Patroni:** a server can leave the `postgres` list and join again. A server that comes
  back with an old copy of the data moves it to `data/pgroot.old` and gets a new copy.
- **Docker stays held after an update** (before, apt removed the hold, so unattended-upgrades could change Docker).
- **k3s restore on new servers works:** the old node passwords are forgotten, and each server's k3s volumes
  (local-path, with Traefik's certificates) are in the backup.
- **Backup to a new S3 bucket on Ubuntu 26.04** no longer waits 15 minutes: the repository is created first.
  The config check stops on an S3 bucket name restic cannot use.
- Alerts are muted while the installer runs (except `Watchdog`). The mute ends 3 minutes after the install,
  or after 1 hour if the install stops half way.
- A removed app no longer counts as a change on every later install.
- `AlertRulesFailing` waits 10 minutes, so one error while vmalert starts does not fire it.
- Offline: Ubuntu's daily firmware check (`fwupd-refresh`) is turned off, so it no longer fires `SystemdServiceFailed`.
- `tests/check.py` opens an encrypted `state/` (like `install.sh`), and skips the Uptime Kuma monitor of a removed app.

## New

- **Python on a Mac:** `./install.sh` finds Python 3.12 to 3.14 even when `python3` is Apple's 3.9 (it also
  checks Homebrew's folders, uv and mise). If none is found, it installs Python 3.13 with brew, uv or mise,
  without sudo. A `.venv` built with a Python that is too old, too new or broken is built again.
- **`state/handover.json`:** the servers, the apps and where they run, and the settings the installer worked
  out, for tools that write handover documents. It has no passwords, only the names of the files in
  `state/secrets/`. `tests/test_handover.py` checks it.
- **`state/summary.md`:** says how to change each password. "Runs on" names k3s on k3s. The admin login shown
  is the Authelia or Keycloak login when one of them is installed.

## Release readiness

- `./install.sh --help` prints the usage. When the config file is missing, the error names the file you
  gave and points to `examples/`.
- A real run makes `state/` readable only by you (0700) before Ansible starts, not only at the end.
- Docs: how to upgrade Ansibro itself and how to start over ([docs/how-to.md](docs/how-to.md)).
  [docs/k3s.md](docs/k3s.md): `kubectl` from a laptop needs an SSH tunnel or a `firewall_allow` rule for port 6443.
- CI: the release workflow checks that `CHANGELOG.md` has the tag's section and that the config tests pass
  before it publishes, and uses that section as the release notes. Validate does not keep the token in
  `.git`, jobs have timeouts, and the link check also covers `CODE_OF_CONDUCT.md`.
- The Keycloak admin API calls now say why they skip certificate checks (no change in behavior).

## How this was checked

- Run for this draft, offline: `tests/test_config.py` (108 passed), `tests/test_handover.py` (5 passed),
  `ansible-playbook site.yml --syntax-check` (for `config.example.yml` and every file in `examples/`),
  `ansible-lint --profile production` (0 failures), `shellcheck`, `actionlint`, and a check of the relative links in the docs.
- The test-round fixes above were tested on DigitalOcean by the maintainer, according to `CHANGELOG.md`.
  The later changes (the Mac Python setup, `handover.json`, the summary texts and the release-readiness
  fixes) have not been run on real servers or on a fresh Mac for this draft.
