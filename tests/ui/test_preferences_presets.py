"""R1-R4: the few settings a non-expert needs, the alert presets and the recommended values."""

from wimm.config import RANGES, Config, config_to_raw
from wimm.ui.dialogs.preferences_model import (
    ADVANCED_GROUPS,
    CATEGORIES_KEY,
    ESSENTIAL_GROUPS,
    LIST_KEYS,
    NUMBER_FIELDS,
    display_value,
)
from wimm.ui.dialogs.preferences_presets import (
    CUSTOM_SENTENCE,
    PRESETS,
    matching_preset,
    preset_sentence,
    recommended_values,
)


def test_only_the_alert_settings_are_in_view() -> None:
    keys = [key for group in ESSENTIAL_GROUPS for key in group.keys]

    assert keys == ["notify_after_s", "notify_min_bytes", CATEGORIES_KEY]
    assert len([key for group in ADVANCED_GROUPS for key in group.keys]) == 15


def test_labels_read_as_sentences_in_everyday_units() -> None:
    network = NUMBER_FIELDS["net_active_threshold_bps"]

    assert NUMBER_FIELDS["notify_after_s"].title == "Avvisami se non lo usi da (minuti)"
    assert network.title == "È fermo se scambia in rete meno di (kB al secondo)"
    assert display_value(field=network, raw=700) == 0.7


def test_presets_are_few_normal_many_and_normal_is_the_default() -> None:
    defaults = config_to_raw(config=Config())

    assert [preset.name for preset in PRESETS] == ["Pochi", "Normali", "Tanti"]
    assert matching_preset(values=defaults) is PRESETS[1]


def test_every_preset_value_is_inside_the_allowed_range() -> None:
    for preset in PRESETS:
        for key, value in preset.values.items():
            lower, upper = RANGES[key]
            assert value >= lower and (upper is None or value <= upper), (preset.name, key)


def test_values_set_by_hand_match_no_preset() -> None:
    values = {**config_to_raw(config=Config()), "notify_after_s": 5400}

    assert matching_preset(values=values) is None


def test_preset_sentence_says_what_it_means_in_words() -> None:
    assert preset_sentence(preset=PRESETS[1]) == (
        "Normali: ti avvisiamo se qualcosa resta acceso senza uso per 2 ore "
        "e libera almeno 200 MB, fino a 3 avvisi all'ora (gli altri insieme in uno solo)."
    )
    assert "fino a 1 avviso all'ora" in preset_sentence(preset=PRESETS[0])
    assert preset_sentence(preset=None) == CUSTOM_SENTENCE


def test_recommended_values_reset_numbers_and_choices_but_keep_names_and_folders() -> None:
    values = recommended_values()

    assert values["sample_interval_s"] == Config().sample_interval_s
    assert values[CATEGORIES_KEY] == config_to_raw(config=Config())[CATEGORIES_KEY]
    assert not set(LIST_KEYS) & set(values)
    assert "language" not in values
