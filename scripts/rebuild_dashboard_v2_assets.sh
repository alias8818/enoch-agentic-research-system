#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root/dashboard"

npm ci
npm run build

echo "Rebuilt dashboard V2 assets under enoch_control_plane/control_plane/dashboard_v2/"
echo "Commit those files with your dashboard source changes."
