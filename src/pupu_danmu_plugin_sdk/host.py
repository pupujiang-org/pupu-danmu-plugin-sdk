"""Small, capability-checked host adapters for local plugin development."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol
from uuid import uuid4

from pupu_danmu_plugin_sdk.clock import ReplayClock
from pupu_danmu_plugin_sdk.protocol import (
    MAX_CANDIDATE_CHARS,
    SUPPORTED_CAPABILITIES,
    CapabilityCall,
    Invocation,
    JsonValue,
    RoomEvidence,
    SelfSentMessage,
    SessionConfiguration,
    Settlement,
    ViewerMessage,
    decode_capability_response,
    encode_capability_call,
)

_MAX_STORAGE_KEY_CHARS = 128
_MAX_STORAGE_DEPTH = 12
_MAX_STORAGE_NODES = 2048


class CapabilityDeniedError(PermissionError):
    """Raised when local plugin code calls a host method it did not declare."""


class CapabilityCallError(RuntimeError):
    """A broker rejected one request with a stable, content-free code."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


class CapabilityTransport(Protocol):
    """Synchronous byte exchange supplied by the isolated Worker runtime."""

    def exchange(self, payload: bytes) -> bytes: ...


class HostRpcClient:
    """Worker-side client for host-brokered capabilities.

    The transport only sees bounded protocol frames. Invocation identity,
    session authority, and permission decisions stay in the host broker.
    """

    __slots__ = ("_lock", "_request_number", "_request_prefix", "_transport")

    def __init__(self, transport: CapabilityTransport) -> None:
        if not callable(getattr(transport, "exchange", None)):
            raise TypeError("capability transport must provide exchange(payload)")
        self._transport = transport
        self._request_prefix = uuid4().hex
        self._request_number = 0
        self._lock = Lock()

    def call(
        self,
        capability: str,
        method: str,
        payload: Mapping[str, object],
    ) -> JsonValue:
        """Make one correlated RPC; the host independently authorizes every call."""

        with self._lock:
            self._request_number += 1
            request_id = f"rpc-{self._request_prefix}-{self._request_number}"
            request = CapabilityCall(request_id, capability, method, payload)
            response_bytes = self._transport.exchange(encode_capability_call(request))
            response = decode_capability_response(
                response_bytes,
                expected_request_id=request_id,
            )
            if not response.success:
                raise CapabilityCallError(response.error_code or "broker_failed")
            return response.result


class Llm(Protocol):
    def generate(self, prompt: str) -> str: ...


class SessionStoragePort(Protocol):
    def get(self, key: str, default: object = None) -> object: ...

    def set(self, key: str, value: object) -> None: ...

    def delete(self, key: str) -> bool: ...


class MockLlm:
    """A deterministic response queue that never contacts a model service."""

    __slots__ = ("_responses", "prompts")

    def __init__(self, responses: Iterable[str] = ()) -> None:
        self._responses = iter(responses)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("LLM prompt must be non-empty text")
        if len(prompt) > 16_000:
            raise ValueError("LLM prompt exceeds its size limit")
        self.prompts.append(prompt)
        try:
            response = next(self._responses)
        except StopIteration:
            return ""
        if not isinstance(response, str) or len(response) > MAX_CANDIDATE_CHARS:
            raise ValueError("mock LLM response is invalid or too large")
        return response


class SessionStorage:
    """Copy-on-read JSON storage scoped to one replay session and byte budget."""

    __slots__ = ("_max_bytes", "_session_id", "_values")

    def __init__(self, session_id: str, *, max_bytes: int = 64 * 1024) -> None:
        if not session_id:
            raise ValueError("session id must be non-empty")
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("storage max_bytes must be a positive integer")
        self._session_id = session_id
        self._max_bytes = max_bytes
        self._values: dict[str, object] = {}

    def get(self, key: str, default: object = None) -> object:
        self._validate_key(key)
        if key not in self._values:
            return default
        return json.loads(self._encode(self._values[key]).decode("utf-8"))

    def set(self, key: str, value: object) -> None:
        self._validate_key(key)
        normalized = self._normalize(value, max_bytes=self._max_bytes)
        updated = {**self._values, key: normalized}
        if len(self._encode(updated)) > self._max_bytes:
            raise ValueError("session storage exceeds its byte limit")
        self._values = updated

    def delete(self, key: str) -> bool:
        self._validate_key(key)
        if key not in self._values:
            return False
        self._values = {
            name: item for name, item in self._values.items() if name != key
        }
        return True

    @staticmethod
    def _validate_key(key: str) -> None:
        if (
            not isinstance(key, str)
            or not key.strip()
            or len(key) > _MAX_STORAGE_KEY_CHARS
        ):
            raise ValueError("session storage key is invalid")

    @classmethod
    def _normalize(cls, value: object, *, max_bytes: int) -> object:
        budget = [0]

        def consume(amount: int) -> None:
            budget[0] += amount
            if budget[0] > max_bytes:
                raise ValueError("session storage value exceeds its byte limit")

        def check(item: object, depth: int, count: list[int]) -> None:
            count[0] += 1
            if depth > _MAX_STORAGE_DEPTH or count[0] > _MAX_STORAGE_NODES:
                raise ValueError("session storage value exceeds its structure limit")
            if isinstance(item, dict):
                if not all(isinstance(key, str) for key in item):
                    raise ValueError("session storage object keys must be text")
                for key, child in item.items():
                    check(key, depth + 1, count)
                    check(child, depth + 1, count)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    check(child, depth + 1, count)
            elif isinstance(item, str):
                if len(item) > max_bytes:
                    raise ValueError("session storage string exceeds its byte limit")
                consume(len(item.encode("utf-8")))
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError("session storage numbers must be finite")
            elif type(item) is int:
                consume(len(str(item)))
            elif item is not None and type(item) not in {bool, int, float, str}:
                raise ValueError("session storage accepts JSON values only")

        check(value, 0, [0])
        encoded = cls._encode(value)
        return json.loads(encoded.decode("utf-8"))

    @staticmethod
    def _encode(value: object) -> bytes:
        try:
            return json.dumps(
                value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError):
            raise ValueError(
                "session storage accepts bounded JSON values only"
            ) from None


