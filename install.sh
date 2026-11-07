#!/usr/bin/env bash
# Usage: ./install.sh [config.yml] [extra ansible-playbook options]
#   ./install.sh                     uses config.yml
#   ./install.sh prod.yml -v         another config file, plus an ansible-playbook option
#
# If a bundle/ folder is here (made by build-bundle.sh), it installs offline:
# Ansible, packages and images all come from the bundle.
set -euo pipefail

case "${1:-}" in
  -h|--help) sed -n '2,7p' "$0" | cut -c3-; exit 0 ;;
esac

# The first argument is the config file, unless it is an option like -v.
config=config.yml
if [ "$#" -gt 0 ] && [ "${1#-}" = "$1" ]; then
  config="$1"
  shift
fi
if [ ! -f "$config" ]; then
  echo "error: $config not found. Copy an example and edit it, like:" >&2
  echo "  cp examples/swarm-1-server.yml $config   (all examples: see README.md)" >&2
  exit 1
fi
# Full path, so it still works after we change folder below.
ANSIBRO_CONFIG="$(cd "$(dirname "$config")" && pwd)/$(basename "$config")"
export ANSIBRO_CONFIG

cd "$(dirname "$0")"

# Ansible (ansible-core 2.21, see requirements.txt) works with Python 3.12, 3.13 and 3.14.
# Older is too old, and 3.15 breaks it. When requirements.txt gets a newer Ansible, check this again.
# python_ok tells if the Python program given is there, works, and is one of these versions.
python_ok() {
  [ -n "$1" ] && "$1" -c 'import sys; sys.exit(not (3, 12) <= sys.version_info[:2] <= (3, 14))' 2>/dev/null
}

# find_python looks for a Python 3.12 to 3.14 and keeps it in $python.
# On a Mac "python3" is often Apple's old 3.9, so we also try python3.14, 3.13 and 3.12,
# in PATH and in Homebrew's folders, and then ask uv and mise if they are installed.
python=
find_python() {
  local name try
  for name in python3 python3.14 python3.13 python3.12; do
    for try in "$(command -v "$name" || true)" "/opt/homebrew/bin/$name" "/usr/local/bin/$name"; do
      if python_ok "$try"; then python=$try; return 0; fi
    done
  done
  if command -v uv >/dev/null; then
    try=$(uv python find '>=3.12,<3.15' 2>/dev/null || true)
    if python_ok "$try"; then python=$try; return 0; fi
  fi
  if command -v mise >/dev/null; then
    try=$(mise which python3 2>/dev/null || true)
    if python_ok "$try"; then python=$try; return 0; fi
  fi
  return 1
}

# install_python installs Python 3.13 on a Mac, with a tool that needs no sudo:
# Homebrew if it is there (also when this shell's PATH lacks it), else uv, else mise. Then it looks again.
install_python() {
  local try brew
  [ "$(uname -s)" = Darwin ] || return 1
  brew=$(command -v brew || true)
  for try in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -z "$brew" ] && [ -x "$try" ]; then brew=$try; fi
  done
  if [ -n "$brew" ]; then
    echo "Python 3.12 to 3.14 not found. Installing it: brew install python@3.13"
    "$brew" install python@3.13 || return 1
  elif command -v uv >/dev/null; then
    echo "Python 3.12 to 3.14 not found. Installing it: uv python install 3.13"
    uv python install 3.13 || return 1
  elif command -v mise >/dev/null; then
    echo "Python 3.12 to 3.14 not found. Installing it: mise install python@3.13"
    mise install python@3.13 || return 1
    try=$(mise where python@3.13 2>/dev/null || true)/bin/python3
    if python_ok "$try"; then python=$try; return 0; fi
  else
    return 1
  fi
  find_python
}

offline=false
[ -f bundle/info.yml ] && offline=true

