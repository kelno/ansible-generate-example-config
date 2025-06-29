#!/bin/sh

# This script generates documentation for the Ansible roles in the current directory.
# Generated files:
# - VARIABLES: Contains the variables for each role.
# - group_vars/all/main.yml.example: Example configuration file generated from the variables.

ROLES=$(find roles -maxdepth 1 -mindepth 1 -type d ! -name '.*' -printf '%f\n' | sort)
ansible-doc -t role -r roles $ROLES > VARIABLES
python3 group_vars/all/generate_example_config.py
