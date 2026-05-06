#!/usr/bin/env bash
set -euo pipefail

cat <<'JSON'
{"ok":true,"action":"disabled","reason":"legacy Notion sync has been removed from the runtime path; use Supabase-native ideas via /control/intake/ideas"}
JSON

case "${ENOCH_ENABLE_LEGACY_NOTION_SYNC:-0}" in
  1|true|TRUE|yes|YES|on|ON)
    echo "legacy Notion sync is intentionally unavailable in the Supabase-native runtime" >&2
    ;;
esac

exit 0
