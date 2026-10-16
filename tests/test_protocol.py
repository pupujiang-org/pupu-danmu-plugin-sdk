from __future__ import annotations

import json

import pytest
from conftest import NOW

from pupu_danmu_plugin_sdk.protocol import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    CapabilityCall,
    CapabilityResponse,
    PluginProtocolError,
    ViewerChatSnapshot,
    ViewerMessage,
    WorkerCancellation,
    decode_capability_call,
    decode_capability_response,
    decode_invocation,
    decode_worker_cancellation,
    encode_capability_call,
    encode_capability_response,
    encode_invocation,
    encode_worker_cancellation,
)


def test_protocol_version_two_round_trips(invocation) -> None:
    encoded = encode_invocation(invocation)
    assert json.loads(encoded)["protocol_version"] == PROTOCOL_VERSION == 2
    assert decode_invocation(encoded) == invocation


def test_unknown_protocol_version_fails_closed(invocation) -> None:
    payload = json.loads(encode_invocation(invocation))
    payload["protocol_version"] = 3
    with pytest.raises(PluginProtocolError, match="unsupported protocol version"):
        decode_invocation(payload)


def test_duplicate_and_unknown_fields_are_rejected(invocation) -> None:
    with pytest.raises(PluginProtocolError, match="duplicate field"):
        decode_invocation('{"protocol_version":2,"protocol_version":2}')

    payload = json.loads(encode_invocation(invocation))
    payload["host_private_field"] = "must not cross the SDK boundary"
    with pytest.raises(PluginProtocolError, match="missing or unsupported fields"):
        decode_invocation(payload)


def test_unsupported_capability_is_rejected() -> None:
    with pytest.raises(PluginProtocolError, match="unsupported capability"):
        CapabilityCall("request-1", "filesystem.write", "write", {})


def test_viewer_snapshot_keeps_only_the_newest_fifty() -> None:
    messages = [
        ViewerMessage(
            f"viewer-{index}",
            f"message {index}",
            NOW.replace(second=index),
        )
        for index in range(60)
    ]
    snapshot = ViewerChatSnapshot.from_messages(messages)
    assert len(snapshot.messages) == 50
    assert snapshot.messages[0].message_id == "viewer-10"
    assert snapshot.messages[-1].message_id == "viewer-59"


def test_capability_call_round_trips_without_invocation_identity() -> None:
    call = CapabilityCall(
        "rpc-1",
        "llm.generate",
        "llm.generate.generate",
        {"prompt": "Give one short response"},
    )

    encoded = encode_capability_call(call)
    decoded = decode_capability_call(encoded)

    assert decoded == call
    assert json.loads(encoded) == {
        "protocol_version": PROTOCOL_VERSION,
        "type": "capability_call",
        "request_id": "rpc-1",
        "capability": "llm.generate",
        "method": "llm.generate.generate",
        "payload": {"prompt": "Give one short response"},
    }


def test_capability_call_rejects_unknown_method_and_capability_mismatch() -> None:
    with pytest.raises(PluginProtocolError, match="unsupported method"):
        CapabilityCall("rpc-1", "llm.generate", "llm.generate.stream", {})

    with pytest.raises(PluginProtocolError, match="does not match method"):
        CapabilityCall("rpc-1", "storage.session", "llm.generate.generate", {})


def test_capability_call_codec_rejects_unknown_and_duplicate_fields() -> None:
    call = CapabilityCall(
        "rpc-1", "storage.session", "storage.session.get", {"key": "topic"}
    )
    payload = json.loads(encode_capability_call(call))
    payload["invocation_id"] = "must not be accepted"
    with pytest.raises(PluginProtocolError, match="missing or unsupported fields"):
        decode_capability_call(payload)

    with pytest.raises(PluginProtocolError, match="duplicate field"):
        decode_capability_call(
            '{"protocol_version":2,"type":"capability_call",'
            '"request_id":"rpc-1","request_id":"rpc-2",'
            '"capability":"storage.session","method":"storage.session.get",'
            '"payload":{"key":"topic"}}'
        )


def test_capability_call_codec_rejects_invalid_json_non_finite_and_oversize() -> None:
    with pytest.raises(PluginProtocolError, match="valid UTF-8 JSON"):
        decode_capability_call(b"\xff")

    with pytest.raises(PluginProtocolError, match="non-finite"):
        encode_capability_call(
            CapabilityCall(
                "rpc-1",
                "storage.session",
                "storage.session.set",
                {"value": float("nan")},
            )
        )

    with pytest.raises(PluginProtocolError, match="size limit"):
        encode_capability_call(
            CapabilityCall(
                "rpc-1",
                "storage.session",
                "storage.session.set",
                {"value": "x" * MAX_MESSAGE_BYTES},
            )
        )


def test_capability_response_success_and_failure_round_trip() -> None:
    success = CapabilityResponse(
        request_id="rpc-1", success=True, result={"text": "ok"}
    )
    success_bytes = encode_capability_response(success)
    assert (
        decode_capability_response(success_bytes, expected_request_id="rpc-1")
        == success
    )

    failure = CapabilityResponse(
        request_id="rpc-2", success=False, error_code="capability_denied"
    )
    failure_bytes = encode_capability_response(failure)
    assert (
        decode_capability_response(failure_bytes, expected_request_id="rpc-2")
        == failure
    )


def test_capability_response_rejects_mismatched_or_duplicate_request_id() -> None:
    response = CapabilityResponse(request_id="rpc-1", success=True, result=None)
    with pytest.raises(PluginProtocolError, match="request_id mismatch"):
        decode_capability_response(
            encode_capability_response(response), expected_request_id="rpc-2"
        )

    with pytest.raises(PluginProtocolError, match="duplicate field"):
        decode_capability_response(
            '{"protocol_version":2,"type":"capability_response",'
            '"request_id":"rpc-1","request_id":"rpc-1",'
            '"success":true,"result":null}'
        )


def test_capability_response_rejects_conflicting_branches_and_identity_fields() -> None:
    with pytest.raises(PluginProtocolError, match="mutually exclusive"):
        CapabilityResponse(
            request_id="rpc-1",
            success=True,
            result="ok",
            error_code="failed",
        )

    response = CapabilityResponse(request_id="rpc-1", success=True, result="ok")
    payload = json.loads(encode_capability_response(response))
    payload["run_id"] = "must not cross the RPC boundary"
    with pytest.raises(PluginProtocolError, match="missing or unsupported fields"):
        decode_capability_response(payload)


def test_worker_cancellation_round_trips_without_session_or_run_identity() -> None:
    cancellation = WorkerCancellation("invocation-7")

    encoded = encode_worker_cancellation(cancellation)
    decoded = decode_worker_cancellation(encoded)

    assert decoded == cancellation
    assert json.loads(encoded) == {
        "protocol_version": PROTOCOL_VERSION,
        "type": "cancel",
        "invocation_id": "invocation-7",
    }


def test_worker_cancellation_rejects_unknown_identity_fields() -> None:
    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "type": "cancel",
        "invocation_id": "invocation-7",
        "session_id": "not part of cancellation authority",
    }

    with pytest.raises(PluginProtocolError, match="missing or unsupported fields"):
        decode_worker_cancellation(payload)
