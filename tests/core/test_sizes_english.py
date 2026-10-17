import pytest

from wimm.core.sizes import format_size

pytestmark = pytest.mark.usefixtures("english")


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0 B"),
        (980_000_000, "980 MB"),
        (1_100_000_000, "1.1 GB"),
        (2_500_000_000_000, "2.5 TB"),
    ],
)
def test_format_size_uses_a_decimal_point_in_english(size: int, expected: str) -> None:
    assert format_size(size=size) == expected
