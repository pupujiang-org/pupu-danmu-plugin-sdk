# Changelog

Package releases use semantic versioning. Protocol compatibility is tracked separately in docs/protocol-compatibility.md.

## 0.3.0.dev0 - Unreleased

- Add protocol v3 session configuration with a persona id and bounded, immutable JSON options.
- Add `session.config.read` as an explicit projection capability, separate from `room.read` and session focus.
- Reject protocol v2 messages in the v3 development SDK rather than interpreting them with changed fields.

## 0.2.0 - 2026-10-16

- Add protocol v2 capability-call and capability-response DTOs with strict JSON codecs and request correlation.
- Add the bounded protocol v2 host cancellation message for an active Worker invocation.
- Add the Worker-side host RPC client seam; authorization remains the host broker's responsibility.
- Add a one-invocation local Worker process with bounded newline-delimited IPC, host capability routing, stdout separation, and cancellation handling.
- Add `PluginContext` adapters that route LLM and session storage calls through the host RPC transport.

## 0.1.0 - 2026-10-15

- Extract the version 2 protocol DTOs and strict JSON codec into a standalone package.
- Include capability-checked local host adapters, a deterministic replay clock, and anonymous JSONL replay.
- Add independent wheel and source distribution verification.
