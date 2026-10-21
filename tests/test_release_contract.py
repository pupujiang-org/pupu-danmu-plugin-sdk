import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_protocol_v3_release_metadata_is_consistent() -> None:
    metadata = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_version = metadata["project"]["version"]
    module = (_ROOT / "src" / "pupu_danmu_plugin_sdk" / "__init__.py").read_text(
        encoding="utf-8"
    )
    changelog = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    compatibility = (_ROOT / "docs" / "protocol-compatibility.md").read_text(
        encoding="utf-8"
    )
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")

    assert package_version == "0.3.0"
    assert '__version__ = "0.3.0"' in module
    assert "## 0.3.0 - Unreleased" in changelog
    assert "| SDK v0.2.0 / protocol v2 |" in compatibility
    assert "| SDK v0.3.0 / protocol v3 |" in compatibility
    assert "host-owned Manifest schema v2 is unchanged" in compatibility
    assert "session.config.read" in compatibility
    assert "pupu_danmu_plugin_sdk-0.2.0-py3-none-any.whl" in readme


def test_ci_and_tag_workflows_are_read_only_and_verify_distributions() -> None:
    ci = (_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    release = (_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    assert "pull_request:" in ci
    assert 'python-version: "3.13"' in ci
    assert "contents: read" in ci
    assert "uv build --out-dir dist" in ci
    assert "verify_dist.py --dist-dir dist" in ci
    assert 'tags:\n      - "v*"' in release
    assert "contents: read" in release
    assert "actions/upload-artifact" in release
    for workflow in (ci, release):
        assert "dist/*.whl" in workflow
        assert "dist/*.tar.gz" in workflow
        assert "dist/SHA256SUMS" in workflow
    assert "id-token: write" not in release
    assert "pypi" not in release.lower()


def test_distribution_verifier_checks_both_formats_and_hashes() -> None:
    verifier = (_ROOT / "scripts" / "verify_dist.py").read_text(encoding="utf-8")
    assert 'glob("pupu_danmu_plugin_sdk-*.whl")' in verifier
    assert 'glob("pupu_danmu_plugin_sdk-*.tar.gz")' in verifier
    assert 'environment.pop("PYTHONPATH", None)' in verifier
    assert "hashlib.sha256" in verifier
    assert "anonymous replay and installed SDK protocol tests" in verifier


def test_distribution_verifier_runs_protocol_tests_against_installed_artifact() -> None:
    verifier = (_ROOT / "scripts" / "verify_dist.py").read_text(encoding="utf-8")
    assert '"test_protocol.py"' in verifier
    assert '"test_host.py"' in verifier
    assert '"sync"' in verifier
    assert '"--no-install-project"' in verifier
    assert "installed SDK protocol tests passed outside the source tree" in verifier
