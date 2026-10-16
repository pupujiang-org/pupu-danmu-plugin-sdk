"""One-invocation local Python Worker used by the host development runtime.

This subprocess and its IPC are fault-isolation tools only. They do not sandbox
Python code or authorize remote/community package execution.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from threading import Lock
from typing import BinaryIO

from pupu_danmu_plugin_sdk.host import CapabilityCallError, remote_context
from pupu_danmu_plugin_sdk.protocol import (
    MAX_MESSAGE_BYTES,
    SUPPORTED_CAPABILITIES,
    Candidate,
    Invocation,
    PluginProtocolError,
    Silent,
    TypedFailure,
    decode_capability_response,
    decode_invocation,
    decode_worker_cancellation,
    encode_worker_outcome,
)


class WorkerCancelledError(RuntimeError):
    """The host cancelled this invocation while it awaited a capability."""


class _StdioCapabilityTransport:
    __slots__ = ("_input", "_invocation_id", "_lock", "_output")

    def __init__(
        self,
        input_stream: BinaryIO,
        output_stream: BinaryIO,
        *,
        invocation_id: str,
    ) -> None:
        self._input = input_stream
        self._output = output_stream
        self._invocation_id = invocation_id
        self._lock = Lock()

    def exchange(self, payload: bytes) -> bytes:
        with self._lock:
            if len(payload) > MAX_MESSAGE_BYTES:
                raise CapabilityCallError("message_too_large")
            self._output.write(payload + b"\n")
            self._output.flush()
            response = _read_frame(self._input)
            try:
                raw = json.loads(response.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise PluginProtocolError("host response is invalid") from None
            if isinstance(raw, dict) and raw.get("type") == "cancel":
                cancellation = decode_worker_cancellation(response)
                if cancellation.invocation_id != self._invocation_id:
                    raise PluginProtocolError("host cancellation identity mismatch")
                raise WorkerCancelledError("worker invocation was cancelled")
            decode_capability_response(response)
            return response


def _read_frame(stream: BinaryIO) -> bytes:
    frame = stream.readline(MAX_MESSAGE_BYTES + 2)
    if not frame or len(frame) > MAX_MESSAGE_BYTES + 1 or not frame.endswith(b"\n"):
        raise PluginProtocolError("IPC frame is missing or exceeds its size limit")
    payload = frame[:-1]
    if payload.endswith(b"\r"):
        payload = payload[:-1]
    if not payload:
        raise PluginProtocolError("IPC frame is empty")
    return payload


def _load_entrypoint(specification: str):
    module_name, separator, attribute = specification.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("entrypoint must use module:function syntax")
    module = importlib.import_module(module_name)
    entrypoint = getattr(module, attribute)
    if not callable(entrypoint):
        raise ValueError("entrypoint is not callable")
    return entrypoint


def _run_one_invocation(
    invocation: Invocation,
    *,
    entrypoint: str,
    plugin_root: Path,
    capabilities: tuple[str, ...],
    input_stream: BinaryIO,
    protocol_output: BinaryIO,
) -> Candidate | Silent | TypedFailure:
    sys.path.insert(0, str(plugin_root))
    context_transport = _StdioCapabilityTransport(
        input_stream,
        protocol_output,
        invocation_id=invocation.invocation_id,
    )
    context = remote_context(
        invocation,
        capabilities=capabilities,
        transport=context_transport,
    )
    try:
        result = _load_entrypoint(entrypoint)(context)
    except WorkerCancelledError:
        return TypedFailure("worker_cancelled", retryable=False)
    except Exception:  # noqa: BLE001 - Worker boundary returns a sanitized failure.
        return TypedFailure("plugin_error", retryable=True)
    if not isinstance(result, (Candidate, Silent, TypedFailure)):
        return TypedFailure("invalid_plugin_outcome", retryable=False)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one local trusted Python plugin call"
    )
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--entrypoint", required=True)
    parser.add_argument(
        "--capability",
        action="append",
        choices=sorted(SUPPORTED_CAPABILITIES),
        default=[],
    )
    arguments = parser.parse_args(argv)
    protocol_input = sys.stdin.buffer
    protocol_output = sys.stdout.buffer
    sys.stdout = sys.stderr
    try:
        plugin_root = arguments.plugin_root.resolve(strict=True)
        if not plugin_root.is_dir():
            raise ValueError("plugin root is unavailable")
        invocation = decode_invocation(_read_frame(protocol_input))
        outcome = _run_one_invocation(
            invocation,
            entrypoint=arguments.entrypoint,
            plugin_root=plugin_root,
            capabilities=tuple(arguments.capability),
            input_stream=protocol_input,
            protocol_output=protocol_output,
        )
    except (OSError, PluginProtocolError, ValueError):
        outcome = TypedFailure("worker_protocol_error", retryable=False)
    try:
        payload = encode_worker_outcome(outcome)
        if len(payload) > MAX_MESSAGE_BYTES:
            return 2
        protocol_output.write(payload + b"\n")
        protocol_output.flush()
    except (OSError, PluginProtocolError):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
