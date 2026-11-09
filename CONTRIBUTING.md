# Contributing

Thanks for helping. Ansibro stays small and simple on purpose:
a beginner must be able to read every file. Use simple English.

## Rules

- Simple and easy to read. A beginner should be able to change it. Simple English.
- Open-source apps only. At most two choices per category, the popular one first.
- Pin every version. No `latest`.
- Databases, caches, storage, queues and monitoring are server apps (`runs_on: node`): Docker Compose on the servers you name (some on more than one), not swarm services.

## Suggest an app

Open an issue with the [Suggest an app](https://github.com/sgnd/ansibro/issues/new?template=suggest-an-app.yml) form. An app fits when all of these are true:

- It is open source: its license is on the [OSI list](https://opensource.org/licenses) (so not BSL or SSPL).
- It has an image for Intel/AMD (amd64), with a fixed version (not `latest`).
- It works offline: everything it needs is in its image.
- Its category has fewer than two apps. Each category has two choices at most.

## Report a bug

Open an issue with the [Bug report](https://github.com/sgnd/ansibro/issues/new?template=bug-report.yml) form. For a security problem, see [SECURITY.md](SECURITY.md) instead.

## Add an app

1. Add it to [`catalog.yml`](catalog.yml) with its license and how to reach it.
2. Add its image to [`versions.yml`](versions.yml): tag and the digest of its image index
   (`docker buildx imagetools inspect <image>:<tag>`).
3. Copy a similar role: `roles/postgres/` for a server app, `roles/portainer/` for a swarm app.
   Do not use `ports:` in server apps. Published ports skip the firewall. Use `network_mode: host`.
4. Add it to the lists of apps in other roles:
   - a server app: its ports to `common_app_ports` in
     [`roles/common/defaults/main.yml`](roles/common/defaults/main.yml) (the firewall), and its main port
     to `observability_app_ports` in [`roles/observability/defaults/main.yml`](roles/observability/defaults/main.yml)
     (monitoring checks that it answers);
   - a web page: to `uptimekuma_pages` in [`roles/uptimekuma/defaults/main.yml`](roles/uptimekuma/defaults/main.yml);
   - an admin page: to `authelia_admin_hosts` in [`roles/authelia/defaults/main.yml`](roles/authelia/defaults/main.yml)
     (if it uses the `admin` login), and to the page list above `admin_allow_from` in `config.example.yml`.
     An admin page with its own login uses `traefik_route_middleware: sso` (a server app) or
     `admin@file` when `admin_sso` is set (a swarm app, see `roles/portainer/`): the Authelia or Keycloak
     login comes first. Keep paths that programs call (webhooks, health checks) open with
     `traefik_route_open_paths`.
5. Add it to the Apps table in the [README](README.md#apps), to [`THIRD_PARTY.md`](THIRD_PARTY.md), to
   [`config.example.yml`](config.example.yml), and a check to [`tests/check.py`](tests/check.py).
6. Test on new servers: run `./install.sh` two times (the second run must report `changed=0`),
   then `.venv/bin/python tests/check.py`. We test on DigitalOcean droplets and delete them after.

**AI agents.** [`.claude/skills/`](.claude/skills) has skills for Claude Code and other agents
that read `SKILL.md`: set up `config.yml`, install, add an app, and update versions.

## Send a pull request

1. Make your change on a branch. `main` only takes changes from pull requests.
2. Run the checks. No servers needed. You need `shellcheck`, `yq`, `docker` and `curl`
   (on a Mac: `brew install shellcheck yq`). The first line makes `.venv/` with Ansible:

   ```bash
   ./install.sh config.example.yml --syntax-check
   .venv/bin/pip install ansible-lint==26.10.1
   .venv/bin/python tests/test_config.py      # config.example.yml works, mistakes are refused
   .venv/bin/python tests/test_handover.py    # state/handover.json has no password
   ANSIBRO_CONFIG=config.example.yml PATH="$PWD/.venv/bin:$PATH" ansible-lint --profile production
   shellcheck install.sh build-bundle.sh scripts/*.sh
   scripts/validate-versions.sh               # needs yq, docker and curl
   ```

   Changed a version in `requirements.txt` by hand? Run `scripts/hash-requirements.sh` first: pip only
   installs files whose sha256 is listed there (Dependabot writes the hashes itself).

3. Open the pull request. GitHub runs the same checks (see [`validate.yml`](.github/workflows/validate.yml)).
   They must pass before it can be merged.

## Make a release (maintainer)

1. In [CHANGELOG.md](CHANGELOG.md), rename `## Unreleased` to `## X.Y.Z`. The release workflow uses that
   section as the release notes, and stops if it is missing.
2. Change `--branch vX.Y.Z` in the quick start of [README.md](README.md) and
   [docs/getting-started.md](docs/getting-started.md) to the new tag.
3. Merge, then push the tag `vX.Y.Z`. GitHub builds the offline bundles and publishes the release.

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
