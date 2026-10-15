from __future__ import annotations

import json

import pytest
from pupu_danmu_plugin_sdk.protocol import PROTOCOL_VERSION
from pupu_danmu_plugin_sdk.protocol import CapabilityCall
from pupu_danmu_plugin_sdk.protocol import PluginProtocolError
from pupu_danmu_plugin_sdk.protocol import ViewerChatSnapshot
from pupu_danmu_plugin_sdk.protocol import ViewerMessage
from pupu_danmu_plugin_sdk.protocol import decode_invocation
from pupu_danmu_plugin_sdk.protocol import encode_invocation

from conftest import NOW


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