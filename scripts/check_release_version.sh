#!/usr/bin/env bash
# Verify that the checked-out tree is ready to be released as X.Y.Z: the
# version fits the versioning policy, pyproject.toml and both image tags in
# docker-compose.yml carry it, CHANGELOG.md has its section, and the tag
# vX.Y.Z does not exist on origin yet. Shared by ci.yml's release-check job,
# release.yml's guard and scripts/release_start.sh, so all three agree on
# what releasable means. Does not touch git state.
#
# Usage: scripts/check_release_version.sh X.Y.Z
set -euo pipefail

VERSION="${1:?usage: check_release_version.sh X.Y.Z}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

fail() {
  echo "::error::$1" >&2
  exit 1
}

# The major is fixed at 0, the first release is 0.1.0, see
# docs/RELEASING.md section 1. This is the only place the major is checked.
[[ "$VERSION" =~ ^0\.[0-9]+\.[0-9]+$ ]] || fail "$VERSION is not a 0.Y.Z version"

project_version="$(grep -m1 '^version' pyproject.toml | sed -E 's/version = "(.*)"/\1/')"
[[ "$project_version" == "$VERSION" ]] || fail "pyproject.toml has $project_version, not $VERSION"

for service in bridge kiosk; do
  grep -qE "glados-terminal/${service}:\\\$\{TERMINAL_VERSION:-v${VERSION//./\\.}\}" docker-compose.yml \
    || fail "docker-compose.yml's $service image does not default to v$VERSION, run scripts/bump_version.sh $VERSION"
done

grep -qE "^## \[${VERSION//./\\.}\]" CHANGELOG.md || fail "CHANGELOG.md has no '## [$VERSION]' section"

if git ls-remote --exit-code --tags origin "refs/tags/v$VERSION" >/dev/null; then
  fail "tag v$VERSION already exists on origin"
fi

echo "Ready to release $VERSION."
