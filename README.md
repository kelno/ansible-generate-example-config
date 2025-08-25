# Kelno's ansible python scripts
A collection of various python scripts to assist with ansible tasks.

## Requirements
- pipenv

Specific scripts might have project structure requirements.

## Setup

- Setup the venv and deps with `pipenv install` in this directory.

## Scripts

### generate_config.py

A script about generating automatically centralized config file examples, grouping all host-specific variables in their own files.  

The script will:  
- Parse the inventory, get the group list from there
- Parse the main file, try to find statically every included roles for any given group
- Create a config file for each host
- A special tag "shared" can be used on task in the main file to mark the roles inside as going to the 'all' host config. (Roles found with this tag will be removed from other configs.)
- A special "secrets" config file might also be created, for variable marked with custom attribute "x-secret: true".
  This is mostly convenience and here to help you have a clean list of what should go in a vault or some secret manager.

This requires a very specific project structure, and only supports very basic static inclusion, this is not a full ansible parser. For the configs it does not catch, you could improve the script or fall back to making a separate config file for them.  

Currently only supports direct inclusion in main file or via meta deps.

#### Usage

- Run command with `(pipenv run) python generate_config.py <playbook_main_file> [specific_inventory_file]`
  Use `--help` for more details.  

A helper script is also provided, to be run from your main project directory:
`./generate_doc/docs.sh`

(todo: a mini project example would help here)

### ?
