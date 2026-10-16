# Changelog

Package releases use semantic versioning. Protocol compatibility is tracked separately in docs/protocol-compatibility.md.

## Unreleased (0.2.0.dev0)

- Add protocol v2 capability-call and capability-response DTOs with strict JSON codecs and request correlation.
- Add the bounded protocol v2 host cancellation message for an active Worker invocation.
- Add the Worker-side host RPC client seam; authorization remains the host broker's responsibility.

## 0.1.0 - 2026-10-15

- Extract the version 2 protocol DTOs and strict JSON codec into a standalone package.
- Include capability-checked local host adapters, a deterministic replay clock, and anonymous JSONL replay.
- Add independent wheel and source distribution verification.
