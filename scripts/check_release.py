"""Reject release tags that do not match the packaged version."""

import re
import sys
import tomllib
from pathlib import Path


def validate_tag(tag: str, version: str) -> None:
    if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag):
        raise ValueError("Release tag must use vMAJOR.MINOR.PATCH, for example v0.1.0.")
    if tag != f"v{version}":
        raise ValueError(f"Tag {tag} does not match package version {version}.")


if __name__ == "__main__":
    with Path("pyproject.toml").open("rb") as file:
        version = tomllib.load(file)["project"]["version"]
    validate_tag(sys.argv[1], version)
