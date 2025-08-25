from dataclasses import dataclass, field
import yaml
from pathlib import Path
import argparse
import logging, coloredlogs

logger = logging.getLogger(__name__)
coloredlogs.install(
    level="INFO", logger=logger, fmt="%(asctime)s %(levelname)s %(message)s"
)


@dataclass
class ConfigHost:
    name: str
    group_name: str


# This fake special host will be used to gather shared configs
SHARED_HOST_NAME = "all"  # will be used as filename like: host_vars/.all.yml.example

SHARED_TAG = "shared"
CUSTOM_PROPERTY_SECRET = "x-secret"
SECRET_FILE_SUFFIX = ".secrets"

PLAYBOOK_AUTODETECT_NAMES = ["playbook.yml", "site.yml", "main.yml", "deploy.yml"]


@dataclass(kw_only=True)
class HostsParser:

    inventory_file: Path

    def get_hosts(self, include_shared: bool) -> list[ConfigHost]:
        """This function try to find a file : self._project_root / inventory / hosts.yml.example"""

        if not self.inventory_file.exists():
            raise ValueError(f"No such inventory file: {self.inventory_file}")

        with self.inventory_file.open() as f:
            inventory = yaml.safe_load(f)

        if not inventory:
            raise ValueError(f"Failed to read inventory at {self.inventory_file}")

        hosts: list[ConfigHost] = []
        if include_shared:
            # start with our special shared config host
            hosts.append(ConfigHost(SHARED_HOST_NAME, "all"))

        # then every host appearing in the inventory
        for top_data in inventory.values():
            for group, group_data in top_data["children"].items():
                if "hosts" in group_data:
                    for host in group_data["hosts"]:
                        hosts.append(ConfigHost(host, group))

        return hosts


@dataclass
class ConfigProperty:
    name: str
    type: str | None = None
    description: str | None = None
    required: bool = False
    default: str | int | bool | None = None
    secret: bool = False


@dataclass
class ConfigRole:
    name: str
    description: str = ""
    short_description: str = ""
    properties: list[ConfigProperty] = field(default_factory=list)


