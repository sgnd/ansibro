#!/usr/bin/env bash
# Runs inside an Ubuntu container (amd64). build-bundle.sh starts it.
# /src = this project (read only), /out = the bundle folder.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
# shellcheck source=/dev/null
. /etc/os-release

echo "- tools"
apt-get update -qq
apt-get install -y -qq ca-certificates curl python3-venv apt-utils >/dev/null

echo "- Docker apt repository"
install -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
# The key must match the sha256 pinned in versions.yml (docker_apt_key_sha256).
key_sha=$(awk '/^docker_apt_key_sha256:/ {print $2}' /src/versions.yml)
if ! echo "$key_sha  /etc/apt/keyrings/docker.asc" | sha256sum -c --quiet -; then
  echo "error: Docker's apt key does not match docker_apt_key_sha256 in versions.yml." >&2
  echo "Check https://docs.docker.com/engine/install/ubuntu/ for a new key before you change the pin." >&2
  exit 1
fi
echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -qq

echo "- Python packages and Ansible collections"
python3 -m venv /tmp/venv
# --require-hashes: only files whose sha256 is in requirements.txt.
/tmp/venv/bin/pip download -q --require-hashes -r /src/requirements.txt -d /out/python
/tmp/venv/bin/pip install -q --require-hashes --no-index --find-links /out/python -r /src/requirements.txt
# Galaxy sometimes drops the connection, so try 3 times.
for try in 1 2 3; do
  /tmp/venv/bin/ansible-galaxy collection download -r /src/requirements.yml -p /out/collections >/dev/null && break
  [ "$try" = 3 ] && exit 1
  echo "  Galaxy failed, trying again"
done

echo "- apt packages"
# List: base packages from roles/common, Docker packages from versions.yml, and what the installer needs.
# Docker versions like "5:29.9.2-1*" become the exact version from the repo.
# Saved in a variable first, so set -e stops here when the Python part fails.
package_list=$(/tmp/venv/bin/python - <<'EOF'
import subprocess, yaml
versions = yaml.safe_load(open("/src/versions.yml"))
common = yaml.safe_load(open("/src/roles/common/defaults/main.yml"))
wanted = common["common_packages"] + ["python3-venv", "python3-apt", "openssl"]
for spec in versions["docker_packages"]:
    name, version = spec.split("=")
    madison = subprocess.run(["apt-cache", "madison", name], capture_output=True, text=True).stdout
    found = [line.split("|")[1].strip() for line in madison.splitlines()
             if line.split("|")[1].strip().startswith(version.rstrip("*"))]
    if not found:
        raise SystemExit(f"{name} {version} not found in the Docker apt repo")
    wanted.append(f"{name}={found[0]}")
print(" ".join(wanted))
EOF
)
read -ra packages <<< "$package_list"
if [ "${#packages[@]}" = 0 ]; then
  echo "error: the list of apt packages is empty" >&2
  exit 1
fi
# An empty package status makes apt download every dependency, even ones this container already has.
mkdir -p /tmp/debs/partial
touch /tmp/empty-status
apt-get install -y -qq --download-only \
  -o Dir::State::status=/tmp/empty-status -o Dir::Cache::archives=/tmp/debs "${packages[@]}" >/dev/null
cd /tmp/debs
rm -rf partial lock
apt-ftparchive packages . > Packages 2>/dev/null
tar -cf /out/debs.tar .

echo "- image list"
/tmp/venv/bin/python - > /out/images.txt <<'EOF'
import yaml
for name, image in yaml.safe_load(open("/src/versions.yml"))["images"].items():
    print(name, image["repo"], image["tag"], image["digest"])
EOF

echo "- k3s version"
# One line: version, sha256 of the program, sha256 of its images (for orchestrator: k3s).
/tmp/venv/bin/python - > /out/k3s.txt <<'EOF'
import yaml
k3s = yaml.safe_load(open("/src/versions.yml"))["k3s"]
print(k3s["version"], k3s["binary"], k3s["images"])
EOF

cat > /out/info.yml <<EOF
ubuntu: "$VERSION_ID"
EOF
echo "- $(tar -tf /out/debs.tar | grep -c '\.deb$') apt packages"

# Give the files to the user who runs build-bundle.sh.
chown -R "$OWNER" /out
