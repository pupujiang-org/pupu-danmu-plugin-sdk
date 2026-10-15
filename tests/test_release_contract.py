from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


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
    assert "anonymous replay passed outside the source tree" in verifier