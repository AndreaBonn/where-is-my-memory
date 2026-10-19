"""T-6.26: the mass action over the rows the user ticked, and the id of one ticked row."""

import pytest

from wimm.model.actions import (
    ACTION_FINGERPRINT_TYPES,
    SELECTABLE_KINDS,
    ActionRequest,
    parse_selected_entry,
    selected_entry_id,
)
from wimm.model.enums import ActionKind, TargetId


def test_selected_ids_make_a_valid_request() -> None:
    request = ActionRequest(
        kind=ActionKind.DISK_FREE_SELECTED, selected_ids=frozenset({"cache_clean|uv"})
    )
    assert request.selected_ids == {"cache_clean|uv"}
    assert request.target_id is None
    assert ACTION_FINGERPRINT_TYPES[ActionKind.DISK_FREE_SELECTED] == ()


def test_the_selection_is_required_for_the_selected_action() -> None:
    with pytest.raises(ValueError, match="selected_ids"):
        ActionRequest(kind=ActionKind.DISK_FREE_SELECTED)


def test_the_selected_action_takes_no_target() -> None:
    with pytest.raises(ValueError, match="target"):
        ActionRequest(
            kind=ActionKind.DISK_FREE_SELECTED,
            target_id=TargetId("x"),
            selected_ids=frozenset({"cache_clean|uv"}),
        )


@pytest.mark.parametrize("kind", [ActionKind.DISK_FREE_SAFE, ActionKind.BUILDER_PRUNE])
def test_no_other_action_takes_a_selection(kind: ActionKind) -> None:
    with pytest.raises(ValueError, match="selected_ids"):
        ActionRequest(kind=kind, selected_ids=frozenset({"cache_clean|uv"}))
    assert ActionRequest(kind=kind).selected_ids == frozenset()


def test_entry_id_joins_kind_and_target() -> None:
    assert selected_entry_id(kind=ActionKind.IMAGE_REMOVE, target_id="sha256:ab") == (
        "image_remove|sha256:ab"
    )


def test_entry_id_of_a_targetless_row_has_an_empty_target() -> None:
    assert selected_entry_id(kind=ActionKind.BUILDER_PRUNE, target_id=None) == "builder_prune|"


def test_entry_id_keeps_a_target_that_holds_the_separator() -> None:
    entry = selected_entry_id(kind=ActionKind.DEVDIR_DELETE, target_id="/w/a|b/node_modules")
    assert parse_selected_entry(entry=entry) == ActionRequest(
        kind=ActionKind.DEVDIR_DELETE, target_id=TargetId("/w/a|b/node_modules")
    )


@pytest.mark.parametrize("kind", [k for k in ActionKind if k in SELECTABLE_KINDS])
def test_every_selectable_kind_round_trips(kind: ActionKind) -> None:
    target = None if kind in {ActionKind.BUILDER_PRUNE, ActionKind.TRASH_EMPTY} else "t"
    request = parse_selected_entry(entry=selected_entry_id(kind=kind, target_id=target))
    assert request == ActionRequest(
        kind=kind, target_id=None if target is None else TargetId(target)
    )


def test_selectable_kinds_are_the_single_row_actions_of_the_disk_page() -> None:
    expected = {
        ActionKind.IMAGE_REMOVE,
        ActionKind.CONTAINER_REMOVE,
        ActionKind.VOLUME_REMOVE,
        ActionKind.BUILDER_PRUNE,
        ActionKind.CACHE_CLEAN,
        ActionKind.CACHE_ITEM_REMOVE,
        ActionKind.TRASH_EMPTY,
        ActionKind.DEVDIR_DELETE,
    }
    assert expected == SELECTABLE_KINDS


@pytest.mark.parametrize(
    "entry",
    [
        "",
        "image_remove",  # no separator
        "|sha256:ab",  # no kind
        "no_such_kind|x",
        "process_kill|1",  # not a disk row action
        "disk_free_safe|",  # a mass action is not a row
        "disk_free_selected|",
        "image_remove|",  # a target action without its target
        "builder_prune|x",  # a targetless action with a target
    ],
)
def test_a_malformed_or_unselectable_entry_is_a_value_error(entry: str) -> None:
    with pytest.raises(ValueError, match="selected"):
        parse_selected_entry(entry=entry)
