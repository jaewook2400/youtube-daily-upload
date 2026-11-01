#!/bin/bash
# launchd 진입점
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
exec "$DIR/.venv/bin/python" "$DIR/uploader.py" "$@"
