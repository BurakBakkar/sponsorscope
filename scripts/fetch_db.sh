#!/usr/bin/env bash
# Download the previous sponsorscope.db from the `db-latest` release.
# Starts fresh ONLY when the release does not exist yet; any other error fails the job,
# so a transient API failure can never publish an empty DB over the real one.
set -euo pipefail

TAG="db-latest"

if err="$(gh release view "$TAG" 2>&1 >/dev/null)"; then
  gh release download "$TAG" -p sponsorscope.db -D . --clobber
elif grep -qi "release not found" <<<"$err"; then
  echo "No $TAG release yet; starting fresh."
else
  echo "Could not check $TAG release: $err" >&2
  exit 1
fi