@dataclass(kw_only=True)
class ConfigGenerator:
    project_root: Path
    main_file: Path

    def parse_role(self, role: str) -> ConfigRole:
        """
        Parse meta/argument_specs.yml and defaults/main.yml in a role to build annotated variable documentation.
        Return a ConfigRole object.
        """
        role_path: Path = self.project_root / "roles" / role
        specs_path = role_path / "meta" / "argument_specs.yml"
        defaults_path = role_path / "defaults" / "main.yml"

        if not specs_path.exists():
            logger.debug(f"Role '{role_path.name}' has no argument_specs.yml")
            return ConfigRole(name=role_path.name)

        with specs_path.open() as f:
            specs = yaml.safe_load(f)

        defaults = {}
        if defaults_path.exists():
            with defaults_path.open() as f:
                defaults = yaml.safe_load(f) or {}

        short_description = ""
        description = ""
        properties: list[ConfigProperty] = []

        arg_specs = specs and specs.get("argument_specs", {}).get("main", {})
        if arg_specs:
            description = arg_specs.get("description", {})
            if not description:
                logger.warning(
                    f"Role '{role_path.name}' has empty description in argument_specs.yml"
                )
            short_description = arg_specs.get("short_description", {})
            if not short_description:
                logger.warning(
                    f"Role '{role_path.name}' has empty short_description in argument_specs.yml"
                )

        if options := arg_specs and arg_specs.get("options", {}):
            for var_name, meta in options.items():
                type = meta.get("type", None)
                description = meta.get("description", "").strip()
                required = meta.get("required", False)
                secret = meta.get(CUSTOM_PROPERTY_SECRET, False)

                default = defaults.get(var_name, meta.get("default"))

                properties.append(
                    ConfigProperty(
                        name=var_name,
                        type=type,
                        description=description,
                        required=required,
                        default=default,
                        secret=secret,
                    )
                )

        return ConfigRole(
            name=role_path.name,
            description=description,
            short_description=short_description,
            properties=properties,
        )

    def build_role_config(self, config_role: ConfigRole, secrets: bool) -> list[str]:
        """
        Parse meta/argument_specs.yml and defaults/main.yml in a role to build annotated variable documentation.
        Return a list of lines.

        Args:
            config_role (ConfigRole): The role to build config for.
            secrets (bool): Whether to process secret variables (and only those if set)
        """
        block = [
            f"\n### Role: {config_role.name}{f' - {config_role.short_description}' if config_role.short_description else ''}"
        ]
        if config_role.description:
            block.append(f"###     {config_role.description}")
        block.append("#" * 64)
        block.append("")
        if config_role.properties:
            for prop in config_role.properties:
                if prop.secret != secrets:
                    continue

                block.append(
                    f"#  ({'REQUIRED' if prop.required else 'Optional'}) {prop.description}"
                )
                if prop.type is not None:
                    block.append(f"#  Type: {prop.type}")

                if prop.default is not None:
                    block.append(f"#  Default: {prop.default}")
                block.append(
                    f"{prop.name}: {prop.default if prop.default is not None else ''}"
                )

                block.append("")  # blank line for readability
        else:
            block.append("(no options)")

        has_secrets = any(p.secret for p in config_role.properties)
        if not secrets and has_secrets:
            block.append(
                f"# Note: This role has secret variables. See the corresponding '{SECRET_FILE_SUFFIX}' file for the list of those variables."
            )
        block.append("")  # blank line for readability

        return block

    def get_dependant_roles(self, role: str) -> set[str]:
        """
        Returns roles that the provided role depends on.
        Only supports meta/main.yml deps
        """

        roles: set[str] = set()

        role_dir = self.project_root / "roles" / role
        if role_dir.is_dir() is False:
            logger.warning(f"Failed to find role directory for role '{role}'")
            return roles

        meta_file: Path = role_dir / "meta/main.yml"
        if meta_file.is_file():
            with meta_file.open() as f:
                meta = yaml.safe_load(f) or {}
                deps = meta.get("dependencies", [])
                for dep in deps:
                    dep_role = dep["role"]
                    roles.add(dep_role)
                    roles.update(self.get_dependant_roles(dep_role))

        return roles

    @staticmethod
    def extract_role_names(roles_data):
        """Convert roles data from various formats to a list of role names."""
        role_names: set[str] = set()

        if isinstance(roles_data, list):
            for item in roles_data:
                if isinstance(item, str):  # example: `item = 'ssh'`
                    role_names.add(item)
                elif isinstance(item, dict):
                    # example: `item = {'role': 'ssh', 'tags': 'some_tag'}`
                    if "role" in item:
                        role_names.add(item["role"])

        elif isinstance(roles_data, dict):
            role_names.update(roles_data.keys())

        elif isinstance(roles_data, str):
            role_names.update(roles_data)
        else:
            raise ValueError(
                f"Unexpected roles data type: {type(roles_data)} - {roles_data}"
            )
        return role_names

    def accumulate_roles(self, group_name: str) -> set[str]:
        """Tries to find roles included for a given group in the main playbook file.
        This is very basic and only supports static roles inclusion.

        Args:
            group_name (str): The group name to find roles for.

        Returns:
            set[str]: Roles found to be included or this group.
        """
        main_roles: set[str] = set()

        with self.main_file.open() as f:
            main = yaml.safe_load(f)

        # rudtry finding all tasks matching the provided group name.
        for task in main:
            if (
                group_name in task["hosts"]
                or task["hosts"] == "all"
                or ("tags" in task and SHARED_TAG in task["tags"])
            ):
                if "roles" in task:
                    main_roles.update(self.extract_role_names(task["roles"]))

        # would be nice to support some simple includes as well

        # now accumulate dependant roles as well
        accumulated_roles = main_roles.copy()
        for role in main_roles:
            accumulated_roles.update(self.get_dependant_roles(role))

        return accumulated_roles

    def generate_example_config(self, host_name: str, roles: set[str], secrets: bool):
        """
        Create an example config file for given host

        Args:
            host_name (str): The host name to create config for.
            roles (set[str]): The roles to include configs from.
            secrets (bool): Whether to process secret variables (and only those if set)
        """
        output_dir = self.project_root / "host_vars" / host_name
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = host_name if not secrets else f"{host_name}{SECRET_FILE_SUFFIX}"
        output_file = (
            output_dir / f".{stem}.yml.example"
        )  # leading dot to avoid ansible picking it up

        lines = ["---"]
        lines.append("# Autogenerated example config from roles argument_specs")
        if secrets:
            lines.append(
                "# SECRETS: This file contains only secret variables and is meant as a list of variables you should put in a vault or some secret manager, instead of here."
            )
        if host_name == SHARED_HOST_NAME:
            lines.append(
                "# These are the shared configs applied for all hosts. Any value here can be overriden in the specific host config.\n"
                "# Use the `shared` tag (in main playbook) to make configs appear here."
            )

        for role in roles:
            config_role = self.parse_role(role)
            # If we're generating the secret file, don't create empty role config blocks for roles with no variables at all
            if secrets and not any(p.secret for p in config_role.properties):
                continue

            lines.extend(self.build_role_config(config_role, secrets))

        with output_file.open("w") as f:
            f.write("\n".join(lines) + "\n\n")

        logger.info(f"Generated example config: {output_file}")

    def generate(self, hosts: list[ConfigHost]):
        """
        Create an example config file for given host
        """

        roles_per_host: dict[str, set[str]] = {}
        for host in hosts:
            roles_per_host[host.name] = self.accumulate_roles(host.group_name)

        # if we have a shared config, remove from other hosts any role that is already in shared
        if SHARED_HOST_NAME in roles_per_host:
            all_roles = roles_per_host[SHARED_HOST_NAME]
            for name, roles in roles_per_host.items():
                if name != SHARED_HOST_NAME:
                    roles.difference_update(all_roles)

        for name, roles in roles_per_host.items():
            logger.info(f"Accumulated roles for host {name}: {roles}")
            self.generate_example_config(host_name=name, roles=roles, secrets=True)
            self.generate_example_config(host_name=name, roles=roles, secrets=False)

        return 0


