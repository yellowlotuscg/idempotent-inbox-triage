#!/usr/bin/env bash
set -euo pipefail

INFRA_DIR="${1:?infra directory is required}"
ROOT_DIR="$(cd "$INFRA_DIR/.." && pwd)"
PACKAGE_DIR="$INFRA_DIR/.terraform-build/package"
rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR/rules"
python3 -m pip install --disable-pip-version-check --no-compile -q -r "$ROOT_DIR/requirements.txt" -t "$PACKAGE_DIR"
cp -R "$ROOT_DIR/src/triage" "$PACKAGE_DIR/triage"
cp "$ROOT_DIR/rules/rules.yaml" "$PACKAGE_DIR/rules/rules.yaml"
