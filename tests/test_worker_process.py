from __future__ import annotations

import os
import subprocess
import sys

from pupu_danmu_plugin_sdk.protocol import (
    Candidate,
    CapabilityResponse,
    TypedFailure,
    WorkerCancellation,
    decode_capability_call,
    decode_worker_outcome,
    encode_capability_response,
    encode_invocation,
    encode_worker_cancellation,
)


def _launch_worker(tmp_path, invocation):
    plugin = tmp_path / "worker_plugin.py"
    plugin.write_text(
        "from pupu_danmu_plugin_sdk.protocol import Candidate\n"
        "def run(context):\n"
        "    return Candidate(context.generate('write a short reply'))\n",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pupu_danmu_plugin_sdk.worker",
            "--plugin-root",
            str(tmp_path),
            "--entrypoint",
            "worker_plugin:run",
            "--capability",
            "llm.generate",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=tmp_path,
        env=os.environ.copy(),
        text=True,
        encoding="utf-8",
    )
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write(encode_invocation(invocation).decode("utf-8") + "\n")
    process.stdin.flush()
    return process


def test_worker_runs_one_plugin_invocation_and_brokers_one_capability(
    tmp_path, invocation
) -> None:
    process = _launch_worker(tmp_path, invocation)
    assert process.stdout is not None
    assert process.stdin is not None
    try:
        call = decode_capability_call(process.stdout.readline())
        assert call.capability == "llm.generate"
        assert call.payload == {"prompt": "write a short reply"}
        process.stdin.write(
            encode_capability_response(
                CapabilityResponse(call.request_id, True, result="垂感怎么样？")
            ).decode("utf-8")
            + "\n"
        )
        process.stdin.flush()
        outcome_line = process.stdout.readline()
        if not outcome_line:
            return_code = process.wait(timeout=2)
            assert process.stderr is not None
            raise AssertionError(
                f"Worker exited without an outcome: {return_code}; "
                f"stderr={process.stderr.read()}"
            )
        outcome = decode_worker_outcome(outcome_line)
        assert outcome == Candidate("垂感怎么样？")
        assert process.wait(timeout=2) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)


def test_worker_cancellation_returns_typed_failure(tmp_path, invocation) -> None:
    process = _launch_worker(tmp_path, invocation)
    assert process.stdout is not None
    assert process.stdin is not None
    try:
        call = decode_capability_call(process.stdout.readline())
        assert call.request_id
        process.stdin.write(
            encode_worker_cancellation(
                WorkerCancellation(invocation.invocation_id)
            ).decode("utf-8")
            + "\n"
        )
        process.stdin.flush()
        outcome = decode_worker_outcome(process.stdout.readline())
        assert outcome == TypedFailure("worker_cancelled", retryable=False)
        assert process.wait(timeout=2) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
