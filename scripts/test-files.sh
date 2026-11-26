#!/usr/bin/env bash
# Run the tests for the given files: pytest for *.py, vitest for web/* (paths relative to web/).
set -u

py_files=()
web_files=()
for f in "$@"; do
  case "$f" in
    *.py) py_files+=("$f") ;;
    web/*) web_files+=("${f#web/}") ;;
  esac
done

status=0
if [ "${#py_files[@]}" -gt 0 ]; then
  uv run pytest -q "${py_files[@]}" || status=1
fi
if [ "${#web_files[@]}" -gt 0 ]; then
  (cd web && npx vitest run "${web_files[@]}") || status=1
fi
exit "$status"
