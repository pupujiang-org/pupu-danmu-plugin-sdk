from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from conftest import NOW

from pupu_danmu_plugin_sdk.clock import ReplayClock
from pupu_danmu_plugin_sdk.protocol import encode_invocation
from pupu_danmu_plugin_sdk.replay import ReplayHarness


def test_anonymous_jsonl_replay_round_trips_without_account_state(invocation) -> None:
    source = encode_invocation(invocation).decode("utf-8") + "\n"
    (record,) = ReplayHarness().run_jsonl(source)

    assert record.invocation == invocation
    assert record.invocation.session_id == "session-demo"
    assert "cookie" not in source.lower()
    assert "account_id" not in source.lower()


def test_replay_clock_advances_deterministically() -> None:
    clock = ReplayClock(NOW)
    assert clock.now == NOW
    assert clock.advance(seconds=2.5).isoformat() == "2026-01-01T00:00:02.500000+00:00"
    assert clock.now == clock.advance_to(clock.now)


def test_import_boundary_excludes_host_ui_and_browser_modules(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    code = (
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
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
