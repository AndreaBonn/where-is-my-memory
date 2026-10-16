import pytest

from wimm.core.cgroup_paths import unescape_unit_name


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        (r"google\x2dchrome", "google-chrome"),
        (r"a\x41\x2Db", "aA-b"),
        ("plain.scope", "plain.scope"),
        (r"bad\xZZ", r"bad\xZZ"),
        ("", ""),
    ],
)
def test_unescape_unit_name(unit: str, expected: str) -> None:
    assert unescape_unit_name(name=unit) == expected
