#!/bin/sh
# Use an existing environment; never install packages or save credentials implicitly.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -n "${MEDIX_PYTHON:-}" ]; then
    python="$MEDIX_PYTHON"
elif [ -x .venv/bin/python ]; then
    python=.venv/bin/python
else
    python=python3
fi
exec "$python" run_web.py --open "$@"
