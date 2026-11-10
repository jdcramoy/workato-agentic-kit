#!/usr/bin/env bash
# install-wt — standalone installer for wt (Workato Toolbox), no kit needed.
# wt is a single-file Python3 CLI (stdlib only) over the Workato Developer API:
# manifests, packages, recipe lifecycle, jobs, lookup-table writes,
# connections CRUD, project properties, MCP Apps.
#
# Usage:
#   git clone https://github.com/Workato-All/workato-agentic-kit.git
#   bash workato-agentic-kit/bin/install-wt.sh
#   # or pipe it:
#   curl -fsSL https://raw.githubusercontent.com/Workato-All/workato-agentic-kit/main/bin/install-wt.sh | bash
set -euo pipefail

BIN="$HOME/.local/bin"
mkdir -p "$BIN"
SRC="$(dirname "$0")/wt"

if [ -f "$SRC" ]; then
  cp "$SRC" "$BIN/wt"                       # from a cloned kit
else
  curl -fsSL "https://raw.githubusercontent.com/Workato-All/workato-agentic-kit/main/bin/wt" -o "$BIN/wt"
fi
chmod +x "$BIN/wt"

python3 -c "import py_compile,sys; py_compile.compile(sys.argv[1], doraise=True)" "$BIN/wt"
echo "wt installed: $BIN/wt"

case ":$PATH:" in
  *":$BIN:"*) : ;;
  *) echo "NOTE: $BIN is not on your PATH — add it to your shell profile:"; echo "  export PATH=\"$BIN:\$PATH\"" ;;
esac

echo
echo "Auth (pick one):"
echo "  1. export WORKATO_API_TOKEN=<token from YOUR Workato workspace>"
echo "  2. Install Workato's CLI via pipx and log in once (wt reads its keychain entry):"
echo "     pipx install workato-platform-cli && workato login"
echo
echo "Region/profile: wt reads ~/.workato/profiles when present; defaults to the US host."
echo "Smoke test:  wt api GET /api/users/me"
