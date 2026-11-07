# Ansibro 1.3.1 (draft release notes)

Draft. Not tagged. The version number and the date are the maintainer's to choose. This file is
review material: delete it (or use it as the GitHub release body) before tagging.

1.3.1 is a small release on top of v1.3.0 (tag at `fc13ac2`): fixes, docs and release checks. No new
features and no config changes, except that `config.yml` values ending in a new line are now refused.

## Upgrade from 1.3.0

- Steps: [docs/how-to.md, Upgrade Ansibro](docs/how-to.md#upgrade-ansibro). Back up `state/` and
  `config.yml`, `git fetch --tags && git checkout v1.3.1`, `./install.sh --syntax-check`, then `./install.sh`.
- `config.yml` values that end in a new line (domain, node name, label, `backup.time`, monitoring URLs,
  smarthost) are now refused. This affects only odd configs, for example a YAML block scalar used for the domain.
- `./install.sh -h` and `--help` now print the usage. Before, they went to `ansible-playbook`.

## Changes

- `./install.sh --help` prints the usage. When the config file is missing, the error names the file you
  gave and points to `examples/`.
- A real run makes `state/` readable only by you (0700) before Ansible starts, not only at the end.
  A restore's database dump goes into `state/` for a while.
- Docs: how to upgrade Ansibro itself and how to start over ([docs/how-to.md](docs/how-to.md)).
  [docs/k3s.md](docs/k3s.md): `kubectl` from a laptop needs an SSH tunnel or a `firewall_allow` rule for port 6443.
- CI: the release workflow checks that `CHANGELOG.md` has the tag's section and that the config tests pass
  before it publishes, and uses that section as the release notes. Validate does not keep the token in
  `.git`, jobs have timeouts, and the link check also covers `CODE_OF_CONDUCT.md`.
- The Keycloak admin API calls now say why they skip certificate checks (no change in behavior).

## How this was checked

- Offline, for this draft: `tests/test_config.py`, `tests/test_handover.py`,
  `ansible-playbook site.yml --syntax-check` (for `config.example.yml` and every file in `examples/`),
  `ansible-lint --profile production`, `shellcheck`, `actionlint`, and a check of the relative links in the docs.
- Not run on real servers or on a fresh Mac for this draft.
