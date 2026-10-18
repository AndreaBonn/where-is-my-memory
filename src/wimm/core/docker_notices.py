"""Readable notices about the container engines wimm could not use (F9, S8)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from wimm.i18n import N_, _
from wimm.redaction import redact_text

from .docker_endpoint import RejectedEndpoint, RejectionReason

NOTICE_SEPARATOR = "; "


class NoticeCode(StrEnum):
    UNSUPPORTED_SCHEME = "unsupported_scheme"
    PATH_NOT_ABSOLUTE = "path_not_absolute"
    LOCATION_NOT_ALLOWED = "location_not_allowed"
    RUNTIME_DIR_NOT_PRIVATE = "runtime_dir_not_private"
    SOCKET_MISSING = "socket_missing"
    NOT_A_SOCKET = "not_a_socket"
    CONTEXT_NOT_FOUND = "context_not_found"
    CONTEXT_INVALID = "context_invalid"
    UNREACHABLE = "unreachable"
    NO_ENGINE = "no_engine"


@dataclass(frozen=True, slots=True)
class EngineNotice:
    """One engine endpoint that is refused, missing or not answering.

    `endpoint` is what the user configured or the socket path; `detail` is the engine's
    own error for `UNREACHABLE`.
    """

    code: NoticeCode
    endpoint: str
    detail: str = ""


# The sentence a refused endpoint gets. `no_engine` completes "Docker non disponibile: ...".
NOTICE_MESSAGES: Mapping[NoticeCode, str] = MappingProxyType(
    {
        NoticeCode.UNSUPPORTED_SCHEME: N_(
            "Endpoint Docker {endpoint} ignorato: sono accettati solo socket locali (unix://)"
        ),
        NoticeCode.PATH_NOT_ABSOLUTE: N_(
            "Endpoint Docker {endpoint} ignorato: il percorso del socket non è valido"
        ),
        NoticeCode.LOCATION_NOT_ALLOWED: N_(
            "Endpoint Docker {endpoint} ignorato: il socket non è in una posizione consentita"
        ),
        NoticeCode.RUNTIME_DIR_NOT_PRIVATE: N_(
            "Endpoint Docker {endpoint} ignorato: la cartella runtime non è privata"
        ),
        NoticeCode.SOCKET_MISSING: N_("Endpoint Docker {endpoint} non trovato: il socket manca"),
        NoticeCode.NOT_A_SOCKET: N_(
            "Endpoint Docker {endpoint} ignorato: il percorso non è un socket"
        ),
        NoticeCode.CONTEXT_NOT_FOUND: N_("Contesto Docker {endpoint} non trovato"),
        NoticeCode.CONTEXT_INVALID: N_("Contesto Docker {endpoint} non valido"),
        NoticeCode.UNREACHABLE: N_("Motore container su {endpoint} non raggiungibile: {detail}"),
        NoticeCode.NO_ENGINE: N_("nessun socket Docker o Podman trovato"),
    }
)


def rejection_notice(*, rejected: RejectedEndpoint) -> EngineNotice:
    """Turn a resolver rejection into the notice for the same reason."""
    reason: RejectionReason = rejected.reason
    return EngineNotice(code=NoticeCode(reason.value), endpoint=rejected.endpoint)


def notice_text(*, notice: EngineNotice) -> str:
    """The notice in the active language, with credentials in the endpoint masked."""
    return _(NOTICE_MESSAGES[notice.code]).format(
        endpoint=redact_text(text=notice.endpoint), detail=redact_text(text=notice.detail)
    )


def notices_text(*, notices: Sequence[EngineNotice]) -> str:
    """All the notices on one line, in order; empty for none."""
    return NOTICE_SEPARATOR.join(notice_text(notice=notice) for notice in notices)
