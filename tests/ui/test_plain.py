from datetime import datetime, timedelta

import pytest

from wimm.model.enums import ActivityState
from wimm.model.snapshot import ActivityAssessment
from wimm.ui.plain import friendly_container_name, friendly_process_name, plain_reason

NOW = datetime.fromisoformat("2026-10-16T10:12:00+02:00")


def test_idle_server_reads_as_nobody_connecting() -> None:
    text = plain_reason(
        activity=ActivityAssessment(
            state=ActivityState.IDLE,
            reason="nessuna connessione in ingresso",
            since=NOW - timedelta(hours=5, minutes=3),
        ),
        now=NOW,
    )
    assert text == "Non lo usi da 5 ore: nessuno ci si collega."


def test_idle_since_the_monitor_started_says_at_least() -> None:
    text = plain_reason(
        activity=ActivityAssessment(
            state=ActivityState.IDLE,
            reason="inattivo da almeno 2 h, cioè da quando il monitor è partito; CPU media 0,0%",
            since=NOW - timedelta(hours=2),
        ),
        now=NOW,
    )
    # A container is idle on CPU and network, not on connections: no "nessuno ci si collega".
    assert text == "Non lo usi da almeno 2 ore."


def test_idle_tool_without_connections_just_says_since_when() -> None:
    text = plain_reason(
        activity=ActivityAssessment(
            state=ActivityState.IDLE, reason="CPU media 0,0%", since=NOW - timedelta(minutes=40)
        ),
        now=NOW,
    )
    assert text == "Non lo usi da 40 minuti."


@pytest.mark.parametrize(
    ("state", "reason", "text"),
    [
        (ActivityState.ACTIVE, "attività rilevata da 3 minuti", "Lo stai usando adesso."),
        (
            ActivityState.UNKNOWN,
            "attività non misurabile per i browser",
            "Non sappiamo se lo stai usando: decidi tu se chiuderlo.",
        ),
        (
            ActivityState.UNKNOWN,
            "in osservazione da 4 minuti",
            "Lo stiamo osservando: tra poco sappiamo se lo usi.",
        ),
    ],
)
def test_plain_reason_for_states_without_idle_time(
    state: ActivityState, reason: str, text: str
) -> None:
    got = plain_reason(
        # The model requires a start time for active states, never for unknown ones.
        activity=ActivityAssessment(
            state=state, reason=reason, since=NOW if state is ActivityState.ACTIVE else None
        ),
        now=NOW,
    )
    assert got == text


@pytest.mark.parametrize(
    ("image", "name"),
    [
        ("quay.io/keycloak/keycloak:26.0.8", "Accesso utenti"),
        ("postgres:16", "Database"),
        ("redis:7-alpine", "Memoria veloce (cache)"),
        ("bitnami/postgresql:16", "Database"),
        ("localhost:5000/redis:7", "Memoria veloce (cache)"),
        ("ollama/ollama", "Modelli AI locali"),
    ],
)
def test_known_images_get_a_name_of_use(image: str, name: str) -> None:
    assert friendly_container_name(image=image) == name


@pytest.mark.parametrize(
    "image",
    ["registry.example/acme/billing:1", "provectuslabs/kafka-ui", "mongo-express", "redisinsight"],
)
def test_tools_around_a_known_service_are_not_named_like_it(image: str) -> None:
    assert friendly_container_name(image=image) is None


@pytest.mark.parametrize(
    ("process", "name"),
    [
        ("uvicorn", "Server web"),
        ("vite", "Server dell'interfaccia"),
        ("jupyter-lab", "Quaderni Jupyter"),
    ],
)
def test_known_processes_get_a_name_of_use(process: str, name: str) -> None:
    assert friendly_process_name(name=process) == name


def test_generic_process_names_stay_technical() -> None:
    # "node" or "python" say nothing about what the program does.
    assert friendly_process_name(name="node") is None
    assert friendly_process_name(name="python3") is None
    assert friendly_process_name(name="nextcloud-sync") is None
