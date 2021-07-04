#!/usr/bin/env python

import argparse
from collections.abc import Sequence
import jinja2
import os
from pathlib import Path
from ruamel.yaml import YAML
from semver import VersionInfo
import shutil
import sys
from typing import NamedTuple


class ModuleMetadata(NamedTuple):
    name: str
    versions: list[VersionInfo]
    display_name: str = None
    url: str = None


def _generate_versions(jd_root: Path, metadata_file: Path) -> list[ModuleMetadata]: # module -> list[version]
    """
    Generate a mapping of project to module version.
    """
    loader = YAML()
    data = loader.load(metadata_file)

    result = []

    for module in jd_root.iterdir():
        dirname = module.name
        if dirname.startswith(".") or dirname.startswith("_") or not module.is_dir():
            continue

        versions = [VersionInfo.parse(x.name) for x in module.iterdir() if x.is_dir and not x.name.startswith(".")]
        versions.sort()

        extra_metadata = data.get(dirname, {})
        result.append(ModuleMetadata(
            dirname,
            versions,
            extra_metadata.get("name", None),
            extra_metadata.get("url", None)
        ))

    print(result)

    return result


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate static content for JD site")
    parser.add_argument('dest', type=Path, help="Directory to generate to")
    parser.add_argument('--jd-root', type=Path, help="Directory to search for module Javadoc in", default='.')
    parser.add_argument('--metadata', type=Path, help="YAML file containing extra component metadata", default="components.yaml")

    script_dir = Path(__file__).parent

    parser.add_argument("--template-root", type=Path, help="Directory to read templates from", default = script_dir / 'tmpl')
    parser.add_argument("--static-root", type=Path, help="Static root, for files copied directly", default = script_dir / 'static')
    return parser


def _do_generate(dest: Path, jd_root: Path, metadata_file: Path, template_root: Path, static_root: Path):
    print(f"Generating from jd={jd_root}, metadata_file={metadata_file}, tmpl={template_root}, static={static_root} -> {dest}")

    # Setup, generate metadata
    module_versions = _generate_versions(jd_root, metadata_file)
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
    tmpl_env.globals["module_versions"] = module_versions

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
    for module in module_versions:
        module_out = dest / module.name
        print(f"Copying {module.name} to {module_out}")
        shutil.copytree(jd_root / module.name, module_out, copy_function=os.link,symlinks=True)
        print(f"Generating 'latest' symlink for {module.name}")
        (module_out / 'latest/').symlink_to(Path(str(max(module.versions))))

        # SpongeAPI legacy path support (it's ugly but it works)
        if module.name == "spongeapi":
            newest_legacy = VersionInfo(7, 3, 0)
            for version in module.versions:
                if version <= newest_legacy:
                    (dest / str(version)).symlink_to(module.name + '/' + str(version))

    print(f"Generated successfully to {dest}")


def main(args: Sequence[str]):
    parser = _create_parser()
    parsed = parser.parse_args(args)
    _do_generate(parsed.dest, parsed.jd_root, parsed.metadata, parsed.template_root, parsed.static_root)


if __name__ == "__main__":
    main(sys.argv[1:])
