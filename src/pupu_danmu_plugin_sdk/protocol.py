"""Bounded, immutable protocol DTOs shared by the host and plugin SDK.

Viewer statements and plugin-provided fact classifications are untrusted
context. Nothing in this module creates verified product facts or authorizes a
candidate to be sent; those decisions remain host-owned.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

PROTOCOL_VERSION = 3
MAX_MESSAGE_BYTES = 128 * 1024
MAX_VIEWER_MESSAGES = 50
MAX_SELF_SENT_MESSAGES = 10
MAX_SETTLEMENTS = 10
MAX_EVIDENCE_ITEMS = 50
MAX_SESSION_OPTIONS = 32
MAX_CANDIDATE_CHARS = 1000
MAX_TEXT_CHARS = 4000
MAX_CLAIMS = 32
MAX_TAGS = 32
MAX_JSON_DEPTH = 16
MAX_JSON_NODES = 4096
SUPPORTED_CAPABILITIES = frozenset(
    {
        "chat.read",
        "room.read",
        "session.config.read",
        "llm.generate",
        "storage.session",
    }
)
_CAPABILITY_METHODS = {
    "llm.generate.generate": "llm.generate",
    "storage.session.get": "storage.session",
    "storage.session.set": "storage.session",
    "storage.session.delete": "storage.session",
}

_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class PluginProtocolError(ValueError):
    """An IPC message is malformed, unsupported, or exceeds its limits."""


class TrustLevel(StrEnum):
    """Trust labels available in protocol v3; claims are always untrusted."""

    UNTRUSTED = "untrusted"


class EvidenceSource(StrEnum):
    """Provenance labels for low-trust context, not product verification."""

    VIEWER_MESSAGE = "viewer_message"
    ROOM_TITLE = "room_title"
    SESSION_THEME = "session_theme"
    UNKNOWN = "unknown"


class OpportunityMode(StrEnum):
    CONTEXTUAL_FOLLOWUP = "contextual_followup"
    SAFE_INITIATIVE = "safe_initiative"


class SettlementOutcome(StrEnum):
    SUBMITTED = "submitted"
    FAILED = "failed"
    DROPPED = "dropped"


@dataclass(frozen=True, slots=True)
class ViewerMessage:
    """One anonymous viewer message with its host-observed timestamp."""

    message_id: str
    text: str
    received_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "message_id", _text(self.message_id, "message_id", 128)
        )
        object.__setattr__(
            self, "text", _text(self.text, "viewer text", MAX_TEXT_CHARS)
        )
        object.__setattr__(
            self, "received_at", _timestamp(self.received_at, "received_at")
        )


@dataclass(frozen=True, slots=True)
class ViewerChatSnapshot:
    """Newest at most 50 external viewer messages, ordered by receive time."""

    messages: tuple[ViewerMessage, ...] = ()

    def __post_init__(self) -> None:
        messages = tuple(self.messages)
        if len(messages) > MAX_VIEWER_MESSAGES:
            raise PluginProtocolError("viewer snapshot exceeds its message limit")
        if not all(isinstance(message, ViewerMessage) for message in messages):
            raise PluginProtocolError("viewer snapshot contains an invalid message")
        if len({message.message_id for message in messages}) != len(messages):
            raise PluginProtocolError("viewer message ids must be unique")
        if tuple(sorted(messages, key=lambda message: message.received_at)) != messages:
            raise PluginProtocolError("viewer messages must be ordered by timestamp")
        object.__setattr__(self, "messages", messages)

    @classmethod
    def from_messages(cls, messages: Iterable[ViewerMessage]) -> ViewerChatSnapshot:
        try:
            items = tuple(messages)
        except TypeError:
            raise PluginProtocolError("viewer messages must be iterable DTOs") from None
        if not all(isinstance(message, ViewerMessage) for message in items):
            raise PluginProtocolError("viewer snapshot contains an invalid message")
        ordered = sorted(items, key=lambda message: message.received_at)
        return cls(tuple(ordered[-MAX_VIEWER_MESSAGES:]))


@dataclass(frozen=True, slots=True)
class RoomEvidence:
    """Unverified room/viewer context; this type cannot represent verified facts."""

    text: str
    source: EvidenceSource
    source_id: str = ""
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "text", _text(self.text, "evidence text", MAX_TEXT_CHARS)
        )
        try:
            source = EvidenceSource(self.source)
        except ValueError:
            raise PluginProtocolError("unsupported evidence source") from None
        object.__setattr__(self, "source", source)
        object.__setattr__(
            self, "source_id", _optional_text(self.source_id, "source_id", 128)
        )
        if self.observed_at is not None:
            object.__setattr__(
                self, "observed_at", _timestamp(self.observed_at, "observed_at")
            )

    @property
    def trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED


@dataclass(frozen=True, slots=True)
class SessionFocus:
    """Host-derived conversational focus without a verified product-fact flag."""

    current_focus: str = ""
    focus_confidence: float = 0.0
    question_intent: str = "unknown"
    asked_attributes: tuple[str, ...] = ()
    answered_evidence: tuple[RoomEvidence, ...] = ()
    last_topic_shift_at: datetime | None = None
    time_since_last_external_message_seconds: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "current_focus",
            _optional_text(self.current_focus, "current_focus", 200),
        )
        confidence = _finite_number(self.focus_confidence, "focus_confidence")
        if not 0 <= confidence <= 1:
            raise PluginProtocolError("focus_confidence must be between zero and one")
        object.__setattr__(self, "focus_confidence", confidence)
        object.__setattr__(
            self, "question_intent", _text(self.question_intent, "question_intent", 64)
        )
        object.__setattr__(
            self,
            "asked_attributes",
            _text_tuple(self.asked_attributes, "asked_attributes", 32, 128),
        )
        evidence = tuple(self.answered_evidence)
        if len(evidence) > MAX_EVIDENCE_ITEMS or not all(
            isinstance(item, RoomEvidence) for item in evidence
        ):
            raise PluginProtocolError(
                "answered evidence is invalid or exceeds its limit"
            )
        object.__setattr__(self, "answered_evidence", evidence)
        if self.last_topic_shift_at is not None:
            object.__setattr__(
                self,
                "last_topic_shift_at",
                _timestamp(self.last_topic_shift_at, "last_topic_shift_at"),
            )
        idle = _finite_number(
            self.time_since_last_external_message_seconds,
            "time_since_last_external_message_seconds",
        )
        if idle < 0:
            raise PluginProtocolError("idle duration cannot be negative")
        object.__setattr__(self, "time_since_last_external_message_seconds", idle)


@dataclass(frozen=True, slots=True)
class SessionConfiguration:
    """User-selected plugin settings, separate from host-derived room focus.

    The host must validate options against the installed manifest schema and
    project this DTO only when ``session.config.read`` is granted. These values
    do not grant capabilities or represent verified product facts.
    """

    persona_id: str = ""
    options: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        persona_id = _optional_text(self.persona_id, "persona_id", 128)
        if persona_id and not _IDENTIFIER.fullmatch(persona_id):
            raise PluginProtocolError("persona_id is invalid")
        if not isinstance(self.options, Mapping):
            raise PluginProtocolError("options must be an object")
        if len(self.options) > MAX_SESSION_OPTIONS:
            raise PluginProtocolError("session configuration exceeds its option limit")
        if not all(
            isinstance(key, str) and _CODE.fullmatch(key) for key in self.options
        ):
            raise PluginProtocolError("session configuration option key is invalid")
        frozen = _freeze_json(self.options)
        _check_json_tree(frozen)
        object.__setattr__(self, "persona_id", persona_id)
        object.__setattr__(self, "options", frozen)


@dataclass(frozen=True, slots=True)
class Opportunity:
    """A host-issued content opportunity; it never authorizes sending."""

    mode: OpportunityMode | str
    available: bool
    reason: str = ""

    def __post_init__(self) -> None:
        try:
            mode = OpportunityMode(self.mode)
        except ValueError:
            raise PluginProtocolError("unsupported opportunity mode") from None
        if type(self.available) is not bool:
            raise PluginProtocolError("opportunity available must be a boolean")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(
            self, "reason", _optional_text(self.reason, "opportunity reason", 128)
        )


@dataclass(frozen=True, slots=True)
class SelfSentMessage:
    """Host-confirmed self-sent context, kept separate from viewer messages."""

    text: str
    sent_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "text", _text(self.text, "self-sent text", MAX_TEXT_CHARS)
        )
        object.__setattr__(self, "sent_at", _timestamp(self.sent_at, "sent_at"))


@dataclass(frozen=True, slots=True)
class Settlement:
    """Host-owned result of a prior candidate submission."""

    candidate_id: str
    outcome: SettlementOutcome | str
    settled_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "candidate_id", _text(self.candidate_id, "candidate_id", 128)
        )
        try:
            outcome = SettlementOutcome(self.outcome)
        except ValueError:
            raise PluginProtocolError("unsupported settlement outcome") from None
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(
            self, "settled_at", _timestamp(self.settled_at, "settled_at")
        )


@dataclass(frozen=True, slots=True)
class Invocation:
    """Host-created identity and bounded context for one Worker invocation."""

    invocation_id: str
    session_id: str
    run_id: str
    capture_id: str
    revision: int
    viewer_chat: ViewerChatSnapshot
    session_focus: SessionFocus
    opportunity: Opportunity
    session_configuration: SessionConfiguration = field(
        default_factory=SessionConfiguration
    )
    room_evidence: tuple[RoomEvidence, ...] = ()
    recent_self_sent: tuple[SelfSentMessage, ...] = ()
    settlements: tuple[Settlement, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("invocation_id", "session_id", "run_id", "capture_id"):
            value = _text(getattr(self, field_name), field_name, 128)
            if not _IDENTIFIER.fullmatch(value):
                raise PluginProtocolError(f"{field_name} is invalid")
            object.__setattr__(self, field_name, value)
        if type(self.revision) is not int or self.revision < 0:
            raise PluginProtocolError("revision must be a non-negative integer")
        if not isinstance(self.viewer_chat, ViewerChatSnapshot):
            raise PluginProtocolError("viewer_chat is invalid")
        if not isinstance(self.session_focus, SessionFocus):
            raise PluginProtocolError("session_focus is invalid")
        if not isinstance(self.opportunity, Opportunity):
            raise PluginProtocolError("opportunity is invalid")
        if not isinstance(self.session_configuration, SessionConfiguration):
            raise PluginProtocolError("session_configuration is invalid")
        room_evidence = tuple(self.room_evidence)
        if len(room_evidence) > MAX_EVIDENCE_ITEMS or not all(
            isinstance(item, RoomEvidence) for item in room_evidence
        ):
            raise PluginProtocolError("room evidence is invalid or exceeds its limit")
        self_sent = tuple(self.recent_self_sent)
        if len(self_sent) > MAX_SELF_SENT_MESSAGES or not all(
            isinstance(item, SelfSentMessage) for item in self_sent
        ):
            raise PluginProtocolError(
                "self-sent history is invalid or exceeds its limit"
            )
        settlements = tuple(self.settlements)
        if len(settlements) > MAX_SETTLEMENTS or not all(
            isinstance(item, Settlement) for item in settlements
        ):
            raise PluginProtocolError("settlements are invalid or exceed their limit")
        object.__setattr__(self, "room_evidence", room_evidence)
        object.__setattr__(self, "recent_self_sent", self_sent)
        object.__setattr__(self, "settlements", settlements)


@dataclass(frozen=True, slots=True)
class PluginFactClaim:
    """Plugin classification/evidence hint; always untrusted and non-authoritative."""

    classification: str
    claim: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "classification", _text(self.classification, "classification", 64)
        )
        object.__setattr__(
            self, "claim", _text(self.claim, "claim", MAX_CANDIDATE_CHARS)
        )
        refs = _text_tuple(self.evidence_refs, "evidence_refs", 16, 128)
        object.__setattr__(self, "evidence_refs", refs)

    @property
    def trust_level(self) -> TrustLevel:
        return TrustLevel.UNTRUSTED


@dataclass(frozen=True, slots=True)
class Candidate:
    """A candidate string; acceptance and sending remain host-owned."""

    text: str
    fact_claims: tuple[PluginFactClaim, ...] = ()
    semantic_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "text", _text(self.text, "candidate text", MAX_CANDIDATE_CHARS)
        )
        claims = tuple(self.fact_claims)
        if len(claims) > MAX_CLAIMS or not all(
            isinstance(item, PluginFactClaim) for item in claims
        ):
            raise PluginProtocolError(
                "candidate fact claims are invalid or exceed their limit"
            )
        object.__setattr__(self, "fact_claims", claims)
        object.__setattr__(
            self,
            "semantic_tags",
            _text_tuple(self.semantic_tags, "semantic_tags", MAX_TAGS, 64),
        )


@dataclass(frozen=True, slots=True)
class Silent:
    """No candidate is available for this invocation."""

    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason", _text(self.reason, "silent reason", 128))


@dataclass(frozen=True, slots=True)
class TypedFailure:
    """Sanitized failure code without exception text or user data."""

    code: str
    retryable: bool = False

    def __post_init__(self) -> None:
        code = _text(self.code, "failure code", 64)
        if not _CODE.fullmatch(code):
            raise PluginProtocolError("failure code is invalid")
        if type(self.retryable) is not bool:
            raise PluginProtocolError("retryable must be a boolean")
        object.__setattr__(self, "code", code)


type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | tuple[JsonValue, ...] | Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class CapabilityCall:
    """One broker call for a declared capability; no direct host handles."""

    request_id: str
    capability: str
    method: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        request_id = _text(self.request_id, "request_id", 128)
        if not _IDENTIFIER.fullmatch(request_id):
            raise PluginProtocolError("request_id is invalid")
        capability = _text(self.capability, "capability", 64)
        if capability not in SUPPORTED_CAPABILITIES:
            raise PluginProtocolError("unsupported capability")
        method = _text(self.method, "method", 64)
        required_capability = _CAPABILITY_METHODS.get(method)
        if required_capability is None:
            raise PluginProtocolError("unsupported method")
        if capability != required_capability:
            raise PluginProtocolError("capability does not match method")
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "capability", capability)
        object.__setattr__(self, "method", method)
        if not isinstance(self.payload, Mapping):
            raise PluginProtocolError("capability payload must be an object")
        frozen = _freeze_json(self.payload)
        _check_json_tree(frozen)
        object.__setattr__(self, "payload", frozen)


@dataclass(frozen=True, slots=True)
class CapabilityResponse:
    """One broker response, correlated only by the RPC request id."""

    request_id: str
    success: bool
    result: JsonValue = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        request_id = _text(self.request_id, "request_id", 128)
        if not _IDENTIFIER.fullmatch(request_id):
            raise PluginProtocolError("request_id is invalid")
        if type(self.success) is not bool:
            raise PluginProtocolError("success must be a boolean")
        if self.success:
            if self.error_code is not None:
                raise PluginProtocolError("response branches are mutually exclusive")
            result = _freeze_json(self.result)
            _check_json_tree(result)
            object.__setattr__(self, "result", result)
        else:
            if self.result is not None or self.error_code is None:
                raise PluginProtocolError("response branches are mutually exclusive")
            error_code = _text(self.error_code, "error_code", 64)
            if not _CODE.fullmatch(error_code):
                raise PluginProtocolError("error_code is invalid")
            object.__setattr__(self, "result", None)
            object.__setattr__(self, "error_code", error_code)
        object.__setattr__(self, "request_id", request_id)


@dataclass(frozen=True, slots=True)
class WorkerCancellation:
    """Host control message that cancels one active invocation."""

    invocation_id: str

    def __post_init__(self) -> None:
        invocation_id = _text(self.invocation_id, "invocation_id", 128)
        if not _IDENTIFIER.fullmatch(invocation_id):
            raise PluginProtocolError("invocation_id is invalid")
        object.__setattr__(self, "invocation_id", invocation_id)


type WorkerOutcome = Candidate | Silent | TypedFailure


def encode_capability_call(call: CapabilityCall) -> bytes:
    """Encode a host broker request without invocation identity."""

    if not isinstance(call, CapabilityCall):
        raise PluginProtocolError("capability call must use the protocol DTO")
    return _encode_json(
        {
            "protocol_version": PROTOCOL_VERSION,
            "type": "capability_call",
            "request_id": call.request_id,
            "capability": call.capability,
            "method": call.method,
            "payload": _json_value(call.payload),
        }
    )


def decode_capability_call(
    payload: bytes | str | Mapping[str, object],
) -> CapabilityCall:
    """Decode a broker request with exact top-level and method validation."""

    raw = _load_json(payload)
    fields = {
        "protocol_version",
        "type",
        "request_id",
        "capability",
        "method",
        "payload",
    }
    _keys(raw, fields, required=fields)
    _version_and_type(raw, "capability_call")
    call_payload = raw["payload"]
    if not isinstance(call_payload, Mapping):
        raise PluginProtocolError("capability payload must be an object")
    return CapabilityCall(
        request_id=_string(raw["request_id"], "request_id"),
        capability=_string(raw["capability"], "capability"),
        method=_string(raw["method"], "method"),
        payload=call_payload,
    )


def encode_capability_response(response: CapabilityResponse) -> bytes:
    """Encode one success or stable error response without invocation identity."""

    if not isinstance(response, CapabilityResponse):
        raise PluginProtocolError("capability response must use the protocol DTO")
    value: dict[str, object] = {
        "protocol_version": PROTOCOL_VERSION,
        "type": "capability_response",
        "request_id": response.request_id,
        "success": response.success,
    }
    if response.success:
        value["result"] = _json_value(response.result)
    else:
        value["error_code"] = response.error_code
    return _encode_json(value)


def decode_capability_response(
    payload: bytes | str | Mapping[str, object],
    *,
    expected_request_id: str | None = None,
) -> CapabilityResponse:
    """Decode a broker response and optionally enforce request correlation."""

    raw = _load_json(payload)
    allowed = {
        "protocol_version",
        "type",
        "request_id",
        "success",
        "result",
        "error_code",
    }
    required = {"protocol_version", "type", "request_id", "success"}
    _keys(raw, allowed, required)
    _version_and_type(raw, "capability_response")
    request_id = _string(raw["request_id"], "request_id")
    if expected_request_id is not None and request_id != expected_request_id:
        raise PluginProtocolError("capability response request_id mismatch")
    success = _boolean(raw["success"], "success")
    if success:
        if "result" not in raw or "error_code" in raw:
            raise PluginProtocolError("response branches are mutually exclusive")
        return CapabilityResponse(
            request_id=request_id,
            success=True,
            result=raw["result"],  # type: ignore[arg-type]
        )
    if "error_code" not in raw or "result" in raw:
        raise PluginProtocolError("response branches are mutually exclusive")
    return CapabilityResponse(
        request_id=request_id,
        success=False,
        error_code=_string(raw["error_code"], "error_code"),
    )


def encode_worker_cancellation(cancellation: WorkerCancellation) -> bytes:
    """Encode a bounded host cancellation notification for the current Worker."""

    if not isinstance(cancellation, WorkerCancellation):
        raise PluginProtocolError("cancellation must use the protocol DTO")
    return _encode_json(
        {
            "protocol_version": PROTOCOL_VERSION,
            "type": "cancel",
            "invocation_id": cancellation.invocation_id,
        }
    )


def decode_worker_cancellation(
    payload: bytes | str | Mapping[str, object],
) -> WorkerCancellation:
    """Decode a strict cancellation message without session or run authority."""

    raw = _load_json(payload)
    fields = {"protocol_version", "type", "invocation_id"}
    _keys(raw, fields, required=fields)
    _version_and_type(raw, "cancel")
    return WorkerCancellation(_string(raw["invocation_id"], "invocation_id"))


def encode_invocation(invocation: Invocation) -> bytes:
    """Encode a host-created invocation to bounded UTF-8 JSON."""

    if not isinstance(invocation, Invocation):
        raise PluginProtocolError("invocation must use the protocol DTO")
    value = {
        "protocol_version": PROTOCOL_VERSION,
        "type": "invocation",
        "invocation_id": invocation.invocation_id,
        "session_id": invocation.session_id,
        "run_id": invocation.run_id,
        "capture_id": invocation.capture_id,
        "revision": invocation.revision,
        "viewer_chat": {
            "messages": [
                _viewer_message_to_json(item)
                for item in invocation.viewer_chat.messages
            ]
        },
        "session_focus": _session_focus_to_json(invocation.session_focus),
        "session_configuration": _session_configuration_to_json(
            invocation.session_configuration
        ),
        "opportunity": {
            "mode": invocation.opportunity.mode.value,
            "available": invocation.opportunity.available,
            "reason": invocation.opportunity.reason,
        },
        "room_evidence": [
            _room_evidence_to_json(item) for item in invocation.room_evidence
        ],
        "recent_self_sent": [
            _self_sent_to_json(item) for item in invocation.recent_self_sent
        ],
        "settlements": [_settlement_to_json(item) for item in invocation.settlements],
    }
    return _encode_json(value)


def decode_invocation(payload: bytes | str | Mapping[str, object]) -> Invocation:
    """Decode a host invocation with exact field and size validation."""

    raw = _load_json(payload)
    _keys(
        raw,
        {
            "protocol_version",
            "type",
            "invocation_id",
            "session_id",
            "run_id",
            "capture_id",
            "revision",
            "viewer_chat",
            "session_focus",
            "session_configuration",
            "opportunity",
            "room_evidence",
            "recent_self_sent",
            "settlements",
        },
        required={
            "protocol_version",
            "type",
            "invocation_id",
            "session_id",
            "run_id",
            "capture_id",
            "revision",
            "viewer_chat",
            "session_focus",
            "session_configuration",
            "opportunity",
        },
    )
    _version_and_type(raw, "invocation")
    viewer = _object(raw["viewer_chat"], {"messages"}, {"messages"}, "viewer_chat")
    focus = _object(
        raw["session_focus"],
        {
            "current_focus",
            "focus_confidence",
            "question_intent",
            "asked_attributes",
            "answered_evidence",
            "last_topic_shift_at",
            "time_since_last_external_message_seconds",
        },
        {
            "current_focus",
            "focus_confidence",
            "question_intent",
            "asked_attributes",
            "answered_evidence",
            "last_topic_shift_at",
            "time_since_last_external_message_seconds",
        },
        "session_focus",
    )
    opportunity = _object(
        raw["opportunity"],
        {"mode", "available", "reason"},
        {"mode", "available"},
        "opportunity",
    )
    session_configuration = _session_configuration_from_json(
        raw["session_configuration"]
    )
    messages = tuple(
        _viewer_message_from_json(item)
        for item in _array(viewer["messages"], MAX_VIEWER_MESSAGES, "messages")
    )
    room_evidence = tuple(
        _room_evidence_from_json(item)
        for item in _array(
            raw.get("room_evidence", []), MAX_EVIDENCE_ITEMS, "room_evidence"
        )
    )
    self_sent = tuple(
        _self_sent_from_json(item)
        for item in _array(
            raw.get("recent_self_sent", []), MAX_SELF_SENT_MESSAGES, "recent_self_sent"
        )
    )
    settlements = tuple(
        _settlement_from_json(item)
        for item in _array(raw.get("settlements", []), MAX_SETTLEMENTS, "settlements")
    )
    return Invocation(
        invocation_id=_string(raw["invocation_id"], "invocation_id"),
        session_id=_string(raw["session_id"], "session_id"),
        run_id=_string(raw["run_id"], "run_id"),
        capture_id=_string(raw["capture_id"], "capture_id"),
        revision=_integer(raw["revision"], "revision", minimum=0),
        viewer_chat=ViewerChatSnapshot(messages),
        session_focus=SessionFocus(
            current_focus=_string(
                focus["current_focus"], "current_focus", allow_empty=True
            ),
            focus_confidence=_number(focus["focus_confidence"], "focus_confidence"),
            question_intent=_string(focus["question_intent"], "question_intent"),
            asked_attributes=_string_list(
                focus["asked_attributes"], 32, "asked_attributes", 128
            ),
            answered_evidence=tuple(
                _room_evidence_from_json(item)
                for item in _array(
                    focus["answered_evidence"], MAX_EVIDENCE_ITEMS, "answered_evidence"
                )
            ),
            last_topic_shift_at=_optional_timestamp(
                focus["last_topic_shift_at"], "last_topic_shift_at"
            ),
            time_since_last_external_message_seconds=_number(
                focus["time_since_last_external_message_seconds"],
                "time_since_last_external_message_seconds",
            ),
        ),
        opportunity=Opportunity(
            mode=_string(opportunity["mode"], "opportunity mode"),
            available=_boolean(opportunity["available"], "opportunity available"),
            reason=_string(
                opportunity.get("reason", ""), "opportunity reason", allow_empty=True
            ),
        ),
        session_configuration=session_configuration,
        room_evidence=room_evidence,
        recent_self_sent=self_sent,
        settlements=settlements,
    )


def encode_worker_outcome(outcome: WorkerOutcome) -> bytes:
    """Encode a result payload without authoritative invocation identity."""

    if isinstance(outcome, Candidate):
        value = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "candidate",
            "text": outcome.text,
            "fact_claims": [
                {
                    "classification": claim.classification,
                    "claim": claim.claim,
                    "evidence_refs": list(claim.evidence_refs),
                }
                for claim in outcome.fact_claims
            ],
            "semantic_tags": list(outcome.semantic_tags),
        }
    elif isinstance(outcome, Silent):
        value = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "silent",
            "reason": outcome.reason,
        }
    elif isinstance(outcome, TypedFailure):
        value = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "failure",
            "code": outcome.code,
            "retryable": outcome.retryable,
        }
    else:
        raise PluginProtocolError("unsupported Worker outcome")
    return _encode_json(value)


def decode_worker_outcome(payload: bytes | str | Mapping[str, object]) -> WorkerOutcome:
    """Decode a Worker result; Run/Capture/revision identity is never accepted."""

    raw = _load_json(payload)
    message_type = raw.get("type")
    if message_type == "candidate":
        _keys(
            raw,
            {"protocol_version", "type", "text", "fact_claims", "semantic_tags"},
            required={"protocol_version", "type", "text"},
        )
        _version_and_type(raw, "candidate")
        claims_value = _array(raw.get("fact_claims", []), MAX_CLAIMS, "fact_claims")
        claims: list[PluginFactClaim] = []
        for item in claims_value:
            claim = _object(
                item,
                {"classification", "claim", "evidence_refs"},
                {"classification", "claim"},
                "fact claim",
            )
            claims.append(
                PluginFactClaim(
                    classification=_string(claim["classification"], "classification"),
                    claim=_string(claim["claim"], "claim"),
                    evidence_refs=_string_list(
                        claim.get("evidence_refs", []), 16, "evidence_refs", 128
                    ),
                )
            )
        tags = _string_list(raw.get("semantic_tags", []), MAX_TAGS, "semantic_tags", 64)
        return Candidate(
            text=_string(raw["text"], "candidate text"),
            fact_claims=tuple(claims),
            semantic_tags=tags,
        )
    if message_type == "silent":
        _keys(
            raw,
            {"protocol_version", "type", "reason"},
            required={"protocol_version", "type", "reason"},
        )
        _version_and_type(raw, "silent")
        return Silent(_string(raw["reason"], "silent reason"))
    if message_type == "failure":
        _keys(
            raw,
            {"protocol_version", "type", "code", "retryable"},
            required={"protocol_version", "type", "code", "retryable"},
        )
        _version_and_type(raw, "failure")
        return TypedFailure(
            code=_string(raw["code"], "failure code"),
            retryable=_boolean(raw["retryable"], "retryable"),
        )
    raise PluginProtocolError("unsupported Worker outcome type")


def _viewer_message_to_json(message: ViewerMessage) -> dict[str, object]:
    return {
        "message_id": message.message_id,
        "text": message.text,
        "received_at": message.received_at.isoformat(),
    }


def _viewer_message_from_json(value: object) -> ViewerMessage:
    raw = _object(
        value,
        {"message_id", "text", "received_at"},
        {"message_id", "text", "received_at"},
        "viewer message",
    )
    return ViewerMessage(
        message_id=_string(raw["message_id"], "message_id"),
        text=_string(raw["text"], "viewer text"),
        received_at=_parse_timestamp(raw["received_at"], "received_at"),
    )


def _room_evidence_to_json(item: RoomEvidence) -> dict[str, object]:
    return {
        "text": item.text,
        "source": item.source.value,
        "source_id": item.source_id,
        "observed_at": None
        if item.observed_at is None
        else item.observed_at.isoformat(),
    }


def _room_evidence_from_json(value: object) -> RoomEvidence:
    raw = _object(
        value,
        {"text", "source", "source_id", "observed_at"},
        {"text", "source"},
        "room evidence",
    )
    return RoomEvidence(
        text=_string(raw["text"], "evidence text"),
        source=_string(raw["source"], "evidence source"),
        source_id=_string(raw.get("source_id", ""), "source_id", allow_empty=True),
        observed_at=_optional_timestamp(raw.get("observed_at"), "observed_at"),
    )


def _session_focus_to_json(focus: SessionFocus) -> dict[str, object]:
    return {
        "current_focus": focus.current_focus,
        "focus_confidence": focus.focus_confidence,
        "question_intent": focus.question_intent,
        "asked_attributes": list(focus.asked_attributes),
        "answered_evidence": [
            _room_evidence_to_json(item) for item in focus.answered_evidence
        ],
        "last_topic_shift_at": None
        if focus.last_topic_shift_at is None
        else focus.last_topic_shift_at.isoformat(),
        "time_since_last_external_message_seconds": focus.time_since_last_external_message_seconds,
    }


def _session_configuration_to_json(
    configuration: SessionConfiguration,
) -> dict[str, object]:
    return {
        "persona_id": configuration.persona_id,
        "options": _json_value(configuration.options),
    }


def _session_configuration_from_json(value: object) -> SessionConfiguration:
    raw = _object(
        value,
        {"persona_id", "options"},
        {"persona_id", "options"},
        "session_configuration",
    )
    return SessionConfiguration(
        persona_id=_optional_text(raw["persona_id"], "persona_id", 128),
        options=raw["options"],  # type: ignore[arg-type]
    )


def _self_sent_to_json(item: SelfSentMessage) -> dict[str, object]:
    return {"text": item.text, "sent_at": item.sent_at.isoformat()}


def _self_sent_from_json(value: object) -> SelfSentMessage:
    raw = _object(value, {"text", "sent_at"}, {"text", "sent_at"}, "self-sent message")
    return SelfSentMessage(
        text=_string(raw["text"], "self-sent text"),
        sent_at=_parse_timestamp(raw["sent_at"], "sent_at"),
    )


def _settlement_to_json(item: Settlement) -> dict[str, object]:
    return {
        "candidate_id": item.candidate_id,
        "outcome": item.outcome.value,
        "settled_at": item.settled_at.isoformat(),
    }


def _settlement_from_json(value: object) -> Settlement:
    raw = _object(
        value,
        {"candidate_id", "outcome", "settled_at"},
        {"candidate_id", "outcome", "settled_at"},
        "settlement",
    )
    return Settlement(
        candidate_id=_string(raw["candidate_id"], "candidate_id"),
        outcome=_string(raw["outcome"], "settlement outcome"),
        settled_at=_parse_timestamp(raw["settled_at"], "settled_at"),
    )


def _encode_json(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise PluginProtocolError("protocol message cannot be encoded") from None
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise PluginProtocolError("protocol message exceeds its size limit")
    return encoded


def _load_json(payload: bytes | str | Mapping[str, object]) -> dict[str, object]:
    if isinstance(payload, Mapping):
        value: object = payload
    else:
        if isinstance(payload, str):
            encoded = payload.encode("utf-8")
        elif isinstance(payload, bytes):
            encoded = payload
        else:
            raise PluginProtocolError("protocol payload must be JSON data")
        if len(encoded) > MAX_MESSAGE_BYTES:
            raise PluginProtocolError("protocol message exceeds its size limit")

        def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in pairs:
                if key in result:
                    raise PluginProtocolError(
                        "protocol object contains a duplicate field"
                    )
                result[key] = item
            return result

        try:
            value = json.loads(
                encoded.decode("utf-8"),
                object_pairs_hook=unique_pairs,
                parse_constant=lambda _value: (_ for _ in ()).throw(
                    PluginProtocolError("protocol contains a non-finite number")
                ),
            )
        except PluginProtocolError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            raise PluginProtocolError(
                "protocol payload is not valid UTF-8 JSON"
            ) from None
    _check_json_tree(value)
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise PluginProtocolError("protocol message root must be an object")
    return dict(value)


def _check_json_tree(
    value: object, *, depth: int = 0, count: list[int] | None = None
) -> None:
    if count is None:
        count = [0]
    count[0] += 1
    if depth > MAX_JSON_DEPTH or count[0] > MAX_JSON_NODES:
        raise PluginProtocolError("protocol nesting or item count exceeds the limit")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 128:
                raise PluginProtocolError("protocol object key is invalid")
            _check_json_tree(item, depth=depth + 1, count=count)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_json_tree(item, depth=depth + 1, count=count)
    elif isinstance(value, str) and len(value) > MAX_MESSAGE_BYTES:
        raise PluginProtocolError("protocol string exceeds its size limit")
    elif isinstance(value, float) and not math.isfinite(value):
        raise PluginProtocolError("protocol contains a non-finite number")
    elif value is not None and type(value) not in {bool, int, float, str}:
        raise PluginProtocolError("protocol contains a non-JSON value")


def _keys(value: Mapping[str, object], allowed: set[str], required: set[str]) -> None:
    if not set(value).issubset(allowed) or not required.issubset(value):
        raise PluginProtocolError("protocol contains missing or unsupported fields")


def _object(
    value: object, allowed: set[str], required: set[str], name: str
) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise PluginProtocolError(f"{name} must be an object")
    _keys(value, allowed, required)
    return dict(value)


def _version_and_type(raw: Mapping[str, object], expected: str) -> None:
    if (
        raw.get("protocol_version") != PROTOCOL_VERSION
        or type(raw.get("protocol_version")) is not int
    ):
        raise PluginProtocolError("unsupported protocol version")
    if raw.get("type") != expected:
        raise PluginProtocolError("unexpected protocol message type")


def _array(value: object, maximum: int, name: str) -> list[object]:
    if not isinstance(value, list) or len(value) > maximum:
        raise PluginProtocolError(f"{name} must be a bounded array")
    return value


def _string_list(
    value: object, maximum: int, name: str, item_maximum: int
) -> tuple[str, ...]:
    items = _array(value, maximum, name)
    result = tuple(_text(item, name, item_maximum) for item in items)
    if len(set(result)) != len(result):
        raise PluginProtocolError(f"{name} must contain unique values")
    return result


def _text_tuple(
    value: object, name: str, maximum: int, item_maximum: int
) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)) or len(value) > maximum:
        raise PluginProtocolError(f"{name} must be a bounded sequence")
    result = tuple(_text(item, name, item_maximum) for item in value)
    if len(set(result)) != len(result):
        raise PluginProtocolError(f"{name} must contain unique values")
    return result


def _text(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise PluginProtocolError(f"{name} must be text")
    text = value.strip()
    if not text or len(text) > maximum or "\x00" in text:
        raise PluginProtocolError(f"{name} is empty or exceeds its limit")
    return text


def _optional_text(value: object, name: str, maximum: int) -> str:
    if value == "":
        return ""
    return _text(value, name, maximum)


def _timestamp(value: object, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise PluginProtocolError(f"{name} must be a timezone-aware timestamp")
    return value.astimezone(UTC)


def _parse_timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise PluginProtocolError(f"{name} must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise PluginProtocolError(f"{name} must be an ISO timestamp") from None
    return _timestamp(parsed, name)


def _optional_timestamp(value: object, name: str) -> datetime | None:
    return None if value is None else _parse_timestamp(value, name)


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PluginProtocolError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise PluginProtocolError(f"{name} must be a finite number")
    return result


def _number(value: object, name: str) -> float:
    return _finite_number(value, name)


def _integer(value: object, name: str, *, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise PluginProtocolError(f"{name} is outside its supported range")
    return value


def _string(value: object, name: str, *, allow_empty: bool = False) -> str:
    return (
        _optional_text(value, name, MAX_TEXT_CHARS)
        if allow_empty
        else _text(value, name, MAX_TEXT_CHARS)
    )


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise PluginProtocolError(f"{name} must be a boolean")
    return value


def _freeze_json(value: object, *, depth: int = 0) -> object:
    if depth > MAX_JSON_DEPTH:
        raise PluginProtocolError("protocol nesting exceeds the limit")
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise PluginProtocolError("JSON object keys must be text")
        return MappingProxyType(
            {key: _freeze_json(item, depth=depth + 1) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, depth=depth + 1) for item in value)
    if value is None or type(value) in {bool, int, float, str}:
        return value
    raise PluginProtocolError("protocol contains a non-JSON value")


def _json_value(value: object) -> object:
    """Convert an immutable JSON tree to ordinary encoder-compatible containers."""

    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


__all__ = [
    "MAX_CANDIDATE_CHARS",
    "MAX_SESSION_OPTIONS",
    "MAX_VIEWER_MESSAGES",
    "SUPPORTED_CAPABILITIES",
    "Candidate",
    "CapabilityCall",
    "CapabilityResponse",
    "EvidenceSource",
    "Invocation",
    "Opportunity",
    "OpportunityMode",
    "PluginFactClaim",
    "PluginProtocolError",
    "RoomEvidence",
    "SelfSentMessage",
    "SessionConfiguration",
    "SessionFocus",
    "Settlement",
    "SettlementOutcome",
    "Silent",
    "TrustLevel",
    "TypedFailure",
    "ViewerChatSnapshot",
    "ViewerMessage",
    "WorkerCancellation",
    "WorkerOutcome",
    "decode_capability_call",
    "decode_capability_response",
    "decode_invocation",
    "decode_worker_cancellation",
    "decode_worker_outcome",
    "encode_capability_call",
    "encode_capability_response",
    "encode_invocation",
    "encode_worker_cancellation",
    "encode_worker_outcome",
]
