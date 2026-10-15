# Security policy

This SDK contains protocol data types and local replay helpers. It is not a sandbox, plugin loader, or production authorization system.

- Do not put credentials, account state, private viewer data, or production session dumps in replay fixtures.
- Treat plugin output and viewer-provided text as untrusted.
- The host must enforce authorization, capability grants, final candidate checks, and operating-system isolation independently of this SDK.
- The replay command executes only an entrypoint explicitly selected by the local caller, in the current Python process.

Before the first public release, maintainers should enable GitHub private vulnerability reporting for the repository. Until that is available, do not disclose security-sensitive details in a public issue.