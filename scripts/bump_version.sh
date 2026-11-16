#!/usr/bin/env bash
# Bump the terminal to one version: [project].version in pyproject.toml and
# the default image tag of both services in docker-compose.yml, so a device
# that checks out vX.Y.Z pulls the vX.Y.Z images. Idempotent - running it
# again with the same version changes nothing. Does NOT touch git.
#
# Usage: scripts/bump_version.sh X.Y.Z
set -euo pipefail

VERSION="${1:?usage: bump_version.sh X.Y.Z}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "not a X.Y.Z version: $VERSION" >&2; exit 1; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

poetry version "$VERSION"
sed -i -E "s/(\\\$\{TERMINAL_VERSION:-)v[0-9]+\.[0-9]+\.[0-9]+\}/\1v${VERSION}}/" docker-compose.yml

echo "pyproject.toml:     $(poetry version -s)"
echo "docker-compose.yml: $(grep -oE 'TERMINAL_VERSION:-v[0-9.]+' docker-compose.yml | sort -u | sed 's/.*:-v//' | paste -sd ' ')"
