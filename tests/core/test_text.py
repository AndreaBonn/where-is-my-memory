from dataclasses import replace
from typing import TypedDict, Unpack

import pytest

from wimm.core import text
from wimm.model.enums import Category


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.0, "0,0"), (0.1, "0,1"), (12.34, "12,3"), (1.0, "1,0"), (99.96, "100,0")],
)
def test_format_decimal_uses_italian_comma(value: float, expected: str) -> None:
    assert text.format_decimal(value=value) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "meno di 1 minuto"),
        (59, "meno di 1 minuto"),
        (60, "1 minuto"),
        (240, "4 minuti"),
        (1800, "30 minuti"),
        (7199, "119 minuti"),
        (7200, "2 h"),
        (3 * 3600 + 1799, "3 h"),
        (47 * 3600 + 3599, "47 h"),
        (48 * 3600, "2 giorni"),
        (5 * 86400, "5 giorni"),
    ],
)
def test_format_duration_boundaries(seconds: float, expected: str) -> None:
    assert text.format_duration(seconds=seconds) == expected


def test_format_duration_negative_is_clamped() -> None:
    assert text.format_duration(seconds=-5) == "meno di 1 minuto"


def test_reason_observing_names_elapsed_time() -> None:
    assert text.reason_observing(elapsed_s=240) == "in osservazione da 4 minuti"


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        (Category.BROWSER, "attività non misurabile per i browser"),
        (Category.DESKTOP_APP, "attività non misurabile per le app desktop"),
        (Category.TERMINAL, "attività non misurabile per i terminali"),
    ],
)
def test_reason_unmeasurable_per_category(category: Category, expected: str) -> None:
    assert text.reason_unmeasurable(category=category) == expected


def test_reason_unmeasurable_other_category_is_generic() -> None:
    assert text.reason_unmeasurable(category=Category.OTHER) == "attività non misurabile"


def test_reason_active_names_duration() -> None:
    assert text.reason_active(active_for_s=720) == "attività rilevata da 12 minuti"


def test_reason_idle_server_without_connections() -> None:
    facts = text.IdleFacts(
        window_s=1800, cpu_avg_pct=0.1, net_avg_bps=None, watches_connections=True, open_port=None
    )
    reason = text.reason_idle(idle_for_s=3 * 3600, facts=facts, from_monitor_start=False)
    assert reason == (
        "inattivo da 3 h; nessuna connessione in ingresso e CPU media 0,1% negli ultimi 30 minuti"
    )


def test_reason_idle_server_with_forgotten_tab() -> None:
    facts = text.IdleFacts(
        window_s=1800, cpu_avg_pct=0.1, net_avg_bps=None, watches_connections=True, open_port=5173
    )
    reason = text.reason_idle(idle_for_s=3 * 3600, facts=facts, from_monitor_start=False)
    assert reason == (
        "inattivo da 3 h; nessuna connessione nuova e CPU media 0,1% negli ultimi 30 minuti; "
        "c'è una connessione aperta da un browser "
        "(probabile scheda dimenticata su localhost:5173)"
    )


def test_reason_idle_process_has_only_cpu() -> None:
    facts = text.IdleFacts(
        window_s=1800, cpu_avg_pct=0.0, net_avg_bps=None, watches_connections=False, open_port=None
    )
    reason = text.reason_idle(idle_for_s=600, facts=facts, from_monitor_start=False)
    assert reason == "inattivo da 10 minuti; CPU media 0,0% negli ultimi 30 minuti"


def test_reason_idle_container_reports_network_rate() -> None:
    facts = text.IdleFacts(
        window_s=1800, cpu_avg_pct=0.2, net_avg_bps=12.4, watches_connections=False, open_port=None
    )
    reason = text.reason_idle(idle_for_s=7200, facts=facts, from_monitor_start=False)
    assert reason == (
        "inattivo da 2 h; CPU media 0,2% e traffico di rete medio 12 B/s negli ultimi 30 minuti"
    )


def test_reason_idle_since_monitor_start_says_so() -> None:
    facts = text.IdleFacts(
        window_s=1800, cpu_avg_pct=0.0, net_avg_bps=None, watches_connections=False, open_port=None
    )
    reason = text.reason_idle(idle_for_s=3 * 3600, facts=facts, from_monitor_start=True)
    assert reason.startswith("inattivo da almeno 3 h, cioè da quando il monitor è partito; ")