# Offline: this machine must match the bundle (its packages are for one Ubuntu version, on amd64).
if $offline; then
  bundle_ubuntu=$(sed -n 's/^ubuntu: "\(.*\)"/\1/p' bundle/info.yml)
  here_ubuntu=$(sed -n 's/^VERSION_ID="\(.*\)"/\1/p' /etc/os-release 2>/dev/null || true)
  here_arch=$(dpkg --print-architecture 2>/dev/null || true)
  if [ "$here_ubuntu" != "$bundle_ubuntu" ] || [ "$here_arch" != amd64 ]; then
    echo "error: this bundle is for Ubuntu $bundle_ubuntu amd64, this machine is ${here_ubuntu:-not Ubuntu} ${here_arch}." >&2
    echo "  Run the offline install on the first manager, or build a matching bundle:" >&2
    echo "  ./build-bundle.sh <ubuntu version>" >&2
    exit 1
  fi
fi

# Install python3-venv with apt, from the internet or from the bundle.
install_venv_package() {
  if ! command -v apt-get >/dev/null; then
    echo "error: Python's venv is missing. On a Mac: brew install python@3.13, then run ./install.sh again." >&2
    exit 1
  fi
  if $offline; then
    mkdir -p bundle/debs bundle/apt/lists/partial bundle/apt/sources.d
    tar -C bundle/debs -xf bundle/debs.tar
    echo "deb [trusted=yes] file:$PWD/bundle/debs ./" > bundle/apt/sources.list
    cat > bundle/apt/apt.conf <<EOF
Dir::Etc::SourceList "$PWD/bundle/apt/sources.list";
Dir::Etc::SourceParts "$PWD/bundle/apt/sources.d";
Dir::State::Lists "$PWD/bundle/apt/lists";
EOF
    export APT_CONFIG="$PWD/bundle/apt/apt.conf"
  fi
  sudo --preserve-env=APT_CONFIG apt-get update -qq
  sudo --preserve-env=APT_CONFIG apt-get install -y -qq python3-venv
}

# Install Ansible in .venv. A copy of requirements.txt in .venv shows what is installed,
# so this only runs again when requirements.txt changes.
venv=.venv
# A .venv made with a Python that is too old or too new, or was removed since, does not work. Make it again.
if [ -d "$venv" ] && ! python_ok "$venv/bin/python"; then
  echo "The Python in $venv is broken, or not Python 3.12 to 3.14. Making $venv again."
  rm -rf "$venv"
fi
if ! cmp -s requirements.txt "$venv/requirements.txt"; then
  if ! find_python && ! install_python; then
    echo "error: Python 3.12, 3.13 or 3.14 is needed, found: $(python3 --version 2>&1)" >&2
    echo "  On a Mac: brew install python@3.13 (get brew at https://brew.sh)." >&2
    echo "  On Ubuntu: sudo apt install python3 python3-venv." >&2
    echo "  Then run ./install.sh again." >&2
    exit 1
  fi
  echo "Using $python ($("$python" --version 2>&1)) for $venv."
  "$python" -m venv "$venv" 2>/dev/null || { install_venv_package && "$python" -m venv "$venv"; }
  if $offline; then
    "$venv/bin/pip" install --quiet --no-index --find-links bundle/python -r requirements.txt
  else
    "$venv/bin/pip" install --quiet -r requirements.txt
  fi
  cp requirements.txt "$venv/requirements.txt"
fi

if $offline; then
  (cd bundle/collections && "../../$venv/bin/ansible-galaxy" collection install -r requirements.yml -p ../../.collections >/dev/null)
else
  "$venv/bin/ansible-galaxy" collection install -r requirements.yml >/dev/null
fi

export PATH="$PWD/$venv/bin:$PATH"

# Check config.yml first, so a mistake stops here with a clear message.
# A real run also checks for values left from config.example.yml (a --syntax-check does not).
check=(--list --ready)
case " $* " in *" --syntax-check "*) check=(--list) ;; esac
if ! "$venv/bin/python" inventory.py "${check[@]}" >/dev/null; then
  exit 1
fi

# state/ holds the passwords. If it is kept encrypted (see scripts/state.sh), open it now
# and close it again when the install ends, also when it fails.
scripts/state.sh open
trap 'scripts/state.sh close' EXIT

# Only you may read state/ (passwords, and database dumps during a restore), from the start of the run.
if [ "${check[*]}" = "--list --ready" ]; then
  mkdir -p state
  chmod 700 state
fi

ansible-playbook site.yml "$@"