@dataclass(frozen=True, slots=True)
class PluginContext:
    """One invocation view; capability checks guard every optional host surface."""

    _invocation: Invocation = field(repr=False)
    _capabilities: frozenset[str]
    _storage: SessionStoragePort
    _llm: Llm
    clock: ReplayClock

    def _require(self, capability: str) -> None:
        if capability not in self._capabilities:
            raise CapabilityDeniedError(f"capability is not available: {capability}")

    @property
    def viewer_messages(self) -> tuple[ViewerMessage, ...]:
        self._require("chat.read")
        return self._invocation.viewer_chat.messages

    @property
    def room_evidence(self) -> tuple[RoomEvidence, ...]:
        self._require("room.read")
        return self._invocation.room_evidence

    @property
    def session_focus(self):
        self._require("room.read")
        return self._invocation.session_focus

    @property
    def session_configuration(self) -> SessionConfiguration:
        self._require("session.config.read")
        return self._invocation.session_configuration

    @property
    def opportunity(self):
        return self._invocation.opportunity

    @property
    def recent_self_sent(self) -> tuple[SelfSentMessage, ...]:
        self._require("chat.read")
        return self._invocation.recent_self_sent

    @property
    def settlements(self) -> tuple[Settlement, ...]:
        self._require("chat.read")
        return self._invocation.settlements

    @property
    def storage(self) -> SessionStorage:
        self._require("storage.session")
        return self._storage

    def generate(self, prompt: str) -> str:
        self._require("llm.generate")
        return self._llm.generate(prompt)


class HostStub:
    """In-memory host for replay; no accounts, network, files, or platform APIs."""

    __slots__ = ("_capabilities", "_clock", "_llm", "_storage", "_storage_max_bytes")

    def __init__(
        self,
        *,
        capabilities: Iterable[str] = (),
        llm: Llm | None = None,
        storage_max_bytes: int = 64 * 1024,
        clock: ReplayClock | None = None,
    ) -> None:
        selected = frozenset(capabilities)
        if not selected.issubset(SUPPORTED_CAPABILITIES):
            raise ValueError("HostStub capabilities contain an unsupported value")
        self._capabilities = selected
        self._llm = llm or MockLlm()
        self._storage: dict[str, SessionStorage] = {}
        self._storage_max_bytes = storage_max_bytes
        self._clock = clock or ReplayClock()

    def context_for(self, invocation: Invocation) -> PluginContext:
        storage = self._storage.get(invocation.session_id)
        if storage is None:
            storage = SessionStorage(
                invocation.session_id, max_bytes=self._storage_max_bytes
            )
            self._storage[invocation.session_id] = storage
        return PluginContext(
            _invocation=invocation,
            _capabilities=self._capabilities,
            _storage=storage,
            _llm=self._llm,
            clock=self._clock,
        )


class _RemoteLlm:
    __slots__ = ("_client",)

    def __init__(self, client: HostRpcClient) -> None:
        self._client = client

    def generate(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16_000:
            raise ValueError("LLM prompt is invalid or exceeds its size limit")
        result = self._client.call(
            "llm.generate",
            "llm.generate.generate",
            {"prompt": prompt},
        )
        if not isinstance(result, str) or len(result) > MAX_CANDIDATE_CHARS:
            raise ValueError("host LLM response is invalid or too large")
        return result


class _RemoteSessionStorage:
    __slots__ = ("_client",)

    def __init__(self, client: HostRpcClient) -> None:
        self._client = client

    def get(self, key: str, default: object = None) -> object:
        SessionStorage._validate_key(key)
        result = self._client.call(
            "storage.session",
            "storage.session.get",
            {"key": key},
        )
        return default if result is None else result

    def set(self, key: str, value: object) -> None:
        SessionStorage._validate_key(key)
        normalized = SessionStorage._normalize(value, max_bytes=64 * 1024)
        self._client.call(
            "storage.session",
            "storage.session.set",
            {"key": key, "value": normalized},
        )

    def delete(self, key: str) -> bool:
        SessionStorage._validate_key(key)
        result = self._client.call(
            "storage.session",
            "storage.session.delete",
            {"key": key},
        )
        if type(result) is not bool:
            raise ValueError("host session storage returned an invalid result")
        return result


def remote_context(
    invocation: Invocation,
    *,
    capabilities: Iterable[str],
    transport: CapabilityTransport,
    clock: ReplayClock | None = None,
) -> PluginContext:
    """Create one Worker context whose optional services use host RPC only."""

    if not isinstance(invocation, Invocation):
        raise TypeError("Worker context requires a protocol Invocation")
    selected = frozenset(capabilities)
    if not selected.issubset(SUPPORTED_CAPABILITIES):
        raise ValueError("Worker context capabilities contain an unsupported value")
    client = HostRpcClient(transport)
    return PluginContext(
        _invocation=invocation,
        _capabilities=selected,
        _storage=_RemoteSessionStorage(client),
        _llm=_RemoteLlm(client),
        clock=clock or ReplayClock(),
    )


__all__ = [
    "CapabilityCallError",
    "CapabilityDeniedError",
    "CapabilityTransport",
    "HostRpcClient",
    "HostStub",
    "MockLlm",
    "PluginContext",
    "SessionStorage",
    "remote_context",
]
