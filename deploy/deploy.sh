#!/usr/bin/env bash
# Build the site and rsync dist/ to a web server.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage: DEPLOY_HOST=host DEPLOY_PATH=/var/www/site deploy/deploy.sh [--dry-run]

Runs `python3 build.py`, then rsyncs dist/ to the server (with --delete, so files
removed locally are removed remotely).

Environment variables:
  DEPLOY_HOST   required  server hostname or IP (e.g. web.lan or 192.168.1.50)
  DEPLOY_PATH   required  absolute web root on the server (e.g. /var/www/danielpearson)
  DEPLOY_USER   optional  ssh user (default: your current ssh config / local user)
  DEPLOY_PORT   optional  ssh port (default: 22)

Options:
  -n, --dry-run   show what would change without transferring anything
  -h, --help      show this message

Example:
  DEPLOY_HOST=192.168.1.50 DEPLOY_USER=deploy DEPLOY_PATH=/var/www/site deploy/deploy.sh
USAGE
}

dry=()
for arg in "$@"; do
  case "$arg" in
    -h|--help) usage; exit 0 ;;
    -n|--dry-run) dry=(--dry-run) ;;
    *) echo "Unknown argument: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${DEPLOY_HOST:-}" || -z "${DEPLOY_PATH:-}" ]]; then
  echo "Error: DEPLOY_HOST and DEPLOY_PATH must be set." >&2
  echo >&2
  usage >&2
  exit 2
fi

# Refuse obviously dangerous targets, since --delete is used.
case "$DEPLOY_PATH" in
  /|/root|/home|/var|/var/www|"") echo "Error: refusing to deploy to '$DEPLOY_PATH'." >&2; exit 2 ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

echo "==> Building site"
python3 build.py

if [[ ! -f dist/index.html ]]; then
  echo "Error: dist/index.html missing after build; not deploying." >&2
  exit 1
fi

target="${DEPLOY_USER:+$DEPLOY_USER@}$DEPLOY_HOST"
port="${DEPLOY_PORT:-22}"

echo "==> Syncing dist/ to $target:$DEPLOY_PATH (port $port)"
rsync -avz --delete "${dry[@]}" \
  -e "ssh -p $port" \
  dist/ "$target:${DEPLOY_PATH%/}/"

echo "==> Done"
