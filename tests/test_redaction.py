import pytest

from wimm.redaction import redact_text


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Authorization: Bearer abc", "Authorization: Bearer [REDACTED]"),
        ("https://user:pass@host/x", "https://user:[REDACTED]@host/x"),
        ("--token=abc", "--token=[REDACTED]"),
        ("node --port=8000", "node --port=8000"),
    ],
)
def test_redact_text_masks_credentials_and_preserves_public_text(text: str, expected: str) -> None:
    assert redact_text(text=text) == expected
