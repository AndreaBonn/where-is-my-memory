import re

REDACTED = "[REDACTED]"
CREDENTIAL_PATTERN = r"(?:[\w-]*(?:key|token|password|secret))"
SECRET_ARGUMENT = re.compile(
    rf"""(?P<prefix>(?<![\w-])(?:--{CREDENTIAL_PATTERN}(?:\s*=\s*|\s+)|"""
    rf"""['\"]?{CREDENTIAL_PATTERN}['\"]?\s*[:=]\s*))"""
    r"""(?:"[^"\n]*"|'[^'\n]*'|[^\s,;}]+)""",
    re.IGNORECASE,
)
AUTH_HEADER = re.compile(r"(\bAuthorization\s*:\s*(?:Bearer|Basic)\s+)\S+", re.IGNORECASE)
COOKIE_HEADER = re.compile(r"(\b(?:Set-)?Cookie\s*:\s*)[^\r\n]+", re.IGNORECASE)
URL_PASSWORD = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s/@:]+:)[^\s/@]*(@)", re.IGNORECASE)
SECRET_FIELD = re.compile(rf"^{CREDENTIAL_PATTERN}$", re.IGNORECASE)


def redact_text(text: str) -> str:
    text = AUTH_HEADER.sub(repl=rf"\1{REDACTED}", string=text)
    text = COOKIE_HEADER.sub(repl=rf"\1{REDACTED}", string=text)
    text = URL_PASSWORD.sub(repl=rf"\1{REDACTED}\2", string=text)
    return SECRET_ARGUMENT.sub(repl=lambda match: match["prefix"] + REDACTED, string=text)
