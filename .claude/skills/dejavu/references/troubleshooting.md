# Every message, and what to do

Each line of `handover.py` starts with `ok:`, `warning: [id]`, `needs the user: [id]` or `failed: [id]`. Find the id here.

## Warnings from `facts`: the user decides

Go through each with the user. They either fix it (a change in `config.yml`, then `./install.sh`, only with their consent) or accept it: then write it into `known_issues` in their words. Every warning also appears in the documents, in the known-issues appendix.

| Id | What it means | What to say or do |
| --- | --- | --- |
| `allowlist-empty` | `ssh.allow_from` or `admin_allow_from` is empty, so anyone on the internet can try to log in to SSH or open the admin pages. | Recommend listing the office or VPN IPs. The documents say "open to anyone". |
| `tls-selfsigned` | The web pages use a certificate browsers do not trust, so every page shows a warning. | Recommend `tls: custom` (a bought or company certificate) or an internal CA (`acme_server`). |
| `custom-cert-expires` | The certificate in `tls_cert` ends within 90 days. | Renew it before the handover, or record who renews it. |
| `no-backup` | `backup:` is not set: nothing is backed up. | Strongly recommend setting a backup repository. The BAST notes it. |
| `backup-no-alert` | Backups run, but no monitoring app (victoria) alerts when they stop. | Recommend victoria, or a regular manual check. |
| `no-monitoring` | No monitoring app: nobody is told when something breaks. | Recommend victoria (full) or beszel (light). |
| `uptimekuma-notifications-manual` | Uptime Kuma checks the pages, but sends no message until notifications are set in its own page. | Set them at the handover meeting (it is a row in Annex 1). |
| `beszel-alerts-manual` | Beszel alerts are set in Beszel's own page. | Set them at the handover meeting (Annex 1). |
| `swarmpit-old-databases` | Swarmpit uses CouchDB 2.3 and InfluxDB 1.8, which are old. | A known risk: mention it; Portainer is the alternative. |
| `missing-secret` | ansibro should have written this password file, but it is not in state/. | Usually `authelia_admin` after state/ was rebuilt: the password is in `users.yml` on the first manager. The documents say "not in state". |
| `stale-secret` | A password file of an app that is no longer installed. | It goes into the "Old" group of the credentials file; the app's data may still be in `/opt/ansibro/<app>`. |
| `unknown-secret` | A password file dejavu does not know (a newer ansibro). | It goes into the "Internal" group. Report it so dejavu learns it. |
| `unknown-app` | An app dejavu does not know (a newer ansibro). | The documents use ansibro's own short text. Ask the user for a sentence about it and put it in `extra_apps`. |
| `not-documented` | A setting in `config.yml` that dejavu does not know. | It is left out of the documents. Report it so dejavu learns it. |
| `ansibro-untested-version` | ansibro is newer or older than the versions this skill was tested with. | The documents are still made; read them carefully. |
| `ansibro-dirty` | The ansibro folder has changes that are not committed. | Check that what was installed is what is in the folder. |
| `shared-state` | There are several `config*.yml` here, sharing one state/. | Make sure `--config` names the one this handover is about. |
| `weak-secret` | A password in `config.yml` (backup or alerts) is shorter than 6 characters, so the leak check cannot search for it. | Recommend a longer one. |
| `state-not-encrypted` | state/ is open (plain) while an age key exists. | Suggest `scripts/state.sh close` after the build. |
| `check-failed` | ansibro's acceptance test has FAIL lines. | Explain each one; fix with consent, or record it as a known issue. |
| `logo` | A logo path in `handover.yml` is not a file. | Fix the path, or leave it empty. |
| `open-warnings` | The build lists the warnings that are still open. | Make sure each was discussed. |
| `keepassxc` (warning) | A draft was built without the credentials file. | Install keepassxc-cli before the final build. |

## Needs the user (exit 3)

| Id | What to do |
| --- | --- |
| `answers`, `no-answers` | Ask the missing questions (references/questions.md), fill `handover.yml`, run again. Or build with `--draft`. |
| `no-config` | Ask which config was installed; pass it with `--config`. |
| `age-key` | state.age is encrypted and its key is not here. Ask the user for the key file, or set `ANSIBRO_KEY=/path/to/age.key`. |
| `age` | Install age: macOS `brew install age`, Linux `sudo apt-get install age`. |
| `tools` | Install mise (`curl https://mise.run \| sh`). dejavu then downloads pandoc, Typst and d2 itself. |
| `keepassxc` | Install KeePassXC: macOS `brew install --cask keepassxc`; Debian 13 or Ubuntu 26.04 `sudo apt-get install keepassxc-minimal`; Ubuntu 24.04 `sudo apt-get install keepassxc`; Fedora `sudo dnf install keepassxc`. |
| `no-state`, `no-passphrase` | There is no state/ here: this is not the folder that ran `./install.sh`. Or run `build` first. |
| `deliver` | The pack is ready. Tell the user how to hand over the file and the passphrase (SKILL.md, step 7). |

## Failed (exit 1, 2, 4, 5)

| Id | What it means | What to do |
| --- | --- | --- |
| `not-ansibro` | This folder has no `inventory.py`, `catalog.yml`, `site.yml` or `versions.yml`. | Run in the ansibro folder, or pass `--ansibro DIR`. |
| `config` | ansibro itself refused `config.yml`; its message is shown as it is. | Fix `config.yml` as the message says. |
| `ansible` | ansible could not read ansibro's settings. | Check that `.venv/` is ansibro's (run `./install.sh` once), then try again. |
| `state-guard` (exit 4) | Reading the facts would have created a password. Nothing was changed. | A dejavu bug: report it, with the dejavu and ansibro versions. |
| `state-both` | Both state/ and state.age are here. | Do not delete either: move one into a backup folder, then run again. |
| `state-open`, `state-close` | ansibro's `scripts/state.sh` failed. | After `state-close`, run `scripts/state.sh close` yourself at once. |
| `out-in-git` | The output folder is inside a git repository. | Use a folder outside every repository (the default `~/Handover/...` is). |
| `answers` (exit 2) | `handover.yml` has an unknown setting or a wrong value. | Fix the line named in the message. |
| `template` | A document template could not be rendered. | A dejavu bug: report it with the message. |
| `pandoc`, `typst`, `d2` | A PDF tool failed. | Read the message; run `doctor`. Report it if it persists. |
| `keepassxc`, `vault-check` | keepassxc-cli failed, or the credentials file did not hold the right value. | Run `doctor`; update KeePassXC to 2.7.6 or newer; build again with `--rebuild-vault`. |
| `ssh-keygen` | Making the client's SSH key failed. | Install the OpenSSH client, or use `ssh_handover: client_key`. |
| `hand-edit` | A document in `dist/` was edited by hand. | Put the wording in `handover.yml` and build again (or `--force` to overwrite). |
| `not-a-terminal` | `passphrase` runs only in a real terminal. | The user runs it in their own Terminal. Never run it yourself. |
| `leak` (exit 5) | A secret value reached a generated file. That run's files were deleted. | Remove the value (usually pasted into `handover.yml`), then build again. Never paste the value into the chat. |
