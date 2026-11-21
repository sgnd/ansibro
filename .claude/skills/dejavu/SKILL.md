---
name: dejavu
description: Make the complete handover pack for a server system built with ansibro - the BAST (Berita Acara Serah Terima / Handover and Acceptance Certificate), the technical documentation, a laptop access guide per OS (Windows, macOS, Linux), and one encrypted KeePassXC file with every password - in Indonesian, English or both, as Markdown and PDF. Use it when the user asks for a BAST, berita acara, serah terima, handover documents, dokumentasi teknis, client documentation, or "how does the client access the system" for an ansibro cluster.
license: MIT
compatibility: macOS or Linux, inside an ansibro (1.2 or newer) folder where ./install.sh ran. Needs ansibro's .venv, mise (for pandoc, Typst and d2) and keepassxc-cli.
metadata:
  version: "1.0.0"
  ansibro: ">=1.2.0 <2"
---

# dejavu: the handover pack for an ansibro system

dejavu writes everything a client needs to take over a system that ansibro built:

1. **BAST** (Berita Acara Serah Terima; in English the Handover and Acceptance Certificate), ready to print and sign, with an acceptance checklist, the list of accounts and the delivered files with their SHA-256.
2. **Technical documentation**: architecture, servers and network, apps, access, passwords and how to change them, backup and restore, monitoring, runbook, security, support.
3. **Laptop access guide** per OS the client's staff use.
4. **One credentials file** (`.kdbx`, opened with KeePassXC) with every password. The documents themselves never contain a password.

The facts come from ansibro's own files and code, so they are right. You only ask the user what ansibro cannot know (client, signers, BAST number, delivery), and you never handle a password yourself.

Many users are not technical. Use plain words, ask a few questions at a time, and explain what you do.

## Never

- Never open, print, copy or grep `state/secrets/*`, `state/summary.md`, `state.age`, `state/handover/*`, `config.yml` secret fields, or the `.kdbx`. dejavu reads them itself, in memory.
- Never write a password, token or key into `handover.yml` or into the chat.
- Never run `./install.sh`, `check`, or anything that connects to the servers without asking first.
- Never send files anywhere. Sending is the user's job.
- Never edit the files in `dist/`. Put wording in `handover.yml` and build again.
- Never show the passphrase. Only the user reads it, in their own terminal.

## How to run it

Run every command in the ansibro folder (the one with `config.yml`, `.venv/` and `state/` or `state.age`), with ansibro's own Python. `SKILL` is the folder of this file (for example `~/.claude/skills/dejavu`):

```bash
.venv/bin/python "$SKILL/scripts/handover.py" COMMAND [--config FILE] [--out DIR]
```

- `--config`: the config that was installed (default `config.yml`). Ask when there are several.
- `--out`: the output folder (default `~/Handover/<domain>-<config>`). It must be outside every git repository.

| Command | What it does |
| --- | --- |
| `doctor` | Checks the folder, Python, the state, mise and keepassxc-cli. Run it first. |
| `init` | Makes the output folder and `handover.yml` (the answers), and lists what is still empty. |
| `facts` | Reads the facts from ansibro (no network, no SSH) and prints warnings. |
| `check` | Runs ansibro's own acceptance test on the servers. Read-only, but it connects: ask first. |
| `build` | Writes the documents (Markdown + PDF), the credentials file and `SHA256SUMS`. `--draft` builds with empty answers, marked DRAFT. |
| `scan` | Searches the output for secret values (`build` does this too). |
| `passphrase` | Shows the credentials file's passphrase, only in a real terminal: the user runs it, not you. |

Every line starts with `ok:`, `warning: [id]`, `needs the user: [id]` or `failed: [id]`. Exit codes: 0 ok, 1 failed, 2 wrong usage, 3 the user must act, 4 state/ changed (a bug: report it), 5 a secret reached a document (the files of that run are deleted). Every id is explained in [references/troubleshooting.md](references/troubleshooting.md).

## The steps

1. **Say what will happen**, in plain words: "I will make the handover documents from the system's own settings. No password will appear in any document; passwords go in one locked file."
2. **Doctor.** Run `doctor`. For each `needs the user` line, give the user the exact install command it shows (they may need their password). When `.venv/` is missing, this is not the folder that ran `./install.sh`: ask for the right one.
3. **Init and interview.** Run `init`, then ask the questions in [references/questions.md](references/questions.md), a few at a time, in the user's language. Write the answers into `handover.yml` in the output folder. Leave unknown answers empty (null); the documents then say "not provided", never a guess. Always ask the language: `id`, `en` or both.
4. **Facts and warnings.** Run `facts`. Go through each warning with the user (references/troubleshooting.md says what each means). For each, the user decides: fix it (a change in `config.yml` and `./install.sh`, only with their consent) or accept it. Write an accepted one into `known_issues` in the user's words.
5. **Acceptance test (ask first).** "May I run ansibro's own test now? It logs in to every app over SSH and changes nothing." If yes, run `check`. Explain any FAIL line; fix it with consent, or record it as a known issue. Without a check, the BAST says "not tested" instead of "in good condition".
6. **Build.** Run `build --draft` first, read the Markdown in `dist/` with the user (it has no secrets), correct wording in `handover.yml`, and build again. When every required answer is in, run `build` without `--draft`. The first build makes the passphrase and keeps it in `state/handover/` (encrypted with state.age when that is on).
7. **Deliver.** `build` ends with `needs the user: [deliver]`. Tell the user, in plain words:
   - Send the PDFs (and the Markdown if wanted) by email or a shared folder.
   - Hand over the `.kdbx` file on another channel (for example a USB stick in person).
   - Read the passphrase in your own Terminal with the command the build printed, and say it to the named recipient by phone or in person. Never in the same message as the file.
   - Print the BAST in the agreed number of copies. At the handover meeting, go through Annex 1 (the acceptance checklist) together, then sign. Add the meterai when chosen.
   - Keep a copy of the signed scan.
8. **After.** The client changes every password within the agreed days (the technical documentation, chapter 6, says how for each one). A later re-issue (final handover, a change) raises `document.version` and builds again.

## Good to know

- Re-running `build` is safe. It keeps the same passphrase and the same credentials file unless the passwords changed (`--rebuild-vault` and `--new-passphrase` force it).
- Both languages give two full sets and one shared credentials file. The Indonesian BAST says the Indonesian version prevails.
- When ansibro is newer than this skill was tested with, `facts` warns `ansibro-untested-version`: the documents are still made, but check them carefully.
- The meterai, PIHAK PERTAMA/KEDUA and the legal wording follow common Indonesian practice; they are not legal advice. When in doubt, the user asks their legal team.
