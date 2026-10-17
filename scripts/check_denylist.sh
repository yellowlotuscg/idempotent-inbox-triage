#!/usr/bin/env bash
set -u -o pipefail

DENYLIST=".github/denylist.txt"
if [[ ! -f "$DENYLIST" ]]; then
  echo "No .github/denylist.txt present; deny-list check skipped."
  exit 0
fi

found=0
while IFS= read -r file; do
  [[ "$file" == "$DENYLIST" ]] && continue
  [[ -z "$file" ]] && continue
  while IFS= read -r term; do
    [[ -z "$term" ]] && continue
    if grep -Fni -- "$term" "$file"; then
      found=1
    fi
  done < "$DENYLIST"
done < <(git ls-files)

if [[ "$found" -ne 0 ]]; then
  echo "deny-list check failed"
  exit 1
fi
echo "deny-list check passed"
