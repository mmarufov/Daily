#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Conductor layout: conductor/workspaces/<repo>/<name> → conductor/repos/<repo>
WORKSPACES_DIR="$(dirname "$PROJECT_ROOT")"
REPO_NAME="$(basename "$WORKSPACES_DIR")"
CONDUCTOR_ROOT="$(cd "$WORKSPACES_DIR/../.." 2>/dev/null && pwd || echo "")"
CONDUCTOR_REPO_ROOT="${CONDUCTOR_ROOT:+$CONDUCTOR_ROOT/repos/$REPO_NAME}"

cd "$PROJECT_ROOT"

echo "==> Setting up Daily workspace in $PROJECT_ROOT"

# ── 1. Copy env / config files ────────────────────────────────────────────────

copy_file() {
  local src_rel="$1"   # relative path to look for (e.g. backend/.env)
  local dst="$2"       # destination path relative to PROJECT_ROOT

  # Priority 1: Conductor root repo (repos/<name>/<src_rel>) — source of truth
  if [ -n "$CONDUCTOR_REPO_ROOT" ] && [ -f "$CONDUCTOR_REPO_ROOT/$src_rel" ]; then
    mkdir -p "$(dirname "$dst")"
    cp "$CONDUCTOR_REPO_ROOT/$src_rel" "$dst"
    echo "    Synced $dst from $CONDUCTOR_REPO_ROOT (Conductor root repo)"
    return
  fi

  # Already exists from a previous run
  if [ -f "$dst" ]; then
    echo "    $dst already exists, keeping it (no root repo to sync from)"
    return
  fi

  # Fallback: any sibling Conductor workspace that has it
  for sibling in "$WORKSPACES_DIR"/*/; do
    sibling="${sibling%/}"
    if [ "$sibling" != "$PROJECT_ROOT" ] && [ -f "$sibling/$src_rel" ]; then
      mkdir -p "$(dirname "$dst")"
      cp "$sibling/$src_rel" "$dst"
      echo "    Copied $dst from $sibling (sibling workspace)"
      return
    fi
  done

  # Last resort: create from example
  local example="${dst}.example"
  if [ -f "$example" ]; then
    cp "$example" "$dst"
    echo "    WARNING: Created $dst from $example (fill in your secrets!)"
  else
    echo "    ERROR: No source found for $dst and no .example available"
  fi
}

copy_file "backend/.env" "backend/.env"
copy_file "Daily/GoogleService-Info.plist" "Daily/GoogleService-Info.plist"

# ── 2. Python venv + dependencies ─────────────────────────────────────────────

VENV_DIR="$PROJECT_ROOT/backend/venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "==> Creating Python virtual environment..."
  # psycopg 3.2+ requires Python 3.10+; search PATH and common Homebrew locations
  PYTHON_BIN=""
  for candidate in \
    python3.13 python3.12 python3.11 python3.10 \
    /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 \
    /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3.10 \
    /usr/local/bin/python3.13 /usr/local/bin/python3.12 \
    /usr/local/bin/python3.11 /usr/local/bin/python3.10; do
    if command -v "$candidate" &>/dev/null || [ -x "$candidate" ]; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
  if [ -z "$PYTHON_BIN" ]; then
    echo "    Python 3.10+ not found — installing via Homebrew..."
    BREW="/opt/homebrew/bin/brew"
    [ -x "$BREW" ] || BREW="/usr/local/bin/brew"
    "$BREW" install python@3.12
    PYTHON_BIN="/opt/homebrew/bin/python3.12"
    [ -x "$PYTHON_BIN" ] || PYTHON_BIN="/usr/local/bin/python3.12"
  fi
  echo "    Using $PYTHON_BIN ($(${PYTHON_BIN} --version))"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

echo "==> Installing Python dependencies..."
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.txt

# ── 3. Create .context directory ──────────────────────────────────────────────

if [ ! -d ".context" ]; then
  mkdir -p .context
  touch .context/notes.md .context/todos.md
  echo "==> Created .context/ directory"
fi

# ── 4. Check required env vars in backend/.env ────────────────────────────────

echo "==> Checking backend env vars..."
MISSING=()
for key in NEON_DATABASE_URL NEWS_API_KEY OPENAI_API_KEY; do
  val="$(grep "^${key}=" backend/.env 2>/dev/null | cut -d= -f2-)"
  if [ -z "$val" ] || [[ "$val" == *"your-"* ]] || [[ "$val" == *"example"* ]]; then
    MISSING+=("$key")
  fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
  echo "    WARNING: These keys are missing or placeholder in backend/.env:"
  for key in "${MISSING[@]}"; do
    echo "      - $key"
  done
  echo "    Backend will not work until these are set."
else
  echo "    All required backend keys present"
fi

# ── 5. Check iOS GoogleService-Info.plist ─────────────────────────────────────

if [ -f "Daily/GoogleService-Info.plist" ]; then
  if grep -qE "YOUR_|your-|example\.com" "Daily/GoogleService-Info.plist" 2>/dev/null; then
    echo "    WARNING: Daily/GoogleService-Info.plist still contains placeholder values"
    echo "      Download the real file from Firebase Console and replace it"
  else
    echo "    Daily/GoogleService-Info.plist looks configured"
  fi
else
  echo "    WARNING: Daily/GoogleService-Info.plist missing — iOS Firebase will not work"
fi

echo ""
echo "==> Setup complete!"
echo "    Workspace ready at $PROJECT_ROOT"
echo "    Run: cd backend && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload"
