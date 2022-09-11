#!/usr/bin/env python

import argparse
from collections import OrderedDict
from collections.abc import Sequence
import re
import jinja2
import os
from pathlib import Path
from ruamel.yaml import YAML
from semver import VersionInfo
import shutil
import sys
from typing import Any, NamedTuple, Optional
from re import Pattern


class ModuleMetadata(NamedTuple):
    name: str
    full_path: Path
    snapshot_regex: Pattern
    versions: list[VersionInfo]
    display_name: str = None
    url: str = None


def _generate_versions(jd_root: Path, module_metadata: Any, group_metadata: Any) -> dict[str, list[ModuleMetadata]]: # module -> dict[group, list[version]]
    """
    Generate a mapping of project to module version.
    """
    result: dict[str, list[ModuleMetadata]] = OrderedDict()
    result[None] = []

    # Match order in config file
    for key in group_metadata.keys():
        result[key] = []

    _populate_versions(result, jd_root, jd_root, module_metadata, group_metadata, None)

    # Clear any empty lists
    to_remove = [k for k, v in result.items() if len(v) == 0]
    for k in to_remove:
        del result[k]

    return result

def _populate_versions(result: dict[str, list[ModuleMetadata]], jd_root: Path, current_dir: Path, module_metadata: Any, group_metadata: Any, chosen_group: Optional[str]):
    for module in current_dir.iterdir():
        dirname = module.name
        if dirname.startswith(".") or dirname.startswith("_") or not module.is_dir():
            continue

        if (not chosen_group) and dirname in group_metadata and group_metadata[dirname].get("from_directory", False):
            # contribute
            # treat every child project as part of the group
            _populate_versions(result, jd_root, module, module_metadata, group_metadata, dirname)
            continue

        extra_metadata = module_metadata.get(dirname, {})
        group = extra_metadata.get("group", chosen_group)
        result.setdefault(group, []).append(
            _resolve_metadata(jd_root, module, extra_metadata, group)
        )


def _resolve_metadata(root_path: Path, module_path: Path, module_metadata: any, group: Optional[str]) -> ModuleMetadata:
    versions = [VersionInfo.parse(x.name) for x in module_path.iterdir() if x.is_dir and not x.name.startswith(".")]
    versions.sort()

    dirname = module_path.name
    return ModuleMetadata(
            dirname,
            module_path.relative_to(root_path),
            re.compile(module_metadata.get("snapshot_pattern", ".+-SNAPSHOT$")),
            versions,
            module_metadata.get("name", None),
            module_metadata.get("url", None)
        )


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate static content for JD site")
    parser.add_argument('dest', type=Path, help="Directory to generate to")
    parser.add_argument('--jd-root', type=Path, help="Directory to search for module Javadoc in", default='.')
    parser.add_argument('--metadata', type=Path, help="YAML file containing extra component and group metadata", default="metadata.yaml")

    script_dir = Path('.').parent

    parser.add_argument("--template-root", type=Path, help="Directory to read templates from", default = script_dir / 'tmpl')
    parser.add_argument("--static-root", type=Path, help="Static root, for files copied directly", default = script_dir / 'static')
    return parser


def _do_generate(dest: Path, jd_root: Path, metadata_file: Path, template_root: Path, static_root: Path):
    print(f"Generating from jd={jd_root}, metadata_file={metadata_file}, tmpl={template_root}, static={static_root} -> {dest}")

    metadata = YAML().load(metadata_file)

    groups = metadata["groups"]
    components = metadata["components"]

    # Setup, generate metadata
    module_versions = _generate_versions(jd_root, components, groups)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(exist_ok=True)

    # Generate templates
    tmpl_env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_root),
        undefined=jinja2.StrictUndefined,
        autoescape=True,
        keep_trailing_newline=True
    )
    tmpl_env.globals["name"] = metadata.get("name", "Javadocs")
    tmpl_env.globals["module_versions"] = module_versions
    tmpl_env.globals["groups"] = groups
    # TODO: hide snapshot versions

    for tmpl in template_root.glob('**/*'):
        tmpl_out = dest / tmpl.relative_to(template_root)
        print(f"Writing {tmpl} to {tmpl_out}")
        template = tmpl_env.get_template(str(tmpl.relative_to(template_root)))
        with tmpl_out.open(mode = 'wt') as fp:
            fp.write(template.render())

    # Copy static content
    for static in static_root.glob('**/*'):
        static_out = dest / static.relative_to(static_root)
        print(f"Writing {static} to {static_out}")
        shutil.copy2(static, static_out)

    # link JD directories into the output dir
    for modules in module_versions.values():
        for module in modules:
            module_out = dest / module.full_path
            print(f"Copying {module.name} to {module_out}")
            shutil.copytree(jd_root / module.full_path, module_out, copy_function=os.link,symlinks=True)
            print(f"Generating 'latest' symlink for {module.name}")
            (module_out / 'latest/').symlink_to(Path(str(max(module.versions))))

            # SpongeAPI legacy path support (it's ugly but it works)
            if module.name == "spongeapi":
                newest_legacy = VersionInfo(7, 3, 0)
                for version in module.versions:
                    if version <= newest_legacy:
                        (dest / str(version)).symlink_to(module.name + '/' + str(version))

    print(f"Generated successfully to {dest}")


def main(args: Sequence[str] = None):
    if args is None:
        args = sys.argv[1:]
    parser = _create_parser()
    parsed = parser.parse_args(args)
    _do_generate(parsed.dest, parsed.jd_root, parsed.metadata, parsed.template_root, parsed.static_root)


if __name__ == "__main__":
    main()
