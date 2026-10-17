import pytest

from wimm.core.assemble import assemble_snapshot
from wimm.core.grouping_keys import protected_label
from wimm.model.enums import Category
from wimm.model.snapshot import ProtectedSummaryItem

from .assemble_helpers import SESSION_KEY, SYSTEM_KEY, build_input, draft, pair
from .helpers import process

pytestmark = pytest.mark.usefixtures("english")

OWN_UID = 1000


@pytest.mark.parametrize(
    ("proc_changes", "category", "expected"),
    [
        ({"name": "pipewire"}, Category.SESSION, ("session-audio", "Audio")),
        ({"name": "gnome-shell"}, Category.SESSION, ("session-gnome", "GNOME session")),
        ({"uid": 0}, Category.SYSTEM, ("system-services", "System services")),
        ({"uid": 1234}, Category.SYSTEM, ("other-users", "Other users")),
        ({"name": "wimm"}, Category.SELF, ("self", "where-is-my-memory")),
    ],
)
def test_protected_label_translates_the_name_but_never_the_key(
    proc_changes: dict[str, object], category: Category, expected: tuple[str, str]
) -> None:
    proc = process(**proc_changes)  # type: ignore[arg-type]

    assert protected_label(proc=proc, category=category, own_uid=OWN_UID) == expected


def test_protected_summary_reason_is_in_english() -> None:
    system = pair(7, Category.SYSTEM, name="systemd", pss=300, uss=200, swap=0)
    session = pair(5, Category.SESSION, name="gnome-shell", pss=400, uss=300, swap=0)
    inputs = build_input(
        [
            draft(
                "g_y", name="System services", category=Category.SYSTEM, pids=[7], key=SYSTEM_KEY
            ),
            draft(
                "g_s", name="GNOME session", category=Category.SESSION, pids=[5], key=SESSION_KEY
            ),
        ],
        pairs=[system, session],
    )

    snapshot = assemble_snapshot(inputs=inputs)

    assert snapshot.protected_summary == (
        ProtectedSummaryItem(label="GNOME session", memory=400, reason="desktop component"),
        ProtectedSummaryItem(label="System services", memory=300, reason="system service"),
    )
