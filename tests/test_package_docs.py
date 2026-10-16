from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def test_readme_documents_install_and_local_only_replay() -> None:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "uv add pupu-danmu-plugin-sdk==0.1.0" in readme
    assert "anonymous.jsonl" in readme
    assert "does not provide an operating-system sandbox" in readme


def test_compatibility_docs_separate_package_protocol_and_host_versions() -> None:
    compatibility = (_ROOT / "docs" / "protocol-compatibility.md").read_text(
        encoding="utf-8"
    )
    assert "SDK package | 0.1.0" in compatibility
    assert "0.2.0.dev0 (local development)" in compatibility
    assert "Plugin protocol | 2" in compatibility
    assert "Host application | Host-owned" in compatibility
    assert "reject unknown protocol versions" in compatibility


def test_project_metadata_declares_python_floor_and_mit_license() -> None:
    project = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    license_text = (_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.13"' in project
    assert 'license = "MIT"' in project
    assert "MIT License" in license_text
    assert "Copyright (c) 2026 Pupujiang" in license_text
