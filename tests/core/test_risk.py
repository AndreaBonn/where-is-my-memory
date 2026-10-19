from dataclasses import replace

import pytest

from tests.core.risk_helpers import CONTAINER_TEXT, CONTAINER_TIMEOUT_TEXT, PROCESS
from wimm.core.risk import RiskTarget as Target
from wimm.core.risk import assess_risk, available_actions
from wimm.model.enums import ActionKind as Action
from wimm.model.enums import ActivityState, Category, Risk
from wimm.model.snapshot import ActionOffer


@pytest.mark.parametrize(
    ("text", "case"),
    {
        ("Il server si ferma."): (
            replace(PROCESS, cwd="/work", category=Category.DEV_SERVER),
            Action.PROCESS_TERMINATE,
            Risk.SAFE,
        ),
        ("È in uso adesso: chi lo sta usando perde la connessione."): (
            replace(PROCESS, activity=ActivityState.ACTIVE),
            Action.PROCESS_TERMINATE,
            Risk.CAUTION,
        ),
        (
            "La sessione dell'agente si chiude: il lavoro non salvato nella conversazione si perde."
        ): (replace(PROCESS, category=Category.AI_CLI), Action.PROCESS_TERMINATE, Risk.CAUTION),
        (
            "Il browser si chiude senza la chiusura normale: alla riapertura ripristina le schede "
            "dal salvataggio automatico, che può essere indietro di qualche secondo."
        ): (Target(kind="browser", category=Category.BROWSER), Action.APP_CLOSE, Risk.CAUTION),
        ("Eventuali file non salvati possono andare persi."): (
            Target(kind="desktop_app", category=Category.DESKTOP_APP, has_documents=True),
            Action.APP_CLOSE,
            Risk.CAUTION,
        ),
        ("L'applicazione si chiude."): (
            Target(kind="desktop_app", category=Category.DESKTOP_APP),
            Action.APP_CLOSE,
            Risk.CAUTION,
        ),
        (
            "Si chiudono tutte le finestre e le schede del terminale e i programmi al loro interno."
        ): (Target(kind="terminal", category=Category.TERMINAL), Action.APP_CLOSE, Risk.CAUTION),
        ("Chiusura immediata senza salvataggio."): (PROCESS, Action.PROCESS_KILL, Risk.CAUTION),
        ("Le modifiche fatte dentro il container fuori dai volumi si perdono."): (
            Target(kind="container", is_running=False),
            Action.CONTAINER_REMOVE,
            Risk.CAUTION,
        ),
        ("I container vengono rimossi; i volumi con i dati restano."): (
            Target(kind="compose_project"),
            Action.COMPOSE_DOWN,
            Risk.CAUTION,
        ),
        ("I dati dei volumi db, uploads vengono cancellati in modo definitivo."): (
            Target(kind="compose_project", volume_names=("db", "uploads")),
            Action.COMPOSE_DOWN_VOLUMES,
            Risk.DANGER,
        ),
        ("Si riscarica dal registry quando serve."): (
            Target(kind="image", has_repo_digests=True, dangling=False),
            Action.IMAGE_REMOVE,
            Risk.SAFE,
        ),
        ("Immagine costruita in locale, non è su un registry: per riaverla serve ricostruirla."): (
            Target(kind="image", has_repo_digests=False, dangling=False),
            Action.IMAGE_REMOVE,
            Risk.CAUTION,
        ),
        (
            "Nessun nome punta più a questa immagine e nessun contenitore la usa: "
            "sparisce senza perdere niente."
        ): (
            Target(kind="image", has_repo_digests=False, dangling=True),
            Action.IMAGE_REMOVE,
            Risk.SAFE,
        ),
        ("Le prossime build saranno più lente."): (
            Target(kind="build_cache"),
            Action.BUILDER_PRUNE,
            Risk.SAFE,
        ),
        ("I dati del volume vengono cancellati in modo definitivo."): (
            Target(kind="volume"),
            Action.VOLUME_REMOVE,
            Risk.DANGER,
        ),
        ("I pacchetti si riscaricano quando servono."): (
            Target(kind="cache"),
            Action.CACHE_CLEAN,
            Risk.SAFE,
        ),
        ("I file nel cestino vengono eliminati in modo definitivo."): (
            Target(kind="trash"),
            Action.TRASH_EMPTY,
            Risk.DANGER,
        ),
        ("Serve reinstallare le dipendenze (npm install o uv sync) prima di usare il progetto."): (
            Target(kind="devdir"),
            Action.DEVDIR_DELETE,
            Risk.CAUTION,
        ),
    }.items(),
)
def test_assess_risk_specification_rows(
    text: str | None, case: tuple[Target, Action, Risk]
) -> None:
    target, action, level = case
    assessment = assess_risk(target=target, action=action)
    assert assessment.level is level
    assert assessment.consequences == (() if text is None else (text,))
    if action is not Action.PROCESS_KILL:
        offers = available_actions(target=target)
        assert ActionOffer(kind=action, risk=level) in offers
        assert len(offers) == (3 if target.kind == "compose_project" else 1)


def test_container_stop_tells_that_docker_terminates_it_after_ten_seconds() -> None:
    target = Target(kind="container", is_running=True)

    assessment = assess_risk(target=target, action=Action.CONTAINER_STOP)

    assert assessment.level is Risk.SAFE
    assert assessment.consequences == (CONTAINER_TEXT, CONTAINER_TIMEOUT_TEXT)
    assert ActionOffer(kind=Action.CONTAINER_STOP, risk=Risk.SAFE) in available_actions(
        target=target
    )
    removal = assess_risk(
        target=Target(kind="container", is_running=False), action=Action.CONTAINER_REMOVE
    )
    assert CONTAINER_TIMEOUT_TEXT not in removal.consequences


def test_user_facing_consequences_carry_no_markdown_backticks() -> None:
    # Shown in plain GTK labels: a backtick would appear literally on screen.
    from wimm.core.risk_table import CONSEQUENCES

    assert all("`" not in text for text in CONSEQUENCES.values())
    assert any("Docker" in text for text in CONSEQUENCES.values())  # positive pair
    assert not any("docker start" in text for text in CONSEQUENCES.values())


@pytest.mark.parametrize(
    ("category", "text"),
    [
        (Category.DEV_SERVER, "Il server si ferma."),
        # F7: gitstatusd is a development process, not a server.
        (Category.DEV_PROCESS, "Il programma si ferma."),
    ],
)
def test_an_idle_development_process_is_called_a_server_only_when_it_is_one(
    category: Category, text: str
) -> None:
    target = replace(PROCESS, category=category)

    result = assess_risk(target=target, action=Action.PROCESS_TERMINATE)

    assert (result.level, result.consequences) == (Risk.SAFE, (text,))
