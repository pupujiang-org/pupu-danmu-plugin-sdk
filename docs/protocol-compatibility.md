# Protocol and package compatibility

The SDK package version and the wire protocol version are separate version lines.

| Version line | Current value | Meaning |
| --- | --- | --- |
| SDK package | 0.1.0 | Python distribution API and packaging changes |
| Plugin protocol | 2 | Version field carried by invocation and Worker outcome messages |
| Host application | Host-owned | Determines which SDK release and protocol versions it supports |
| Plugin | Plugin-owned | Declares its SDK and protocol compatibility |

## Protocol v2 contract

The package exposes immutable DTOs and a strict JSON codec for protocol v2. It bounds message size and nesting, rejects duplicate JSON fields and unsupported fields, validates timestamps and identifiers, and rejects unsupported protocol versions and capabilities.

Invocation context contains anonymous viewer message identifiers and timestamps, bounded to at most 50 viewer messages. Self-sent messages and settlement records are separate fields. Viewer statements and plugin fact claims are untrusted context; protocol DTOs do not certify product facts or authorize a send.

## Compatibility policy

- A package patch release may fix implementation defects without changing protocol v2 wire semantics.
- A package minor release may add compatible Python APIs or tooling while preserving protocol v2 behavior.
- A package major release may remove or change Python APIs.
- Any incompatible wire change requires a new protocol version and explicit host compatibility work.
- A host must reject unknown protocol versions and undeclared or unsupported capabilities.

These are SDK package policies. They do not promise compatibility with a particular released host until that host lists its supported SDK and protocol versions.