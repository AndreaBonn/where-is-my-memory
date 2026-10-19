"""T-6.37a: the system ollama store is one CacheEntry that no file stands behind."""

import pytest

from tests.core.ollama_system_helpers import MB, MODEL_ID, model, system_entry
from wimm.model import CacheEntry, CacheItem, CacheItemKind, CacheKind, CacheRest


def hf_item(*, model_id: str = "") -> CacheItem:
    return CacheItem(
        id="models--org--a",
        title="org/a",
        path="/home/u/.cache/huggingface/hub/models--org--a",
        size=MB,
        st_ino=5,
        st_dev=2049,
        kind=CacheItemKind.HF_MODEL,
        model_id=model_id,
    )


def test_cache_kind_has_the_system_store_value() -> None:
    assert CacheKind.OLLAMA_SYSTEM.value == "ollama_system"
    assert CacheKind("ollama_system") is CacheKind.OLLAMA_SYSTEM


@pytest.mark.parametrize("model_id", ["", MODEL_ID, "0123456789ab"])
def test_model_id_empty_or_twelve_lowercase_hex_is_accepted(model_id: str) -> None:
    assert hf_item(model_id=model_id).model_id == model_id


def test_model_id_defaults_to_empty() -> None:
    assert hf_item().model_id == ""


@pytest.mark.parametrize(
    "model_id",
    [
        "a2af6cc3eb7",
        "a2af6cc3eb7f0",
        "A2AF6CC3EB7F",
        "a2af6cc3eb7g",
        " a2af6cc3eb7f",
        "a2af6cc3eb7f\n",
    ],
)
def test_model_id_not_twelve_lowercase_hex_is_rejected(model_id: str) -> None:
    with pytest.raises(ValueError, match="model_id"):
        hf_item(model_id=model_id)


def test_a_system_entry_with_zero_inode_and_device_is_accepted() -> None:
    built = system_entry()

    assert built.kind is CacheKind.OLLAMA_SYSTEM
    assert built.items[0].model_id == MODEL_ID


@pytest.mark.parametrize("identity", [(5, 0), (0, 5), (5, 5)])
def test_a_system_entry_with_a_file_identity_is_rejected(identity: tuple[int, int]) -> None:
    st_ino, st_dev = identity

    with pytest.raises(ValueError, match="st_ino"):
        system_entry(st_ino=st_ino, st_dev=st_dev)


@pytest.mark.parametrize("rest", [CacheRest(shared=1), CacheRest(unattributed=1)])
def test_a_system_entry_with_a_rest_is_rejected(rest: CacheRest) -> None:
    with pytest.raises(ValueError, match="rest"):
        system_entry(rest=rest)


def test_a_system_item_without_model_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="model_id"):
        system_entry(items=(model(model_id=""),))


def test_every_system_item_needs_a_model_id() -> None:
    with pytest.raises(ValueError, match="model_id"):
        system_entry(items=(model(), model(name="b:1", model_id="")))


def test_an_entry_of_another_kind_may_hold_items_without_model_id() -> None:
    built = CacheEntry(
        kind=CacheKind.HUGGINGFACE,
        path="/home/u/.cache/huggingface",
        size=MB,
        st_ino=11,
        st_dev=2049,
        items=(hf_item(),),
    )

    assert built.items[0].model_id == ""


def test_a_system_entry_without_items_is_accepted() -> None:
    assert system_entry(items=(), size=0).items == ()