def find_playbook() -> Path | None:
    """Try finding a playbook file in the current working directory, using standard names"""
    for tentative_name in PLAYBOOK_AUTODETECT_NAMES:
        tentative_path = Path(tentative_name)
        if tentative_path.is_file():
            return tentative_path
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate example host_vars config from roles. See README for extended documentation.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    AUTODETECT: str = "(autodetect)"

    parser.add_argument(
        "playbook_main_file",
        nargs="?",
        default=AUTODETECT,
        help="Path to the playbook main file. By default, try to detect it in current working directory",
    )
    DEFAULT_INVENTORY_RELATIVE_PATH = "inventory/.hosts.yml.example"
    parser.add_argument(
        "-i",
        "--inventory-file",
        nargs="?",
        default=None,
        help=f"Path to inventory file to deduce existing hosts from. Defaults to '{DEFAULT_INVENTORY_RELATIVE_PATH}' relative to project main file",
    )
    parser.add_argument(
        "--process-shared",
        dest="process_shared",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=f"Create also the special 'all' shared config file, for main playbook tasks tagged with '{SHARED_TAG}'",
    )
    args = parser.parse_args()

    if args.playbook_main_file == AUTODETECT:
        main_file = find_playbook()
        if not main_file:
            logger.error(
                "Failed to find a playbook main file in current working directory"
            )
            exit(1)
    else:
        main_file = Path(args.playbook_main_file)
        if not main_file.is_file():
            logger.error(
                f"Failed to get playbook main file: '{main_file.absolute()}' does not exists or is not a file"
            )
            exit(1)

    logger.info(f"Start creating configurations files, using main file {main_file}")

    project_root = main_file.absolute().parent

    inventory_file: Path = args.inventory_file or (
        project_root / DEFAULT_INVENTORY_RELATIVE_PATH
    )
    hosts = HostsParser(inventory_file=inventory_file).get_hosts(args.process_shared)
    gen = ConfigGenerator(project_root=project_root, main_file=main_file)
    gen.generate(hosts)

    logger.info("Done")
