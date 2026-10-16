# Pupu Danmu Plugin SDK

A small Python package for the version 2 plugin protocol, capability-checked local host adapters, deterministic clocks, and anonymous JSONL replay.

This package contains data contracts and local development tools. It does not download or sandbox plugins, authorize production execution, or decide whether a generated candidate may be sent. Those responsibilities stay with the host application.

## Requirements

- Python 3.13 or newer
- No runtime dependencies

## Install

Install the exact wheel attached to the official GitHub release:

    uv add "pupu-danmu-plugin-sdk @ https://github.com/pupujiang-org/pupu-danmu-plugin-sdk/releases/download/v0.2.0/pupu_danmu_plugin_sdk-0.2.0-py3-none-any.whl"

For local development from a checkout:

    uv sync --group dev
    uv run pytest

## Build distributions

    uv build

The build produces a wheel and a source distribution in dist/.

## Replay anonymous protocol data

Create a UTF-8 JSONL file with one protocol-v2 invocation per line, then run:

    pupu-danmu-plugin-replay anonymous.jsonl

A local developer can explicitly choose a locally installed Python entrypoint:

    pupu-danmu-plugin-replay anonymous.jsonl --plugin example_plugin:run --capability chat.read

The selected function receives a local PluginContext. This is a developer tool: it executes the caller-selected local Python code in the current process. It does not load remote plugins and does not provide an operating-system sandbox.

The one-invocation Worker process is a development runtime for host integration tests. A separate process and Job Object help with timeout and crash cleanup; they do not sandbox Python code. Do not use it to execute remote, community, or otherwise untrusted packages.

## Compatibility

The SDK package version follows semantic versioning independently from protocol version 2, the host application version, and individual plugin versions. See docs/protocol-compatibility.md before changing or pinning a protocol implementation.

## Security

Treat replay input and plugin output as untrusted. Do not use account credentials, private viewer data, or production session state in replay fixtures. See SECURITY.md.
