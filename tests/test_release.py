"""A release must publish the version it claims to contain."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "check_release", Path(__file__).parents[1] / "scripts" / "check_release.py"
)
check_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_release)


def test_matching_release_version_is_accepted():
    check_release.validate_tag("v0.1.0", "0.1.0")


@pytest.mark.parametrize("tag", ["0.1.0", "v0.2.0", "v0.1.0rc1", "v01.1.0", "v0.1.0/extra"])
def test_invalid_or_mismatched_release_version_is_rejected(tag):
    with pytest.raises(ValueError):
        check_release.validate_tag(tag, "0.1.0")
