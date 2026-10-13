#!/usr/bin/env bash
# Upload sponsorscope.db to the rolling `db-latest` release and keep 7 dated snapshots.
set -euo pipefail

DB="${1:-sponsorscope.db}"
TAG="db-latest"
KEEP=7

uv run sponsorscope check-db --db "$DB"

if ! gh release view "$TAG" >/dev/null 2>&1; then
  gh release create "$TAG" --title "Database snapshot" \
    --notes "Rolling SQLite snapshot written by the nightly workflow." --latest=false
fi

stamp="$(date -u +%Y-%m-%d)"
cp "$DB" "sponsorscope-$stamp.db"
gh release upload "$TAG" "$DB" "sponsorscope-$stamp.db" --clobber

gh release view "$TAG" --json assets -q '.assets[].name' \
  | grep -E '^sponsorscope-[0-9]{4}-[0-9]{2}-[0-9]{2}\.db$' | sort | head -n -"$KEEP" \
  | while read -r old; do gh release delete-asset "$TAG" "$old" -y; done
