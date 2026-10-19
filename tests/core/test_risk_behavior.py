from dataclasses import FrozenInstanceError, replace
from typing import get_args

import pytest

from tests.core.risk_helpers import CONTAINER_TEXT, PROCESS
from wimm.core.risk import RiskTarget as Target
from wimm.core.risk import TargetKind, assess_risk, available_actions, group_primary_action
from wimm.model.enums import ActionKind as Action
from wimm.model.enums import ActivityState, Category, Risk
from wimm.model.snapshot import ActionOffer

# C3: how to restart moves to its own line of the dialog, "Per riaccenderlo".
FOREGROUND_TEXT = (
    "È in esecuzione in primo piano in un terminale: potresti interrompere un lavoro in corso."
)
IDLE_TEXT = "Il server si ferma."
IDLE_PROGRAM_TEXT = "Il programma si ferma."
ACTIVE_TEXT = "È in uso adesso: chi lo sta usando perde la connessione."
AGENT_TEXT = (
    "La sessione dell'agente si chiude: il lavoro non salvato nella conversazione si perde."
)
BROWSER_TEXT = (
    "Il browser si chiude senza la chiusura normale: alla riapertura ripristina le schede "
    "dal salvataggio automatico, che può essere indietro di qualche secondo."
)
APP_TEXT = "L'applicazione si chiude."
TERMINAL_TEXT = (
    "Si chiudono tutte le finestre e le schede del terminale e i programmi al loro interno."
)
OTHER_TEXT = (
    "Il programma si ferma: ciò che ha in memoria e non ha salvato va perso. "
    "Se è un servizio, potrebbe riavviarsi da solo."
)


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
            else "Il programma si ferma.",
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

    @pytest.mark.parametrize(
        ("category", "activity", "base_level", "base_text"),
        [
            (Category.SYSTEM, ActivityState.IDLE, Risk.CAUTION, APP_TEXT),
            (Category.CONTAINER, ActivityState.IDLE, Risk.CAUTION, APP_TEXT),
            (Category.AI_CLI, ActivityState.IDLE, Risk.CAUTION, AGENT_TEXT),
            (Category.BROWSER, ActivityState.IDLE, Risk.CAUTION, BROWSER_TEXT),
            (Category.DESKTOP_APP, ActivityState.IDLE, Risk.CAUTION, APP_TEXT),
            (Category.TERMINAL, ActivityState.IDLE, Risk.CAUTION, TERMINAL_TEXT),
            (Category.SESSION, ActivityState.IDLE, Risk.CAUTION, APP_TEXT),
            (Category.SELF, ActivityState.IDLE, Risk.CAUTION, APP_TEXT),
            (Category.OTHER, ActivityState.IDLE, Risk.CAUTION, OTHER_TEXT),
            (Category.PROJECT, ActivityState.IDLE, Risk.CAUTION, APP_TEXT),
            (Category.DEV_SERVER, ActivityState.IDLE, Risk.SAFE, IDLE_TEXT),
            (Category.DEV_PROCESS, ActivityState.IDLE, Risk.SAFE, IDLE_PROGRAM_TEXT),
            (Category.SYSTEM, ActivityState.ACTIVE, Risk.CAUTION, APP_TEXT),
            (Category.CONTAINER, ActivityState.ACTIVE, Risk.CAUTION, APP_TEXT),
            (Category.AI_CLI, ActivityState.ACTIVE, Risk.CAUTION, AGENT_TEXT),
            (Category.BROWSER, ActivityState.ACTIVE, Risk.CAUTION, BROWSER_TEXT),
            (Category.DESKTOP_APP, ActivityState.ACTIVE, Risk.CAUTION, APP_TEXT),
            (Category.TERMINAL, ActivityState.ACTIVE, Risk.CAUTION, TERMINAL_TEXT),
            (Category.SESSION, ActivityState.ACTIVE, Risk.CAUTION, APP_TEXT),
            (Category.SELF, ActivityState.ACTIVE, Risk.CAUTION, APP_TEXT),
            (Category.OTHER, ActivityState.ACTIVE, Risk.CAUTION, OTHER_TEXT),
            (Category.PROJECT, ActivityState.ACTIVE, Risk.CAUTION, APP_TEXT),
            (Category.DEV_SERVER, ActivityState.ACTIVE, Risk.CAUTION, ACTIVE_TEXT),
            (Category.DEV_PROCESS, ActivityState.ACTIVE, Risk.CAUTION, ACTIVE_TEXT),
        ],
    )
    def test_foreground_consequences(
        self, category: Category, activity: ActivityState, base_level: Risk, base_text: str
    ) -> None:
        target = replace(PROCESS, category=category, activity=activity)
        base = assess_risk(target=target, action=Action.PROCESS_TERMINATE)
        result = assess_risk(
            target=replace(target, is_foreground_on_tty=True), action=Action.PROCESS_TERMINATE
        )
        assert base.level is base_level
        assert base.consequences == (base_text,)
        assert result.level is Risk.CAUTION
        assert result.consequences == (FOREGROUND_TEXT, base_text)

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
        assert result.consequences == (
            "Nessun nome punta più a questa immagine e nessun contenitore la usa: "
            "sparisce senza perdere niente.",
        )
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
