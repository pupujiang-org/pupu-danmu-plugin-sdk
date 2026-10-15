from __future__ import annotations

import pytest
from pupu_danmu_plugin_sdk.host import CapabilityDeniedError
from pupu_danmu_plugin_sdk.host import HostStub


def test_context_requires_each_declared_capability(invocation) -> None:
    context = HostStub(capabilities={"chat.read"}).context_for(invocation)
    assert context.viewer_messages == ()
    with pytest.raises(CapabilityDeniedError):
        _ = context.room_evidence
    with pytest.raises(CapabilityDeniedError):
        _ = context.storage
    with pytest.raises(CapabilityDeniedError):
        context.generate("question")


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