#!/usr/bin/env bash
# Write the hashes in requirements.txt again, for the versions pinned there.
#
# Usage: scripts/hash-requirements.sh   (needs internet: it asks PyPI)
#
# requirements.txt lists each Python package with its version and the sha256 of every file PyPI has
# for that version (wheels for each Python and system, and the source). pip then refuses a file that
# is not one of these (install.sh uses --require-hashes). Dependabot changes a version and its hashes
# together. Run this after you change a version by hand. It keeps the comments and the order.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - requirements.txt <<'EOF'
import json, re, sys, urllib.request

path = sys.argv[1]
text = open(path).read().replace("\\\n", " ")  # one line per package, without the "\" line breaks
out = []
for line in text.splitlines():
    if not line.strip() or line.lstrip().startswith("#"):
        out.append(line.rstrip())
        continue
    m = re.match(r"\s*([A-Za-z0-9._-]+)==([^\s;#]+)", line)
    if not m:
        sys.exit(f"error: cannot read this line of {path}: {line}")
    name, version = m.groups()
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as r:
        files = json.load(r)["urls"]
    hashes = sorted({f["digests"]["sha256"] for f in files})
    if not hashes:
        sys.exit(f"error: PyPI has no files for {name} {version}")
    out.append(f"{name}=={version} \\")
    out += [f"    --hash=sha256:{h}" + (" \\" if i < len(hashes) - 1 else "") for i, h in enumerate(hashes)]
    print(f"{name}=={version}: {len(hashes)} files")
open(path, "w").write("\n".join(out) + "\n")
EOF
