from dataclasses import FrozenInstanceError, replace
from typing import get_args

import pytest

from wimm.core.risk import RiskTarget as Target
from wimm.core.risk import TargetKind, assess_risk, available_actions, group_primary_action
from wimm.model.enums import ActionKind as Action
from wimm.model.enums import ActivityState, Category, Risk
from wimm.model.snapshot import ActionOffer

PROCESS = Target(kind="process", category=Category.DEV_PROCESS, activity=ActivityState.IDLE)
CONTAINER_TEXT = (
    "Il container si ferma; dati e configurazione restano. Si riavvia con "
    "`docker start` o `docker compose up`."
)


@pytest.mark.parametrize(
    ("text", "case"),
    {
        ("Il server si ferma. Si riavvia con lo stesso comando dalla cartella /work."): (
            replace(PROCESS, cwd="/work"),
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
            "Il browser si chiude. Le schede si recuperano solo se il "
            "ripristino della sessione è attivo."
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
        CONTAINER_TEXT: (
            Target(kind="container", is_running=True),
            Action.CONTAINER_STOP,
            Risk.SAFE,
        ),
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
        (None): (
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
        (
            "Serve reinstallare le dipendenze (`npm install` / `uv sync`) "
            "prima di usare il progetto."
        ): (Target(kind="devdir"), Action.DEVDIR_DELETE, Risk.CAUTION),
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


class TestRiskBehavior:
    @pytest.mark.parametrize("category", [Category.DEV_SERVER, Category.DEV_PROCESS])
    @pytest.mark.parametrize("activity", list(ActivityState))
    def test_development_activity(self, category: Category, activity: ActivityState) -> None:
        target = replace(PROCESS, category=category, activity=activity)
        expected = Risk.SAFE if activity is ActivityState.IDLE else Risk.CAUTION
        assert assess_risk(target=target, action=Action.PROCESS_TERMINATE).level is expected

    @pytest.mark.parametrize("name", ["postgres", "mysqld", "mariadbd", "mongod", "redis-server"])
    def test_sigkill_database(self, name: str) -> None:
        target = replace(PROCESS, process_name=name)
        result = assess_risk(target=target, action=Action.PROCESS_KILL)
        assert result.level is Risk.DANGER
        assert result.consequences == ("Chiusura immediata senza salvataggio.",)

    @pytest.mark.parametrize("kind", get_args(TargetKind))
    @pytest.mark.parametrize("category", [Category.SYSTEM, Category.SESSION, Category.SELF])
    def test_protected_actions(self, kind: TargetKind, category: Category) -> None:
        target = Target(kind=kind, is_running=False, has_repo_digests=False, dangling=False)
        assert available_actions(target=target)
        assert available_actions(target=replace(target, category=category)) == ()

    def test_shell_has_no_actions_with_positive_pair(self) -> None:
        assert available_actions(target=PROCESS) == (
            ActionOffer(kind=Action.PROCESS_TERMINATE, risk=Risk.SAFE),
        )
        assert available_actions(target=replace(PROCESS, is_terminal_shell=True)) == ()

    @pytest.mark.parametrize(
        ("target", "action"),
        [
            (PROCESS, Action.IMAGE_REMOVE),
            (Target(kind="container", is_running=False), Action.CONTAINER_STOP),
            (Target(kind="container", is_running=True), Action.CONTAINER_REMOVE),
            (Target(kind="browser"), Action.PROCESS_TERMINATE),
            (Target(kind="cache"), Action.PROCESS_KILL),
            (PROCESS, Action.STOP_ALL_IDLE_SAFE),
        ],
    )
    def test_inapplicable_action_raises(self, target: Target, action: Action) -> None:
        with pytest.raises(ValueError, match="not applicable"):
            assess_risk(target=target, action=action)

    @pytest.mark.parametrize("reverse", [False, True])
    def test_group_risk_is_maximum(self, reverse: bool) -> None:
        offers: tuple[ActionOffer, ...] = (
            ActionOffer(kind=Action.VOLUME_REMOVE, risk=Risk.DANGER),
            ActionOffer(kind=Action.PROCESS_TERMINATE, risk=Risk.SAFE),
            ActionOffer(kind=Action.APP_CLOSE, risk=Risk.CAUTION),
        )
        offers = tuple(reversed(offers)) if reverse else offers
        assert group_primary_action(
            member_offers=offers, group_kind=Category.PROJECT
        ) == ActionOffer(kind=Action.GROUP_STOP, risk=Risk.DANGER)
        assert group_primary_action(member_offers=(), group_kind=Category.PROJECT) is None

    def test_single_member_group_and_compose(self) -> None:
        offer = ActionOffer(kind=Action.APP_CLOSE, risk=Risk.CAUTION)
        assert group_primary_action(member_offers=(offer,), group_kind=Category.BROWSER) == offer
        assert group_primary_action(
            member_offers=(offer,), group_kind=Category.PROJECT
        ) == ActionOffer(kind=Action.GROUP_STOP, risk=Risk.CAUTION)

    def test_targets_and_assessments_are_frozen(self) -> None:
        assessment = assess_risk(target=PROCESS, action=Action.PROCESS_TERMINATE)
        for target, field, value in (
            (PROCESS, "cwd", "/changed"),
            (assessment, "level", Risk.DANGER),
        ):
            with pytest.raises(FrozenInstanceError):
                setattr(target, field, value)

    @pytest.mark.parametrize("has_documents", [False, True])
    def test_idle_development_documents_override_safe(self, has_documents: bool) -> None:
        target = replace(PROCESS, has_documents=has_documents)
        result = assess_risk(target=target, action=Action.PROCESS_TERMINATE)
        assert result.level is (Risk.CAUTION if has_documents else Risk.SAFE)
        assert result.consequences == (
            "Eventuali file non salvati possono andare persi."
            if has_documents
            else "Il server si ferma. Si riavvia con lo stesso comando dalla sua cartella.",
        )

    @pytest.mark.parametrize("kind", ["process", "desktop_app", "browser"])
    @pytest.mark.parametrize("has_documents", [False, True])
    def test_sigkill_apps(self, kind: TargetKind, has_documents: bool) -> None:
        target = Target(kind=kind, has_documents=has_documents)
        result = assess_risk(target=target, action=Action.PROCESS_KILL)
        assert result.level is (Risk.DANGER if has_documents else Risk.CAUTION)
        assert result.consequences == ("Chiusura immediata senza salvataggio.",)

    @pytest.mark.parametrize(
        ("target", "text"),
        [
            (
                replace(PROCESS, category=Category.OTHER),
                "Il programma si ferma: ciò che ha in memoria e non ha salvato va perso. "
                "Se è un servizio, potrebbe riavviarsi da solo.",
            ),
            (
                replace(PROCESS, category=Category.DESKTOP_APP, has_documents=True),
                "Eventuali file non salvati possono andare persi.",
            ),
        ],
        ids=["user_service", "document_app_from_terminal"],
    )
    def test_other_deviation_reasons_stay_caution(self, target: Target, text: str) -> None:
        result = assess_risk(target=target, action=Action.PROCESS_TERMINATE)
        assert result.level is Risk.CAUTION
        assert result.consequences == (text,)

    @pytest.mark.parametrize("category", list(Category))
    @pytest.mark.parametrize("activity", [ActivityState.IDLE, ActivityState.ACTIVE])
    def test_foreground_consequences(self, category: Category, activity: ActivityState) -> None:
        target = replace(PROCESS, category=category, activity=activity)
        base = assess_risk(target=target, action=Action.PROCESS_TERMINATE)
        result = assess_risk(
            target=replace(target, is_foreground_on_tty=True), action=Action.PROCESS_TERMINATE
        )
        is_dev = category in (Category.DEV_PROCESS, Category.DEV_SERVER)
        is_idle_dev = is_dev and activity is ActivityState.IDLE
        assert base.level is (Risk.SAFE if is_idle_dev else Risk.CAUTION)
        assert result.level is max(Risk.CAUTION, base.level)
        assert result.consequences == (
            "È in esecuzione in primo piano in un terminale: "
            "potresti interrompere un lavoro in corso.",
            *base.consequences,
        )

    @pytest.mark.parametrize(
        ("kind", "facts", "missing"),
        [
            ("container", {}, "is_running"),
            ("image", {"dangling": False}, "has_repo_digests"),
            ("image", {"has_repo_digests": False}, "dangling"),
        ],
    )
    def test_required_facts(self, kind: TargetKind, facts: dict[str, bool], missing: str) -> None:
        with pytest.raises(ValueError, match=missing):
            Target(
                kind=kind,
                is_running=facts.get("is_running"),
                has_repo_digests=facts.get("has_repo_digests"),
                dangling=facts.get("dangling"),
            )

    @pytest.mark.parametrize("has_repo_digests", [False, True])
    def test_dangling_wins_over_repo_digests(self, has_repo_digests: bool) -> None:
        target = Target(kind="image", dangling=True, has_repo_digests=has_repo_digests)
        result = assess_risk(target=target, action=Action.IMAGE_REMOVE)
        assert result.level is Risk.SAFE
        assert result.consequences == ()
        assert assess_risk(
            target=replace(target, dangling=False), action=Action.IMAGE_REMOVE
        ).consequences

    def test_compose_stop_and_empty_volume_names_fallback(self) -> None:
        result = assess_risk(
            target=Target(kind="compose_project"), action=Action.COMPOSE_DOWN_VOLUMES
        )
        stop = assess_risk(target=Target(kind="compose_project"), action=Action.GROUP_STOP)
        assert ActionOffer(kind=Action.GROUP_STOP, risk=Risk.SAFE) in available_actions(
            target=Target(kind="compose_project")
        )
        assert stop.level is Risk.SAFE
        assert stop.consequences == (CONTAINER_TEXT,)
        assert result.level is Risk.DANGER
        assert result.consequences == (
            "I dati dei volumi associati al progetto vengono cancellati in modo definitivo.",
        )