def test_reason_idle_persisted_mentions_restart() -> None:
    reason = text.reason_idle_persisted(idle_for_s=3 * 3600, observed_s=240)
    assert reason == (
        "inattivo da 3 h; ultima attività registrata prima del riavvio, in osservazione da 4 minuti"
    )


def test_reason_cpu_unavailable() -> None:
    assert text.reason_cpu_unavailable() == "CPU non misurabile negli ultimi campioni"


def test_reason_not_evaluated() -> None:
    assert text.reason_not_evaluated() == "attività non valutata per questa categoria"


@pytest.mark.parametrize(
    ("active", "measurable", "expected"),
    [
        (1, 1, "l'unico membro misurabile è attivo"),
        (1, 3, "1 membro attivo su 3 misurabili"),
        (2, 2, "2 membri attivi su 2 misurabili"),
        (2, 3, "2 membri attivi su 3 misurabili"),
    ],
)
def test_group_active_reason_agrees_in_number(active: int, measurable: int, expected: str) -> None:
    assert text.reason_group_active(active=active, measurable=measurable) == expected


@pytest.mark.parametrize(
    ("measurable", "expected"),
    [
        (1, "l'unico membro misurabile è inattivo"),
        (2, "entrambi i membri misurabili sono inattivi"),
        (3, "tutti i 3 membri misurabili sono inattivi"),
    ],
)
def test_group_idle_reason_agrees_in_number(measurable: int, expected: str) -> None:
    assert text.reason_group_idle(measurable=measurable) == expected


@pytest.mark.parametrize(
    ("measurable", "expected"),
    [
        (0, "nessun membro misurabile"),
        (1, "attività dell'unico membro misurabile ancora non determinata"),
        (2, "attività di almeno uno dei 2 membri misurabili ancora non determinata"),
        (3, "attività di almeno uno dei 3 membri misurabili ancora non determinata"),
    ],
)
def test_group_unknown_reason_agrees_in_number(measurable: int, expected: str) -> None:
    assert text.reason_group_unknown(measurable=measurable) == expected


class FactsChanges(TypedDict, total=False):
    category: Category
    name: str
    folder: str | None
    containers: int
    processes: int
    ports: tuple[int, ...]
    compose_project: str | None
    lead_process: str | None


def _facts(**changes: Unpack[FactsChanges]) -> text.GroupFacts:
    base = text.GroupFacts(
        category=Category.OTHER,
        name="x",
        folder=None,
        containers=0,
        processes=1,
        ports=(),
        compose_project=None,
        lead_process=None,
    )
    return replace(base, **changes)


@pytest.mark.parametrize(
    ("ports", "expected"),
    [
        ((), "un processo uvicorn"),
        ((80,), "un processo uvicorn in ascolto sulla porta 80"),
        ((80, 81), "un processo uvicorn in ascolto sulle porte 80 e 81"),
        ((80, 81, 82), "un processo uvicorn in ascolto sulle porte 80, 81 e 82"),
    ],
)
def test_explain_group_dev_server_lists_ports_without_terminal_claim(
    ports: tuple[int, ...], expected: str
) -> None:
    facts = _facts(category=Category.DEV_SERVER, lead_process="uvicorn", ports=ports)

    assert text.explain_group(facts=facts) == expected


def test_explain_group_launched_plural_and_folder_basename() -> None:
    facts = _facts(category=Category.AI_CLI, processes=3, folder="/work/api/")

    assert text.explain_group(facts=facts) == (
        "3 processi lanciati dal terminale nella cartella api"
    )


def test_explain_group_one_container_is_singular_count() -> None:
    facts = _facts(
        category=Category.CONTAINER, containers=1, processes=0, compose_project="p", folder="/srv"
    )

    assert text.explain_group(facts=facts) == "progetto compose 'p' con 1 container in /srv"


def test_explain_group_process_without_lead_name() -> None:
    assert text.explain_group(facts=_facts()) == (
        "un processo non riconducibile a un progetto o a un'app"
    )


def test_explain_group_dev_process_keeps_launched_from_terminal() -> None:
    facts = _facts(category=Category.DEV_PROCESS, lead_process="make", ports=(80,))

    assert text.explain_group(facts=facts) == (
        "un processo make lanciato dal terminale, in ascolto sulla porta 80"
    )
