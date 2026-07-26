#!/usr/bin/env bash
#
# Purge the leaked Gemini API key from the whole of git history.
#
# The key was committed in 87315c3 and carried into 10b7030. Commit 3f268fc
# replaced it with "KEY HERE" in the *working tree* only - the original blobs
# are still reachable, so the key remains readable via:
#
#     git show 87315c3:data_scout.py
#
# This script rewrites every commit so the literal is replaced with
# "GEMINI_API_KEY_REDACTED" everywhere it appears.
#
# ---------------------------------------------------------------------------
# READ THIS FIRST
#
#  1. Rewriting history changes every commit SHA after the first affected one.
#     Anyone with a clone must re-clone or hard-reset. Open PRs may need reopening.
#
#  2. Rewriting does NOT un-leak the key. It was public on GitHub; assume it was
#     harvested. REVOKE IT FIRST at https://aistudio.google.com/apikey - that is
#     the step that actually stops abuse. This script is cleanup, not remediation.
#
#  3. GitHub keeps unreferenced objects reachable for a while and may still serve
#     them via the API by SHA. After pushing, open a support request asking for
#     garbage collection if you need the old objects gone immediately:
#     https://support.github.com/contact
#
# Usage:
#     ./scripts/purge_key_from_history.sh            # dry run: report only
#     ./scripts/purge_key_from_history.sh --apply    # rewrite locally
#     # then, once you have inspected the result:
#     git push --force-with-lease origin main
#
set -euo pipefail

readonly REDACTED="GEMINI_API_KEY_REDACTED"
readonly KEY_PATTERN='AIzaSy[A-Za-z0-9_-]{33}'

APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

cd "$(git rev-parse --show-toplevel)"

echo "==> Repository: $(pwd)"

# --- Preconditions ---------------------------------------------------------

if ! command -v git-filter-repo >/dev/null 2>&1; then
  cat <<'EOF'
ERROR: git-filter-repo is not installed.

    pip install git-filter-repo
    # or:  brew install git-filter-repo
    # or:  apt install git-filter-repo

Do not use `git filter-branch` for this. It is slow, error-prone, and leaves
replace-refs and reflogs behind that still contain the secret.
EOF
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: working tree is dirty. Commit or stash first." >&2
  exit 1
fi

# filter-repo refuses to run on a shallow clone.
if [[ -f .git/shallow ]]; then
  echo "==> Shallow clone detected; fetching full history..."
  git fetch --unshallow origin || git fetch --depth=2147483647 origin
fi

# --- Find every commit carrying the key ------------------------------------

echo "==> Scanning history for API key literals..."
FOUND_KEYS=""
while read -r commit; do
  keys=$(git grep -hoE "$KEY_PATTERN" "$commit" -- 2>/dev/null || true)
  if [[ -n "$keys" ]]; then
    echo "    $commit  $(git log -1 --format=%s "$commit")"
    FOUND_KEYS+="$keys"$'\n'
  fi
done < <(git rev-list --all)

UNIQUE_KEYS=$(printf '%s' "$FOUND_KEYS" | sort -u | grep -v '^$' || true)

if [[ -z "$UNIQUE_KEYS" ]]; then
  echo "==> No API key literals found in history. Nothing to do."
  exit 0
fi

echo "==> Distinct key(s) to redact:"
while read -r k; do
  [[ -z "$k" ]] && continue
  echo "    ${k:0:10}...${k: -4}  (masked)"
done <<< "$UNIQUE_KEYS"

if [[ $APPLY -eq 0 ]]; then
  cat <<'EOF'

==> DRY RUN. Nothing was changed.

Before rewriting:
  1. Revoke the key at https://aistudio.google.com/apikey  <-- do this first
  2. Back up:  git clone --mirror . ../backup-$(date +%s).git
  3. Re-run:   ./scripts/purge_key_from_history.sh --apply
EOF
  exit 0
fi

# --- Rewrite ---------------------------------------------------------------

BACKUP="../gjter-backup-$(date +%Y%m%d-%H%M%S).git"
echo "==> Backing up to $BACKUP"
git clone --mirror . "$BACKUP" >/dev/null 2>&1
echo "    Backup complete. Restore with: git clone $BACKUP"

REPLACE_FILE=$(mktemp)
trap 'rm -f "$REPLACE_FILE"' EXIT
while read -r k; do
  [[ -z "$k" ]] && continue
  printf '%s==>%s\n' "$k" "$REDACTED" >> "$REPLACE_FILE"
done <<< "$UNIQUE_KEYS"

echo "==> Rewriting history..."
git filter-repo --replace-text "$REPLACE_FILE" --force

# --- Verify ----------------------------------------------------------------

echo "==> Verifying every blob in the rewritten history..."
LEAKS=0
while read -r obj; do
  if [[ "$(git cat-file -t "$obj" 2>/dev/null)" == "blob" ]]; then
    if git cat-file -p "$obj" 2>/dev/null | grep -qE "$KEY_PATTERN"; then
      echo "    LEAK STILL PRESENT in blob $obj" >&2
      LEAKS=$((LEAKS + 1))
    fi
  fi
done < <(git rev-list --objects --all | awk '{print $1}')

if [[ $LEAKS -gt 0 ]]; then
  echo "==> FAILED: $LEAKS blob(s) still contain a key. Restore from $BACKUP." >&2
  exit 1
fi

echo "==> Verified clean: no API key literal remains in any blob."

cat <<EOF

==> Local rewrite complete. 'origin' was removed by filter-repo (by design).

Next steps:

    git remote add origin https://github.com/anacondy/GJ-Ter-perplex-fills-data-from-gemini-API.git
    git log --oneline            # sanity-check the rewritten history
    git push --force-with-lease origin main

Then:
  * Tell every collaborator to re-clone. Old clones still hold the secret and
    will reintroduce it if anyone pushes from one.
  * Enable push protection:
    Settings -> Code security -> Secret scanning -> Push protection
  * If you have not already: REVOKE THE OLD KEY.
    https://aistudio.google.com/apikey
EOF
