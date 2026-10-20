from dataclasses import replace
from typing import Unpack

from wimm.core.categorize import CategoryDecision
from wimm.core.grouping import GroupDraft, GroupingInput, build_groups
from wimm.core.grouping_keys import Pair, stable_group_id
from wimm.model.enums import Category

from .helpers import ProcessChanges, process

HOME = "/home/u"


def pair(pid: int, /, *, category: Category, **changes: Unpack[ProcessChanges]) -> Pair:
    proc = replace(process(**changes), pid=pid, ppid=1)
    return proc, CategoryDecision(category=category, reason_code="x")


def build(*pairs: Pair) -> tuple[GroupDraft, ...]:
    return build_groups(
        grouping=GroupingInput(
            pairs=pairs,
            containers=(),
            project_root_by_cwd={},
            desktop_name_by_appid={},
            own_home=HOME,
            own_uid=1000,
        )
    )


def test_unrooted_groups_with_same_root_in_two_buckets_get_distinct_ids() -> None:
    drafts = build(
        pair(10, category=Category.DEV_PROCESS, name="worker", cwd=None),
        pair(20, category=Category.OTHER, name="worker", cwd=None),
    )

    assert len(drafts) == 2
    assert drafts[0].key == drafts[1].key
    # Pinned from 1.0.0: from here on these ids are stored in user state.
    assert {draft.category: draft.id for draft in drafts} == {
        Category.DEV_PROCESS: "g_c0c4390b8271",
        Category.OTHER: "g_ecd371c164df",
    }


def test_unrooted_group_id_is_stable_across_samples_in_the_same_bucket() -> None:
    first = build(pair(10, category=Category.OTHER, name="worker", cwd=None))
    second = build(pair(99, category=Category.OTHER, name="worker", cwd=None))

    assert first[0].id == second[0].id


def test_unrooted_dev_group_keeps_its_id_when_it_becomes_a_dev_server() -> None:
    process_only = build(pair(10, category=Category.DEV_PROCESS, name="node", cwd=None))
    server = build(pair(10, category=Category.DEV_SERVER, name="node", cwd=None))

    assert process_only[0].category is not server[0].category
    assert process_only[0].id == server[0].id


def test_unscoped_ids_keep_the_values_saved_before_scoping() -> None:
    # Pinned from 0.2.0: silences and ignores are stored by id and must survive the upgrade.
    assert stable_group_id(key_class="app", key="firefox") == "g_68323f0ae827"
    assert stable_group_id(key_class="folder", key="/work/api") == "g_a5032981058d"


def test_scoped_id_differs_from_the_unscoped_one() -> None:
    unscoped = stable_group_id(key_class="root_process", key="worker|")

    assert unscoped == stable_group_id(key_class="root_process", key="worker|", scope="")
    assert unscoped != stable_group_id(key_class="root_process", key="worker|", scope="OTHER")
    assert stable_group_id(
        key_class="root_process", key="worker|", scope="OTHER"
    ) != stable_group_id(key_class="root_process", key="worker|", scope="TERMINAL")


def test_one_appid_in_two_app_buckets_gives_two_groups_with_distinct_ids() -> None:
    # A browser opened from a desktop app starts in the app's systemd scope and inherits
    # its appid, but is categorized BROWSER: one key, two buckets, once one shared id.
    app = replace(pair(10, category=Category.DESKTOP_APP, name="deadlineaura")[0], ppid=1)
    browser = replace(pair(20, category=Category.BROWSER, name="chrome")[0], ppid=1)
    drafts = build(
        (app, CategoryDecision(category=Category.DESKTOP_APP, reason_code="x", appid="Aura")),
        (browser, CategoryDecision(category=Category.BROWSER, reason_code="x", appid="Aura")),
    )

    by_category = {draft.category: draft for draft in drafts}
    assert set(by_category) == {Category.DESKTOP_APP, Category.BROWSER}
    assert by_category[Category.DESKTOP_APP].process_pids == (10,)
    # The part holding the oldest process keeps the id saved before scoping.
    assert by_category[Category.DESKTOP_APP].id == stable_group_id(key_class="app", key="Aura")
    assert by_category[Category.BROWSER].id == stable_group_id(
        key_class="app", key="Aura", scope=Category.BROWSER.value
    )


def test_the_oldest_start_keeps_the_unscoped_id_when_pids_have_wrapped() -> None:
    app = replace(
        pair(900, category=Category.DESKTOP_APP, name="aura", create_time=100.0)[0], ppid=1
    )
    browser = replace(
        pair(20, category=Category.BROWSER, name="chrome", create_time=500.0)[0], ppid=1
    )
    drafts = build(
        (app, CategoryDecision(category=Category.DESKTOP_APP, reason_code="x", appid="Aura")),
        (browser, CategoryDecision(category=Category.BROWSER, reason_code="x", appid="Aura")),
    )

    by_category = {draft.category: draft.id for draft in drafts}
    assert by_category[Category.DESKTOP_APP] == stable_group_id(key_class="app", key="Aura")
    assert by_category[Category.BROWSER] != by_category[Category.DESKTOP_APP]
