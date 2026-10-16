from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = _ROOT / "tests" / "fixtures" / "anonymous-v3.jsonl"
_REQUIRED_PACKAGE_FILES = (
    "pupu_danmu_plugin_sdk/__init__.py",
    "pupu_danmu_plugin_sdk/protocol.py",
    "pupu_danmu_plugin_sdk/host.py",
    "pupu_danmu_plugin_sdk/clock.py",
    "pupu_danmu_plugin_sdk/replay.py",
)


def _run(command: list[str], *, cwd: Path, environment: dict[str, str]) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {command!r}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout


def _members(artifact: Path) -> set[str]:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            return {name.replace("\\", "/") for name in archive.namelist()}
    if artifact.name.endswith(".tar.gz"):
        with tarfile.open(artifact, "r:gz") as archive:
            return {
                member.name.replace("\\", "/").removeprefix("./")
                for member in archive.getmembers()
            }
    raise ValueError(f"unsupported artifact type: {artifact.name}")


def _verify_archive_contents(artifact: Path) -> None:
    members = _members(artifact)
    missing = [
        suffix
        for suffix in _REQUIRED_PACKAGE_FILES
        if not any(name.endswith(suffix) for name in members)
    ]
    if missing:
        raise ValueError(f"{artifact.name} is missing package files: {missing}")

    if not any(name.endswith("/LICENSE") or name == "LICENSE" for name in members):
        raise ValueError(f"{artifact.name} does not include the MIT license")

    forbidden_fragments = (
        "/pupu_danmu/core/",
        "/.git/",
        "/.venv/",
        "HANDOFF.md",
        ".env",
        "cookies.sqlite",
        "browser-profile",
    )
    unsafe = sorted(
        name
        for name in members
        if any(fragment in f"/{name}".lower() for fragment in forbidden_fragments)
    )
    if unsafe:
        raise ValueError(f"{artifact.name} contains forbidden files: {unsafe}")


def _install_and_replay(artifact: Path, uv: str, work: Path) -> None:
    venv = work / "venv"
    _run(
        [uv, "venv", "--python", sys.executable, str(venv)],
        cwd=work,
        environment=os.environ.copy(),
    )
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    _run(
        [uv, "pip", "install", "--python", str(python), "--no-deps", str(artifact)],
        cwd=work,
        environment=environment,
    )

    output = _run(
        [str(python), "-m", "pupu_danmu_plugin_sdk.replay", str(_FIXTURE)],
        cwd=work,
        environment=environment,
    )
    if "invocations=1 sessions=1 runs=1 outcomes=0" not in output:
        raise RuntimeError(f"unexpected Replay output for {artifact.name}: {output!r}")
    if str(_ROOT) in output:
        raise RuntimeError(f"Replay resolved from the source checkout: {output!r}")

    import_check = (
        "import sys; "
        "import pupu_danmu_plugin_sdk.clock; "
        "import pupu_danmu_plugin_sdk.host; "
        "import pupu_danmu_plugin_sdk.protocol; "
        "import pupu_danmu_plugin_sdk.replay; "
        "assert not any(name == 'pupu_danmu' or name.startswith('pupu_danmu.') "
        "for name in sys.modules); "
        "assert not any(name.startswith(('PySide6', 'PyQt', 'playwright')) "
        "for name in sys.modules)"
    )
    _run([str(python), "-c", import_check], cwd=work, environment=environment)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install and replay both SDK distribution artifacts in clean environments."
    )
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--expected-version")
    arguments = parser.parse_args()

    dist_dir = arguments.dist_dir.resolve()
    uv = shutil.which("uv")
    if uv is None:
        parser.error("uv must be available on PATH")
    wheels = sorted(dist_dir.glob("pupu_danmu_plugin_sdk-*.whl"))
    sdists = sorted(dist_dir.glob("pupu_danmu_plugin_sdk-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        parser.error("dist directory must contain exactly one SDK wheel and one sdist")

    artifacts = [*wheels, *sdists]
    expected = arguments.expected_version
    if expected is not None:
        for artifact in artifacts:
            if f"-{expected}" not in artifact.name:
                parser.error(f"artifact version does not match expected {expected}")

    for artifact in artifacts:
        _verify_archive_contents(artifact)

    for artifact in artifacts:
        with tempfile.TemporaryDirectory(prefix="pupu-sdk-verify-") as temp:
            _install_and_replay(artifact, uv, Path(temp))

    sums = "".join(f"{_sha256(path)}  {path.name}\n" for path in artifacts)
    (dist_dir / "SHA256SUMS").write_text(sums, encoding="utf-8", newline="\n")
    print(sums, end="")
    print("verified wheel and sdist: anonymous replay passed outside the source tree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
