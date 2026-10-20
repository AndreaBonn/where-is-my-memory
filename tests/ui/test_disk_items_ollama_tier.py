"""A cache row with no action of its own sits in the tier of its riskiest item (T-6.39).

The system ollama store has no whole-cache clean, so its row has no risk of its own: without
this rule it stayed under "Si libera senza pensarci" while every model in it is Pericolo.
"""

from dataclasses import replace

from tests.core.disk_helpers import MB, cache, report
from tests.core.ollama_system_helpers import system_entry
from tests.ui.disk_view_helpers import MIN_AGE, sections_by_key
from wimm.core.ollama_served import ServedStore
from wimm.model.disk import CacheKind
from wimm.ui.disk_view import build_disk_sections


def _section_of(*, title: str, served: str, withheld: frozenset[CacheKind]) -> str:
    entries = (system_entry(), cache(kind=CacheKind.GO_MOD, size=MB, ino=40))
    disk = replace(report(caches=entries), ollama_served=served)
    sections = build_disk_sections(report=disk, min_age_days=MIN_AGE, withheld=withheld)
    by_key = sections_by_key(sections=sections)
    (key,) = [key for key, section in by_key.items() for row in section.rows if row.title == title]
    return key


def test_the_system_store_sits_with_the_models_and_emulators() -> None:
    served = ServedStore.SYSTEM.value
    key = _section_of(title="Modelli ollama (sistema)", served=served, withheld=frozenset())
    assert key == "caches_data"


def test_a_withheld_cache_without_items_stays_in_its_section() -> None:
    # Paired case: no action and no items, so no item risk to move it by.
    withheld = frozenset({CacheKind.GO_MOD})
    key = _section_of(title="Go (moduli)", served=ServedStore.SYSTEM.value, withheld=withheld)
    assert key == "caches"
