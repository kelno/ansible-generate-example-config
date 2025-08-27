#!/bin/sh
set -e

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" >/dev/null 2>&1 && pwd)"
ORIGINAL_WORKING_DIR="$(pwd)"

# Ensure venv exists in the current directory
if ! PIPENV_PIPFILE="$SCRIPT_DIR/Pipfile" pipenv --venv >/dev/null 2>&1; then
  echo "No pipenv environment found in '$SCRIPT_DIR'"
  read -rp "Do you want to create one now? [y/n] " answer
  case "$answer" in
      [Yy]* )
          echo "Creating a new Pipenv environment... If this fails, you can create yourself with `pipenv install` in this script directory."
          PIPENV_PIPFILE="$SCRIPT_DIR/Pipfile" pipenv --python /usr/bin/python install
          ;;
      [Nn]* )
          echo "Skipping environment creation."
          ;;
      * )
          echo "Invalid answer"
          exit 1
          ;;
  esac
fi

# Run inside the venv, from the original working dir
PIPENV_PIPFILE="$SCRIPT_DIR/Pipfile" pipenv run python3 "$SCRIPT_DIR/generate_config.py" "$@"
