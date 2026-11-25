#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYINSTALLER_BIN=""
if command -v pyinstaller >/dev/null 2>&1; then
  PYINSTALLER_BIN="$(command -v pyinstaller)"
elif [[ -x "/opt/homebrew/bin/pyinstaller" ]]; then
  PYINSTALLER_BIN="/opt/homebrew/bin/pyinstaller"
else
  echo "Error: pyinstaller が見つかりません。pip install pyinstaller でインストールしてください。" >&2
  exit 1
fi

PY_BIN="$(head -n 1 "$PYINSTALLER_BIN" | sed 's/^#!//')"
EXTRA_ARGS=()
if [[ -n "$PY_BIN" && -x "$PY_BIN" ]]; then
  if "$PY_BIN" -c "import certifi" >/dev/null 2>&1; then
    EXTRA_ARGS+=(--collect-data certifi)
  fi
fi

"$PYINSTALLER_BIN" \
  --windowed \
  --onedir \
  --name HttpPostTool \
  --noconfirm \
  --clean \
  "${EXTRA_ARGS[@]}" \
  http_post_tool.py

echo "Build complete: $SCRIPT_DIR/dist/HttpPostTool.app"
