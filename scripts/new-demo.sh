#!/usr/bin/env bash
# Copy the op-amp demo into its own git repo (opencode matches permission paths from the git root).
# Usage: scripts/new-demo.sh [dest-dir]   (default: .opencode-home/projects/opamp-demo; recreated each run)
set -euo pipefail

FUEL_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$FUEL_HOME/.opencode-home/projects/opamp-demo}"

rm -rf "$DEST"
mkdir -p "$(dirname "$DEST")"
cp -r "$FUEL_HOME/examples/opamp-demo" "$DEST"
rm -rf "$DEST/.opencode" "$DEST/.rocket"
mkdir -p "$DEST/results"
git -C "$DEST" init -q
git -C "$DEST" add -A
git -C "$DEST" -c user.name=rocketeda -c user.email=rocketeda@localhost commit -q -m "Starting point: under-designed op-amp"
echo "$DEST"
