"""Anonymous JSONL replay CLI for local Python plugin development."""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pupu_danmu_plugin_sdk.host import HostStub, PluginContext
from pupu_danmu_plugin_sdk.protocol import (
    SUPPORTED_CAPABILITIES,
    Candidate,
    Invocation,
    Silent,
    TypedFailure,
    WorkerOutcome,
    decode_invocation,
)

PluginEntrypoint = Callable[[PluginContext], WorkerOutcome]


@dataclass(frozen=True, slots=True)
class ReplayRecord:
    invocation: Invocation
    context: PluginContext
    outcome: WorkerOutcome | None


class ReplayHarness:
    """Parse anonymous invocation JSONL and optionally call local plugin code."""

    __slots__ = ("_host",)

    def __init__(self, host: HostStub | None = None) -> None:
        self._host = host or HostStub()

    def run_jsonl(
        self,
        source: str | Iterable[str],
        *,
        plugin: PluginEntrypoint | None = None,
    ) -> tuple[ReplayRecord, ...]:
        lines = source.splitlines() if isinstance(source, str) else iter(source)
        results: list[ReplayRecord] = []
        for line_number, line in enumerate(lines, start=1):
            if not isinstance(line, str):
                raise ValueError(f"JSONL line {line_number} must be text")
            if not line.strip():
                raise ValueError(f"JSONL line {line_number} is empty")
            try:
                invocation = decode_invocation(line)
            except ValueError as exc:
                raise ValueError(
                    f"invalid anonymous invocation on line {line_number}: {exc}"
                ) from None
            context = self._host.context_for(invocation)
            _advance_clock(context, invocation)
            outcome = plugin(context) if plugin is not None else None
            if outcome is not None and not isinstance(
                outcome, (Candidate, Silent, TypedFailure)
            ):
                raise ValueError(
                    "plugin replay must return Candidate, Silent, or TypedFailure"
                )
            results.append(ReplayRecord(invocation, context, outcome))
        return tuple(results)


def _advance_clock(context: PluginContext, invocation: Invocation) -> None:
    timestamps: list[datetime] = [
        item.received_at for item in invocation.viewer_chat.messages
    ]
    timestamps.extend(item.sent_at for item in invocation.recent_self_sent)
    timestamps.extend(item.settled_at for item in invocation.settlements)
    timestamps.extend(
        item.observed_at
        for item in invocation.room_evidence
        if item.observed_at is not None
    )
    if invocation.session_focus.last_topic_shift_at is not None:
        timestamps.append(invocation.session_focus.last_topic_shift_at)
    if timestamps and max(timestamps) >= context.clock.now:
        context.clock.advance_to(max(timestamps))


def _load_plugin(specification: str) -> PluginEntrypoint:
    module_name, separator, attribute = specification.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("plugin must use module:function syntax")
    module = importlib.import_module(module_name)
    plugin = getattr(module, attribute)
    if not callable(plugin):
        raise ValueError("plugin entrypoint is not callable")
    return plugin


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and replay anonymous protocol-v2 JSONL locally. "
            "This tool never reads account state or runs a remotely installed plugin."
        )
    )
    parser.add_argument(
        "input", type=Path, help="UTF-8 JSONL of protocol-v2 invocations"
    )
    parser.add_argument(
        "--plugin",
        help="optional local developer entrypoint in module:function form",
    )
    parser.add_argument(
        "--capability",
        action="append",
        choices=sorted(SUPPORTED_CAPABILITIES),
        default=[],
        help="capability exposed by the local HostStub; may be repeated",
    )
    arguments = parser.parse_args(argv)
    try:
        text = arguments.input.read_text(encoding="utf-8")
        plugin = None if arguments.plugin is None else _load_plugin(arguments.plugin)
        host = HostStub(capabilities=arguments.capability)
        records = ReplayHarness(host).run_jsonl(text, plugin=plugin)
    except (OSError, UnicodeError, ValueError, ImportError, AttributeError) as exc:
        print(f"Replay failed: {exc}", file=sys.stderr)
        return 2
    sessions = len({record.invocation.session_id for record in records})
    runs = len(
        {(record.invocation.session_id, record.invocation.run_id) for record in records}
    )
    outcomes = sum(record.outcome is not None for record in records)
    print(
        f"invocations={len(records)} sessions={sessions} runs={runs} outcomes={outcomes}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ReplayHarness", "ReplayRecord", "main"]
