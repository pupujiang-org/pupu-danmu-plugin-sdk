# Protocol and package compatibility

The SDK package version and the Worker wire protocol version are independent.

| Version line | Current value | Meaning |
| --- | --- | --- |
| SDK package | 0.3.0.dev0 | Current development checkout |
| Plugin protocol | 3 | Version carried by invocation and Worker messages in this checkout |
| Published SDK/protocol | v0.2.0 / 2 | Immutable release; it continues to implement protocol v2 |
| Host application | Host-owned | Must explicitly support the SDK, protocol, and capabilities it runs |
| Plugin | Plugin-owned | Must declare its SDK, host API, and runtime compatibility |

## Protocol v3 contract

The package exposes immutable DTOs and a strict JSON codec for protocol v3. It bounds message size and nesting, rejects duplicate JSON fields and unsupported fields, validates timestamps and identifiers, and rejects unsupported protocol versions and capabilities.

Invocation context contains at most 50 anonymous viewer messages with host-observed timestamps. `session_focus` contains host-derived room context. `session_configuration` contains the user-selected `persona_id` and bounded JSON `options`; these fields stay separate because room context and user settings have different owners and permissions. The host must validate options against the installed manifest schema and project session configuration only when `session.config.read` is granted. `room.read` does not imply that permission. Configuration does not grant capabilities or establish product facts.

Self-sent messages and settlement records remain separate fields. Viewer statements and plugin fact claims are untrusted context; protocol DTOs do not certify product facts or authorize a send.

## Host capability RPC in protocol v3

`CapabilityCall` and `CapabilityResponse` messages let a Worker request one host capability operation and receive a correlated result, with a host `WorkerCancellation` control message. Calls are limited to `llm.generate.generate` and `storage.session.get`, `storage.session.set`, or `storage.session.delete`; the capability must match the selected method. `session.config.read` gates invocation projection and does not add a Worker RPC method. Each message uses the protocol message-size limit and strict UTF-8 JSON validation, including duplicate-key and non-finite-number rejection.

The request id is the only correlation value in an RPC response. Calls and responses carry no invocation, run, capture, or session identity. The host retains those identities in its pending invocation state and remains responsible for authorizing each call, validating its payload, and applying session isolation. The SDK client provides framing-neutral byte exchange and correlation checks; it does not grant capabilities or implement the host broker.

The SDK's development Worker process handles one invocation per process and reads a `module:function` plugin entrypoint. It supports newline-delimited bounded protocol frames over standard input/output, and redirects plugin stdout away from the protocol stream. This is process isolation for host integration tests only, not an operating-system sandbox. Remote/community Python execution remains disabled until the host's Windows isolation and authorization gates pass.

## Compatibility policy

- The published v0.2.0 package and protocol v2 remain immutable.
- This development line uses protocol v3; protocol v2 messages are rejected rather than silently reinterpreted.
- An incompatible wire change requires a new protocol version and explicit host compatibility work.
- A host must reject unknown protocol versions and undeclared or unsupported capabilities.

These SDK policies do not promise compatibility with a particular host until that host lists its supported SDK and protocol versions.
