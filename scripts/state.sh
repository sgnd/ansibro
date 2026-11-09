#!/usr/bin/env bash
# Keep state/ (passwords, keys, summary) encrypted on disk, as state.age.
#
# On by default: the first ./install.sh makes the key ~/.config/ansibro/age.key (scripts/state.sh init).
# Keep a copy of that key somewhere safe (a password manager): without it state.age cannot be opened.
# To keep state/ unencrypted instead: ANSIBRO_PLAIN_STATE=1 ./install.sh (before the key exists).
#
# install.sh opens state.age before it runs and closes it again at the end. By hand:
#   scripts/state.sh open     state.age -> state/ (to read a password)
#   scripts/state.sh close    state/ -> state.age
# Another key file: ANSIBRO_KEY=/path/to/age.key scripts/state.sh open
set -euo pipefail
cd "$(dirname "$0")/.."

# HOME is not set when this runs from a service or cron; ~ then comes from the user list.
home="${HOME:-$(cd ~ && pwd)}"
key="${ANSIBRO_KEY:-$home/.config/ansibro/age.key}"

# Homebrew's age, also when this shell's PATH lacks Homebrew.
for dir in /opt/homebrew/bin /usr/local/bin; do
  case ":$PATH:" in
    *":$dir:"*) ;;
    *) if [ -x "$dir/age" ]; then PATH="$PATH:$dir"; fi ;;
  esac
done

# init: make the key, so state/ is kept encrypted from now on. Nothing to do when there is a key or
# state.age already, or with ANSIBRO_PLAIN_STATE=1. Without age it only warns: the install goes on.
if [ "${1:-}" = init ]; then
  if [ -n "${ANSIBRO_PLAIN_STATE:-}" ] || [ -f "$key" ] || [ -f state.age ]; then
    exit 0
  fi
  if ! command -v age-keygen >/dev/null && [ "$(uname -s)" = Darwin ]; then
    for brew in "$(command -v brew || true)" /opt/homebrew/bin/brew /usr/local/bin/brew; do
      if [ -n "$brew" ] && [ -x "$brew" ]; then
        echo "Installing age, to keep state/ encrypted: brew install age"
        "$brew" install age >/dev/null || true
        PATH="$PATH:$(dirname "$brew")"
        break
      fi
    done
  fi
  if ! command -v age-keygen >/dev/null; then
    echo "WARNING: state/ (every password) stays readable on this computer, because age is not installed." >&2
    echo "  Install it (sudo apt install age, or brew install age) and run ./install.sh again: it then keeps" >&2
    echo "  state/ encrypted. (To keep it unencrypted and stop this warning: ANSIBRO_PLAIN_STATE=1.)" >&2
    exit 0
  fi
  mkdir -p "$(dirname "$key")"
  (umask 077 && age-keygen -o "$key" 2>/dev/null)
  echo "==> state/ is kept encrypted from now on (state.age), with the key $key."
  echo "    Save a copy of this key in a password manager now: without it state.age (every password) cannot be opened."
  echo "    To read a password: scripts/state.sh open, and scripts/state.sh close when you are done."
  exit 0
fi

# Nothing to do when encryption is off (no key and no state.age).
if [ ! -f "$key" ] && [ ! -f state.age ]; then
  exit 0
fi
if ! command -v age >/dev/null; then
  echo "error: state is encrypted with age, but age is not installed (brew install age, or sudo apt install age)" >&2
  exit 1
fi
if [ ! -f "$key" ]; then
  echo "error: state.age is encrypted, but the key $key is missing (or set ANSIBRO_KEY)" >&2
  exit 1
fi

case "${1:-}" in
  open)
    [ -f state.age ] || exit 0
    if [ -d state ]; then
      echo "error: both state/ and state.age are here. Do not delete either: they hold your passwords." >&2
      echo "  Move one of them to a backup folder, then run this again." >&2
      exit 1
    fi
    age -d -i "$key" state.age | tar -xf -
    rm state.age
    ;;
  close)
    [ -d state ] || exit 0
    tar -cf - state | age -e -i "$key" -o state.age.new
    mv state.age.new state.age
    rm -rf state
    ;;
  *)
    echo "usage: scripts/state.sh init|open|close" >&2
    exit 1
    ;;
esac
