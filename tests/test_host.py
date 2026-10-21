from __future__ import annotations

from dataclasses import replace

import pytest

from pupu_danmu_plugin_sdk.host import (
    CapabilityCallError,
    CapabilityDeniedError,
    HostRpcClient,
    HostStub,
    remote_context,
)
from pupu_danmu_plugin_sdk.protocol import (
    CapabilityResponse,
    SessionConfiguration,
    decode_capability_call,
    encode_capability_response,
)


class _RpcTransport:
    def __init__(self, *, response_id: str | None = None, error_code: str = "") -> None:
        self.response_id = response_id
        self.error_code = error_code
        self.calls = []

    def exchange(self, payload: bytes) -> bytes:
        call = decode_capability_call(payload)
        self.calls.append(call)
        response = CapabilityResponse(
            request_id=self.response_id or call.request_id,
            success=not bool(self.error_code),
            result=call.method if not self.error_code else None,
            error_code=self.error_code or None,
        )
        return encode_capability_response(response)


def test_context_requires_each_declared_capability(invocation) -> None:
    context = HostStub(capabilities={"chat.read"}).context_for(invocation)
    assert context.viewer_messages == ()
    with pytest.raises(CapabilityDeniedError):
        _ = context.room_evidence
    with pytest.raises(CapabilityDeniedError):
        _ = context.storage
    with pytest.raises(CapabilityDeniedError):
        context.generate("question")


def test_session_configuration_and_room_focus_require_separate_capabilities(
    invocation,
) -> None:
    configuration = SessionConfiguration(
        persona_id="friendly-host", options={"initiative_enabled": True}
    )
    configured_invocation = replace(invocation, session_configuration=configuration)

    configuration_context = HostStub(capabilities={"session.config.read"}).context_for(
        configured_invocation
    )
    assert configuration_context.session_configuration == configuration
    with pytest.raises(CapabilityDeniedError):
        _ = configuration_context.session_focus

    room_context = HostStub(capabilities={"room.read"}).context_for(
        configured_invocation
    )
    assert room_context.session_focus == invocation.session_focus
    with pytest.raises(CapabilityDeniedError):
        _ = room_context.session_configuration


def test_storage_is_bounded_and_session_scoped(invocation) -> None:
    host = HostStub(capabilities={"storage.session"}, storage_max_bytes=32)
    first = host.context_for(invocation)
    first.storage.set("topic", {"name": "cotton"})

    same_session_invocation = invocation.__class__(
        invocation_id="invocation-next",
        session_id=invocation.session_id,
        run_id="run-next",
        capture_id="capture-next",
        revision=1,
        viewer_chat=invocation.viewer_chat,
        session_focus=invocation.session_focus,
        opportunity=invocation.opportunity,
    )
    other_session_invocation = invocation.__class__(
        invocation_id="invocation-other",
        session_id="session-other",
        run_id="run-other",
        capture_id="capture-other",
        revision=0,
        viewer_chat=invocation.viewer_chat,
        session_focus=invocation.session_focus,
        opportunity=invocation.opportunity,
    )
    same_session = host.context_for(same_session_invocation)
    other_session = host.context_for(other_session_invocation)

    assert same_session.storage.get("topic") == {"name": "cotton"}
    assert other_session.storage.get("topic") is None
    with pytest.raises(ValueError, match="byte limit"):
        first.storage.set("too-large", "x" * 100)


def test_host_rpc_client_correlates_each_capability_call() -> None:
    transport = _RpcTransport()
    client = HostRpcClient(transport)

    llm_result = client.call(
        "llm.generate", "llm.generate.generate", {"prompt": "short prompt"}
    )
    storage_result = client.call(
        "storage.session", "storage.session.get", {"key": "topic"}
    )

    assert llm_result == "llm.generate.generate"
    assert storage_result == "storage.session.get"
    request_ids = [call.request_id for call in transport.calls]
    assert len(set(request_ids)) == 2
    assert [request_id.rsplit("-", 1)[-1] for request_id in request_ids] == ["1", "2"]
    assert [call.capability for call in transport.calls] == [
        "llm.generate",
        "storage.session",
    ]


def test_host_rpc_client_surfaces_stable_broker_errors() -> None:
    client = HostRpcClient(_RpcTransport(error_code="capability_denied"))

    with pytest.raises(CapabilityCallError, match="capability_denied") as error:
        client.call("llm.generate", "llm.generate.generate", {"prompt": "hello"})

    assert error.value.error_code == "capability_denied"


def test_host_rpc_client_rejects_response_for_another_request() -> None:
    client = HostRpcClient(_RpcTransport(response_id="rpc-99"))

    with pytest.raises(ValueError, match="request_id mismatch"):
        client.call("llm.generate", "llm.generate.generate", {"prompt": "hello"})


def test_remote_context_routes_llm_and_session_storage_through_host_rpc(
    invocation,
) -> None:
    class ContextRpcTransport(_RpcTransport):
        def exchange(self, payload: bytes) -> bytes:
            call = decode_capability_call(payload)
            self.calls.append(call)
            result = {
                "llm.generate.generate": "candidate",
                "storage.session.get": None,
                "storage.session.set": None,
                "storage.session.delete": True,
            }[call.method]
            return encode_capability_response(
                CapabilityResponse(call.request_id, True, result=result)
            )

    transport = ContextRpcTransport()
    context = remote_context(
        invocation,
        capabilities={"llm.generate", "storage.session"},
        transport=transport,
    )

    assert context.generate("short prompt") == "candidate"
    assert context.storage.get("topic", "default") == "default"
    context.storage.set("topic", {"name": "cotton"})
    assert context.storage.delete("topic") is True
    assert [call.method for call in transport.calls] == [
        "llm.generate.generate",
        "storage.session.get",
        "storage.session.set",
        "storage.session.delete",
    ]


def test_remote_context_enforces_declared_capabilities(invocation) -> None:
    context = remote_context(invocation, capabilities=(), transport=_RpcTransport())

    with pytest.raises(CapabilityDeniedError):
        context.generate("short prompt")
    with pytest.raises(CapabilityDeniedError):
        _ = context.storage


def test_host_issued_opportunity_is_available_without_room_read(invocation) -> None:
    context = HostStub().context_for(invocation)

    assert context.opportunity == invocation.opportunity
