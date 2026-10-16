from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path

import pupu_danmu_plugin_sdk

_ROOT = Path(__file__).resolve().parents[1]
_DISTRIBUTION = "pupu-danmu-plugin-sdk"
# Development (`.dev`) and local (`+`) version segments. The SDK releases from
# `vX.Y.Z` tags whose version matches `project.version`, so these markers are
# only legitimate while `pyproject.toml` declares the same pre-release;
# otherwise the module constant carries a stale development marker into an
# installed wheel.
_UNRELEASED_MARKERS = (".dev", "+")


def _declared_version() -> str:
    metadata = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(metadata["project"]["version"])


def test_module_version_matches_the_installed_distribution_metadata() -> None:
    metadata_version = importlib.metadata.version(_DISTRIBUTION)
    assert pupu_danmu_plugin_sdk.__version__ == metadata_version, (
        f"pupu_danmu_plugin_sdk.__version__ is "
        f"{pupu_danmu_plugin_sdk.__version__!r} but the installed "
        f"{_DISTRIBUTION} distribution reports {metadata_version!r}"
    )


def test_module_version_matches_the_declared_project_version() -> None:
    declared = _declared_version()
    assert pupu_danmu_plugin_sdk.__version__ == declared, (
        f"pupu_danmu_plugin_sdk.__version__ is "
        f"{pupu_danmu_plugin_sdk.__version__!r} but pyproject.toml declares "
        f"version = {declared!r}"
    )


def test_module_version_carries_no_undeclared_unreleased_marker() -> None:
    version = pupu_danmu_plugin_sdk.__version__
    declared = _declared_version()
    for marker in _UNRELEASED_MARKERS:
        assert (marker in version) == (marker in declared), (
            f"__version__={version!r} and the declared project version "
            f"{declared!r} disagree on the {marker!r} version marker; a "
            f"development or local marker has to be declared in pyproject.toml "
            f"before it appears in __version__"
        )
