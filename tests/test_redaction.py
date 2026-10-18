import pytest

from wimm.redaction import redact_text


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Authorization: Bearer abc", "Authorization: Bearer [REDACTED]"),
        ("https://user:pass@host/x", "https://user:[REDACTED]@host/x"),
        ("--token=abc", "--token=[REDACTED]"),
        ("node --port=8000", "node --port=8000"),
        ("mysql MYSQL_PWD=abc", "mysql MYSQL_PWD=[REDACTED]"),
        ("tool --passwd=abc", "tool --passwd=[REDACTED]"),
        ("tool --pass abc", "tool --pass [REDACTED]"),
        ("tool --auth abc", "tool --auth [REDACTED]"),
        ("tool --credential=abc", "tool --credential=[REDACTED]"),
        ("git log --author alice", "git log --author alice"),
        ("cmd --path /tmp/x", "cmd --path /tmp/x"),
    ],
)
def test_redact_text_masks_credentials_and_preserves_public_text(text: str, expected: str) -> None:
    assert redact_text(text=text) == expected
