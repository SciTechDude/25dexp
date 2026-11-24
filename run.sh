#!/usr/bin/env bash
#
# Launcher for the 2.5D arcade experiment.
#
#   ./run.sh              whack-a-mole (default), starting at its menu
#   ./run.sh game         whack-a-mole, same thing
#   ./run.sh depth        projection / depth comparison demo
#   ./run.sh sky          "eye in the sky" view
#   ./run.sh touch        mouse -> input snapshots -> drawn contacts
#   ./run.sh capture      headless PNG render + blank-frame check
#   ./run.sh shots        headless PNGs of the game, its menu and exit dialog
#   ./run.sh calibrate    measure your screen, write calibration JSON
#   ./run.sh probe        Linux only: what an attached touchscreen reports
#   ./run.sh test         the test suite
#   ./run.sh lint         unused imports / undefined names
#   ./run.sh setup        create the conda env and install the project
#   ./run.sh shell        print the env's python path
#
# Extra arguments are passed through, so this works:
#   ./run.sh game --theme night --difficulty advanced --skip-menu
#
set -euo pipefail

ENV_NAME="tabletop"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# --- locate conda -----------------------------------------------------------
# `conda` is often a shell function rather than a binary, and this script runs
# non-interactively, so resolve the base directory and use the env's
# interpreter directly instead of relying on `conda activate`.
find_conda_base() {
    if command -v conda >/dev/null 2>&1; then
        conda info --base 2>/dev/null && return 0
    fi
    for candidate in \
        "/opt/homebrew/Caskroom/miniconda/base" \
        "$HOME/miniconda3" \
        "$HOME/miniforge3" \
        "$HOME/anaconda3" \
        "/opt/miniconda3"
    do
        if [ -x "$candidate/bin/conda" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

if ! CONDA_BASE="$(find_conda_base)"; then
    echo "error: could not find a conda installation." >&2
    echo "       Install miniconda, or edit find_conda_base() in run.sh." >&2
    exit 1
fi

CONDA_BIN="$CONDA_BASE/bin/conda"
PY="$CONDA_BASE/envs/$ENV_NAME/bin/python"

require_env() {
    if [ ! -x "$PY" ]; then
        echo "error: conda env '$ENV_NAME' not found at $PY" >&2
        echo "       run: ./run.sh setup" >&2
        exit 1
    fi
}

# --- commands ---------------------------------------------------------------
cmd="${1:-game}"
[ $# -gt 0 ] && shift || true

case "$cmd" in
    setup)
        if [ -x "$PY" ]; then
            echo "env '$ENV_NAME' already exists; installing/updating the project"
        else
            echo "creating conda env '$ENV_NAME' (python 3.12)"
            "$CONDA_BIN" create -y -n "$ENV_NAME" python=3.12
        fi
        "$PY" -m pip install --upgrade pip
        # '.[dev]' brings pytest; '.[linux]' adds evdev, which is only for
        # reading a touchscreen on Linux and does not exist on macOS.
        "$PY" -m pip install -e '.[dev]'
        if [ "$(uname -s)" = "Linux" ]; then
            echo "Linux detected: installing the evdev extra for touch input"
            "$PY" -m pip install -e '.[linux]'
        fi
        echo
        echo "done. try: ./run.sh game"
        ;;

    game|whack|mole)
        require_env; exec "$PY" -m tabletop.apps.whack_a_mole "$@" ;;
    depth)
        require_env; exec "$PY" -m tabletop.apps.depth_demo "$@" ;;
    sky)
        require_env; exec "$PY" -m tabletop.apps.sky_demo "$@" ;;
    touch)
        require_env; exec "$PY" -m tabletop.apps.touch_demo "$@" ;;
    calibrate)
        require_env; exec "$PY" -m tabletop.apps.calibrate "$@" ;;
    probe)
        require_env; exec "$PY" -m tabletop.apps.probe_touch "$@" ;;

    capture)
        require_env
        out="${1:-renders}"
        [ $# -gt 0 ] && shift || true
        mkdir -p "$out"
        echo "writing frames to $out/"
        exec "$PY" -m tabletop.apps.capture --out "$out" --check "$@"
        ;;

    shots)
        require_env
        out="${1:-renders}"
        [ $# -gt 0 ] && shift || true
        mkdir -p "$out"
        "$PY" -m tabletop.apps.capture --scene game --out "$out" --check "$@"
        "$PY" -m tabletop.apps.capture --scene menu --out "$out" --check "$@"
        "$PY" -m tabletop.apps.capture --scene confirm --out "$out" --check "$@"
        echo "frames written to $out/"
        ;;

    test|tests)
        require_env; exec "$PY" -m pytest "$@" ;;
    lint)
        require_env
        "$PY" -m pip install -q pyflakes
        # platform_setup is imported for its side effect (it configures
        # Panda3D before Ursina loads), so its "unused" report is expected.
        "$PY" -m pyflakes tabletop tests | grep -v platform_setup || true
        echo "lint done"
        ;;

    shell|python)
        require_env; echo "$PY" ;;

    -h|--help|help)
        # Print the comment header, stopping at the first non-comment line,
        # so the help text cannot drift out of sync with a line range.
        awk 'NR>2 && /^#/ { sub(/^# ?/, ""); print; next } NR>2 { exit }' "$0"
        ;;

    *)
        echo "error: unknown command '$cmd'" >&2
        echo "try: ./run.sh --help" >&2
        exit 2
        ;;
esac
