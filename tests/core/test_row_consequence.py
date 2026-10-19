import pytest

from wimm.core.risk import RiskTarget, assess_risk
from wimm.core.row_consequence import join_consequences, row_consequence
from wimm.model.disk import CacheKind
from wimm.model.enums import ActionKind


def _cache_target(*, kind: CacheKind) -> tuple[ActionKind, RiskTarget]:
    if kind is CacheKind.TRASH:
        return ActionKind.TRASH_EMPTY, RiskTarget(kind="trash", cache_kind=kind)
    return ActionKind.CACHE_CLEAN, RiskTarget(kind="cache", cache_kind=kind)


@pytest.mark.parametrize("kind", list(CacheKind))
def test_row_consequence_cache_joins_the_consequences_of_the_assessment(
    kind: CacheKind,
) -> None:
    action, target = _cache_target(kind=kind)

    text = row_consequence(action=action, target=target)

    assert text
    assert text == join_consequences(
        consequences=assess_risk(target=target, action=action).consequences
    )


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (CacheKind.UV, "I pacchetti si riscaricano quando servono."),
        (CacheKind.GO_BUILD, "Le prossime compilazioni saranno più lente."),
        (CacheKind.TRASH, "I file nel cestino vengono eliminati in modo definitivo."),
    ],
)
def test_row_consequence_cache_text(kind: CacheKind, expected: str) -> None:
    action, target = _cache_target(kind=kind)

    assert row_consequence(action=action, target=target) == expected


def test_row_consequence_maven_warns_that_local_artifacts_are_lost() -> None:
    action, target = _cache_target(kind=CacheKind.MAVEN)

    assert row_consequence(action=action, target=target).startswith(
        "Gli artefatti installati in locale con mvn install"
    )


@pytest.mark.parametrize(
    ("folder_name", "marker", "expected"),
    [
        (
            "target",
            "Cargo.toml",
            "Per usare di nuovo il progetto serve ricostruire la cartella con cargo build.",
        ),
        (
            "node_modules",
            "",
            "Per usare di nuovo il progetto serve ricostruire la cartella con npm install.",
        ),
        (
            "target",
            "",
            "Serve reinstallare le dipendenze (npm install o uv sync) prima di usare il progetto.",
        ),
    ],
)
def test_row_consequence_devdir_names_the_rebuild_command_only_when_known(
    folder_name: str, marker: str, expected: str
) -> None:
    text = row_consequence(
        action=ActionKind.DEVDIR_DELETE,
        target=RiskTarget(kind="devdir"),
        folder_name=folder_name,
        marker=marker,
    )

    assert text == expected


@pytest.mark.parametrize(
    ("has_repo_digests", "expected"),
    [
        (True, "Si riscarica dal registry quando serve."),
        (
            False,
            "Immagine costruita in locale, non è su un registry: per riaverla serve ricostruirla.",
        ),
    ],
)
def test_row_consequence_image_depends_on_where_it_can_be_pulled_from(
    has_repo_digests: bool, expected: str
) -> None:
    target = RiskTarget(kind="image", has_repo_digests=has_repo_digests, dangling=False)

    assert row_consequence(action=ActionKind.IMAGE_REMOVE, target=target) == expected


def test_row_consequence_dangling_image_says_it_goes_away_without_loss() -> None:
    target = RiskTarget(kind="image", has_repo_digests=False, dangling=True)

    assert row_consequence(action=ActionKind.IMAGE_REMOVE, target=target) == (
        "Nessun nome punta più a questa immagine e nessun contenitore la usa: "
        "sparisce senza perdere niente."
    )


def test_row_consequence_keeps_every_line_like_the_dialog() -> None:
    target = RiskTarget(kind="container", is_running=True)

    text = row_consequence(action=ActionKind.CONTAINER_STOP, target=target)

    assert text == (
        "Il container si ferma; dati e configurazione restano.\n"
        "Se il container non si ferma da solo, Docker lo termina dopo 10 secondi."
    )


def test_join_consequences_puts_one_line_per_consequence() -> None:
    assert join_consequences(consequences=("a", "b")) == "a\nb"
    assert join_consequences(consequences=("only",)) == "only"
    assert join_consequences(consequences=()) == ""


def test_join_consequences_shows_a_repeated_line_once_like_the_plan() -> None:
    assert join_consequences(consequences=("a", "b", "a")) == "a\nb"
