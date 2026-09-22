#!/usr/bin/env bash
set -euo pipefail

# Reset local Epsilon project state for a fresh demo or re-initialisation.
#
# This removes local generated project files and the local project/workbench
# registry. It does not remove Epsilon credentials or anything from the
# remote service. With no arguments it cleans every project registered on
# this computer; pass project folders to clean only those.

SDK_ROOT="${EPSILON_SDK_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
STATE_DIR="${EPSILON_STATE_DIR:-${HOME}/.epsilon_sdk}"
EPSILON_BIN="${EPSILON_BIN:-${SDK_ROOT}/.venv/bin/epsilon}"

usage() {
  cat <<'EOF'
Usage: bash scripts/reset-local-workspace.sh [--yes] [PROJECT_DIR ...]

Clean local Epsilon projects and unregister all local projects. Without
PROJECT_DIR arguments, every project in the local registry is cleaned. The
project folders themselves are preserved so they can be initialised again.

Environment overrides:
  EPSILON_SDK_ROOT    SDK checkout (default: this repository)
  EPSILON_STATE_DIR   local state directory (default: ~/.epsilon_sdk)
  EPSILON_BIN         epsilon executable
EOF
}

confirm=""
PROJECTS=()
for arg in "$@"; do
  case "${arg}" in
    --yes) confirm="yes" ;;
    --help|-h) usage; exit 0 ;;
    -*) usage >&2; exit 2 ;;
    *) PROJECTS+=("${arg}") ;;
  esac
done

if [[ "${STATE_DIR}" != */.epsilon_sdk ]]; then
  echo "Refusing unexpected state directory: ${STATE_DIR}" >&2
  exit 1
fi

if [[ ! -x "${EPSILON_BIN}" ]]; then
  echo "epsilon executable not found: ${EPSILON_BIN}" >&2
  echo "Install the SDK or set EPSILON_BIN to the correct executable." >&2
  exit 1
fi

if [[ ${#PROJECTS[@]} -eq 0 && -f "${STATE_DIR}/projects.json" ]]; then
  # One path per line, read with the SDK's own Python so no jq is needed.
  while IFS= read -r path; do
    [[ -n "${path}" ]] && PROJECTS+=("${path}")
  done < <("$(dirname "${EPSILON_BIN}")/python" -c '
import json, sys
for project in json.load(open(sys.argv[1])).get("projects", []):
    print(project.get("path", ""))
' "${STATE_DIR}/projects.json")
fi

if [[ "${confirm}" != "yes" ]]; then
  echo "This will remove local generated files from:"
  if [[ ${#PROJECTS[@]} -eq 0 ]]; then
    echo "  (no registered projects found)"
  else
    printf '  %s\n' "${PROJECTS[@]}"
  fi
  cat <<EOF

It will also unregister all local projects and remove local notebook/chat
history under ${STATE_DIR}. Credentials and remote datasets are preserved.
EOF
  read -r -p "Continue? Type RESET to continue: " answer
  [[ "${answer}" == "RESET" ]] || { echo "Cancelled."; exit 1; }
fi

for project in "${PROJECTS[@]+"${PROJECTS[@]}"}"; do
  if [[ ! -d "${project}" ]]; then
    echo "Skipping missing project folder: ${project}"
    continue
  fi
  echo "Cleaning ${project}"
  (
    cd "${project}"
    "${EPSILON_BIN}" clean --yes
  )
  # These are local audit transcripts for the old project. The folder itself
  # remains available for a new epsilon init.
  rm -rf -- "${project}/.epsilon/chat"
done

if [[ -d "${STATE_DIR}" ]]; then
  echo "Clearing local project registry and workbench state"
  rm -f -- "${STATE_DIR}/projects.json" \
          "${STATE_DIR}/workbench.db" \
          "${STATE_DIR}/chat.db"
  rm -rf -- "${STATE_DIR}/audit" \
             "${STATE_DIR}/handoff" \
             "${STATE_DIR}/kernels"
fi

echo
echo "Local Epsilon workspace reset."
echo "Credentials were preserved. Start again with:"
echo "  ${EPSILON_BIN} start"
