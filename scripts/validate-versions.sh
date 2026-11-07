#!/usr/bin/env bash
# Checks that every version pinned in versions.yml still exists:
#   - each Docker image digest, with an amd64 build, and that its tag exists (a note if the tag
#     points to a newer build)
#   - the Ubuntu image digests that build-bundle.sh uses
#   - each Docker apt package, for Ubuntu 24.04 (noble) and 26.04 (resolute), on amd64
#   - Docker's apt signing key still has the pinned sha256
# Needs: yq, docker (buildx), curl.
set -euo pipefail
cd "$(dirname "$0")/.."

failed=0

echo "== Docker images"
for name in $(yq '.images | keys | .[]' versions.yml); do
  repo=$(yq ".images[\"$name\"].repo" versions.yml)
  tag=$(yq ".images[\"$name\"].tag" versions.yml)
  digest=$(yq ".images[\"$name\"].digest" versions.yml)
  platforms=$(docker buildx imagetools inspect "$repo@$digest" 2>/dev/null | grep 'Platform:' || true)
  # The digest the tag points to now (the first "Digest:" line).
  tag_digest=$(docker buildx imagetools inspect "$repo:$tag" 2>/dev/null | awk '/^Digest:/ {print $2; exit}' || true)
  if ! grep -q "linux/amd64" <<< "$platforms"; then
    echo "MISSING $name ($repo@$digest) for amd64"
    failed=1
  elif [ -z "$tag_digest" ]; then
    echo "MISSING $name: the tag $repo:$tag does not exist"
    failed=1
  elif [ "$tag_digest" != "$digest" ]; then
    # Normal for official images: they build the same version again (OS fixes). Only a note, but
    # look at it when you change the tag: the digest must be one of that tag's builds.
    echo "note $name: $repo:$tag points to a newer build ($tag_digest) than the pinned digest"
  else
    echo "ok $name"
  fi
done

echo "== Ubuntu images (build-bundle.sh builds the bundle in them)"
for version in $(yq '.ubuntu_images | keys | .[]' versions.yml); do
  digest=$(yq ".ubuntu_images[\"$version\"]" versions.yml)
  # Only the digest: the tag gets a new build every few weeks.
  # Saved first: "grep -q" stops early, and with pipefail the cut-off pipe would count as an error.
  platforms=$(docker buildx imagetools inspect "docker.io/library/ubuntu@$digest" 2>/dev/null | grep 'Platform:' || true)
  if grep -q 'linux/amd64' <<< "$platforms"; then
    echo "ok ubuntu $version"
  else
    echo "MISSING ubuntu $version (docker.io/library/ubuntu@$digest) for amd64"
    failed=1
  fi
done

echo "== Docker apt packages"
for ubuntu in noble resolute; do
  # One line per package: "name version"
  available=$(curl -fsSL "https://download.docker.com/linux/ubuntu/dists/$ubuntu/stable/binary-amd64/Packages" \
    | awk '/^Package: /{p=$2} /^Version: /{print p, $2}')
  for spec in $(yq '.docker_packages[]' versions.yml); do
    name=${spec%%=*}
    version=${spec#*=}
    version=${version%\*}
    if ! grep -q "^$name $version" <<< "$available"; then
      echo "MISSING $name $version for $ubuntu"
      failed=1
    fi
  done
  echo "ok $ubuntu"
done

echo "== Docker apt key"
key_sha=$(yq '.docker_apt_key_sha256' versions.yml)
live_sha=$(curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sha256sum | cut -d' ' -f1)
if [ "$live_sha" = "$key_sha" ]; then
  echo "ok docker_apt_key_sha256"
else
  echo "CHANGED Docker's apt key: it is now $live_sha, versions.yml has $key_sha"
  echo "  Check https://docs.docker.com/engine/install/ubuntu/ before you change the pin."
  failed=1
fi

echo "== k3s"
k3s_version=$(yq '.k3s.version' versions.yml)
sums=$(curl -fsSL "https://github.com/k3s-io/k3s/releases/download/${k3s_version/+/%2B}/sha256sum-amd64.txt")
if grep -q "^$(yq '.k3s.binary' versions.yml)  k3s$" <<< "$sums" &&
   grep -q "^$(yq '.k3s.images' versions.yml)  k3s-airgap-images-amd64.tar.zst$" <<< "$sums"; then
  echo "ok $k3s_version"
else
  echo "WRONG k3s $k3s_version sha256"
  failed=1
fi

exit $failed
