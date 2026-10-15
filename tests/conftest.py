from __future__ import annotations

from datetime import UTC
from datetime import datetime

import pytest
from pupu_danmu_plugin_sdk.protocol import Invocation
from pupu_danmu_plugin_sdk.protocol import Opportunity
from pupu_danmu_plugin_sdk.protocol import OpportunityMode
from pupu_danmu_plugin_sdk.protocol import SessionFocus
from pupu_danmu_plugin_sdk.protocol import ViewerChatSnapshot

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def invocation() -> Invocation:
    return Invocation(
        invocation_id="invocation-demo",
        session_id="session-demo",
        run_id="run-demo",
        capture_id="capture-demo",
        revision=0,
        viewer_chat=ViewerChatSnapshot(),
        session_focus=SessionFocus(),
        opportunity=Opportunity(OpportunityMode.CONTEXTUAL_FOLLOWUP, False),
    )