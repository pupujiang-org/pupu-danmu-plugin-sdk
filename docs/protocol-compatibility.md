# Protocol and package compatibility

The SDK package version and the wire protocol version are separate version lines.

| Version line | Current value | Meaning |
| --- | --- | --- |
| SDK package | 0.1.0 (latest release); 0.2.0.dev0 (local development) | Python distribution API and packaging changes |
| Plugin protocol | 2 | Version field carried by invocation and Worker outcome messages |
| Host application | Host-owned | Determines which SDK release and protocol versions it supports |
| Plugin | Plugin-owned | Declares its SDK and protocol compatibility |

## Protocol v2 contract

The package exposes immutable DTOs and a strict JSON codec for protocol v2. It bounds message size and nesting, rejects duplicate JSON fields and unsupported fields, validates timestamps and identifiers, and rejects unsupported protocol versions and capabilities.

Invocation context contains anonymous viewer message identifiers and timestamps, bounded to at most 50 viewer messages. Self-sent messages and settlement records are separate fields. Viewer statements and plugin fact claims are untrusted context; protocol DTOs do not certify product facts or authorize a send.

## Host capability RPC in protocol v2

SDK 0.2.0.dev0 adds `CapabilityCall` and `CapabilityResponse` messages for a Worker to request one host capability operation and receive a correlated result, plus a host `WorkerCancellation` control message. Calls are limited to `llm.generate.generate` and `storage.session.get`, `storage.session.set`, or `storage.session.delete`; the capability must match the selected method. Each message uses the protocol message-size limit and strict UTF-8 JSON validation, including duplicate-key and non-finite-number rejection.

The request id is the only correlation value in an RPC response. Calls and responses carry no invocation, run, capture, or session identity. The host retains those identities in its pending invocation state and remains responsible for authorizing each call, validating its payload, and applying session isolation. The SDK client provides framing-neutral byte exchange and correlation checks; it does not grant capabilities or implement the host broker.

## Compatibility policy

- A package patch release may fix implementation defects without changing protocol v2 wire semantics.
- A package minor release may add compatible Python APIs or tooling while preserving protocol v2 behavior.
- A package major release may remove or change Python APIs.
- Any incompatible wire change requires a new protocol version and explicit host compatibility work.
- A host must reject unknown protocol versions and undeclared or unsupported capabilities.

These are SDK package policies. They do not promise compatibility with a particular released host until that host lists its supported SDK and protocol versions.
