import pytest

from wimm import i18n
from wimm.core.docker_endpoint import EndpointSource, RejectedEndpoint, RejectionReason
from wimm.core.docker_notices import (
    EngineNotice,
    NoticeCode,
    notice_text,
    notices_text,
    rejection_notice,
)


def test_every_rejection_reason_has_a_notice_code_and_a_readable_text() -> None:
    for reason in RejectionReason:
        rejected = RejectedEndpoint(
            source=EndpointSource.DOCKER_HOST, endpoint="tcp://example:2375", reason=reason
        )
        text = notice_text(notice=rejection_notice(rejected=rejected))
        assert "example" in text or "Docker" in text
        assert text.strip() == text and text != ""


def test_tcp_host_is_explained_as_not_local() -> None:
    rejected = RejectedEndpoint(
        source=EndpointSource.DOCKER_HOST,
        endpoint="tcp://example:2375",
        reason=RejectionReason.UNSUPPORTED_SCHEME,
    )
    text = notice_text(notice=rejection_notice(rejected=rejected))
    assert "tcp://example:2375" in text
    assert "locali" in text


def test_credentials_in_the_endpoint_never_reach_the_text() -> None:
    notice = EngineNotice(code=NoticeCode.UNSUPPORTED_SCHEME, endpoint="tcp://user:hunter2@host:1")
    text = notice_text(notice=notice)
    assert "hunter2" not in text
    assert "host:1" in text  # positive pair: the rest of the endpoint is still there


def test_unreachable_text_carries_the_endpoint_and_the_reason() -> None:
    notice = EngineNotice(
        code=NoticeCode.UNREACHABLE, endpoint="/run/user/1000/podman/podman.sock", detail="denied"
    )
    text = notice_text(notice=notice)
    assert "/run/user/1000/podman/podman.sock" in text
    assert "denied" in text


def test_no_engine_text_is_the_reason_after_docker_non_disponibile() -> None:
    assert notice_text(notice=EngineNotice(code=NoticeCode.NO_ENGINE, endpoint="")) == (
        "nessun socket Docker o Podman trovato"
    )


def test_text_follows_the_active_language() -> None:
    notice = EngineNotice(code=NoticeCode.NO_ENGINE, endpoint="")
    i18n.set_language(language=i18n.ENGLISH)
    assert notice_text(notice=notice) == "no Docker or Podman socket found"


def test_notices_text_joins_in_order_and_is_empty_for_no_notices() -> None:
    first = EngineNotice(code=NoticeCode.NO_ENGINE, endpoint="")
    second = EngineNotice(code=NoticeCode.UNREACHABLE, endpoint="/a", detail="x")
    assert notices_text(notices=(first, second)) == (
        f"{notice_text(notice=first)}; {notice_text(notice=second)}"
    )
    assert notices_text(notices=()) == ""


@pytest.mark.parametrize("code", list(NoticeCode))
def test_every_code_formats_without_missing_placeholders(code: NoticeCode) -> None:
    text = notice_text(notice=EngineNotice(code=code, endpoint="/x", detail="why"))
    assert "{" not in text


def test_unreachable_detail_with_credentials_never_reaches_the_text() -> None:
    notice = EngineNotice(
        code=NoticeCode.UNREACHABLE,
        endpoint="/run/docker.sock",
        detail="cannot reach http://u:hunter2@h",
    )
    text = notice_text(notice=notice)
    assert "hunter2" not in text
    assert "@h" in text  # positive pair: the host of the detail is still shown
