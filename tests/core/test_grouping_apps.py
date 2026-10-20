from collections.abc import Mapping
from dataclasses import replace
from typing import Unpack

from wimm.core.categorize import CategoryDecision
from wimm.core.grouping import GroupDraft, GroupingInput, build_groups
from wimm.model.enums import Category
from wimm.model.raw import RawProcess

from .helpers import FIREFOX, TERMINAL, USER_PATH, VTE, ProcessChanges, process

HOME = "/home/u"
CODE_SCOPE = USER_PATH + "app-gnome-code-1.scope"

Pair = tuple[RawProcess, CategoryDecision]


def pair(
    pid: int,
    category: Category,
    /,
    *,
    appid: str | None = None,
    scope: str | None = None,
    **changes: Unpack[ProcessChanges],
) -> Pair:
    proc = replace(process(**changes), pid=pid)
    return proc, CategoryDecision(category=category, reason_code="x", appid=appid, scope=scope)


def build(
    pairs: tuple[Pair, ...], names: Mapping[str, str] | None = None
) -> tuple[GroupDraft, ...]:
    return build_groups(
        grouping=GroupingInput(
            pairs=pairs,
            containers=(),
            project_root_by_cwd={},
            desktop_name_by_appid=names or {},
            own_home=HOME,
            own_uid=1000,
        )
    )


def test_build_groups_child_of_desktop_app_joins_the_app_group() -> None:
    code = pair(10, Category.DESKTOP_APP, appid="code", name="code", cgroup=CODE_SCOPE)
    pyright = pair(
        11, Category.DESKTOP_APP, appid="code", name="pyright", ppid=10, cgroup=CODE_SCOPE
    )

    groups = build((pyright, code), names={"code": "Visual Studio Code"})

    assert len(groups) == 1
    assert groups[0].category is Category.DESKTOP_APP
    assert groups[0].name == "Visual Studio Code"
    assert groups[0].process_pids == (10, 11)
    assert groups[0].explanation == "app desktop Visual Studio Code con 2 processi"


def test_build_groups_desktop_app_without_desktop_entry_is_named_by_appid() -> None:
    groups = build((pair(10, Category.DESKTOP_APP, appid="org.example.Tool"),))

    assert groups[0].name == "org.example.Tool"
    assert groups[0].explanation == "app desktop org.example.Tool con un processo"


def test_build_groups_app_without_appid_uses_scope_then_process_name() -> None:
    by_scope = build((pair(10, Category.DESKTOP_APP, scope="app-x.scope"),))
    by_name = build((pair(11, Category.DESKTOP_APP, name="orphan"),))

    assert by_scope[0].key == "app-x.scope"
    assert by_name[0].key == "orphan"


def test_build_groups_browser_tabs_share_one_browser_group() -> None:
    main = pair(10, Category.BROWSER, appid="firefox", name="firefox", cgroup=FIREFOX)
    tabs = tuple(
        pair(
            pid, Category.BROWSER, appid="firefox", name="Isolated Web Co", ppid=10, cgroup=FIREFOX
        )
        for pid in (11, 12, 13)
    )

    groups = build((main, *tabs), names={"firefox": "Firefox"})

    assert len(groups) == 1
    assert groups[0].category is Category.BROWSER
    assert groups[0].name == "Firefox"
    assert groups[0].process_pids == (10, 11, 12, 13)
    assert groups[0].explanation == "browser Firefox con 4 processi (schede, estensioni e servizi)"


def test_build_groups_shells_go_to_the_terminal_group() -> None:
    server = pair(
        10, Category.TERMINAL, appid="org.gnome.Terminal", name="gnome-terminal-", cgroup=TERMINAL
    )
    shell = pair(11, Category.DEV_PROCESS, name="bash", ppid=10, cgroup=VTE)
    inner = pair(12, Category.DEV_PROCESS, name="zsh", ppid=11, cgroup=VTE)

    groups = build((server, shell, inner), names={"org.gnome.Terminal": "Terminale"})

    assert len(groups) == 1
    assert groups[0].category is Category.TERMINAL
    assert groups[0].name == "Terminale"
    assert groups[0].process_pids == (10, 11, 12)
    assert groups[0].explanation == "terminale Terminale con 3 processi, shell comprese"


def test_build_groups_non_shell_below_a_terminal_is_not_pulled_into_it() -> None:
    server = pair(10, Category.TERMINAL, appid="org.gnome.Terminal", cgroup=TERMINAL)
    worker = pair(11, Category.DEV_PROCESS, name="worker", ppid=10, cwd="/work/x", cgroup=VTE)

    groups = build((server, worker))

    assert sorted(g.category.value for g in groups) == ["DEV_PROCESS", "TERMINAL"]


def test_build_groups_orphan_shell_forms_terminal_group_by_root_process() -> None:
    shell = pair(11, Category.DEV_PROCESS, name="bash", ppid=1, cgroup=VTE)
    nested = pair(12, Category.DEV_PROCESS, name="bash", ppid=11, cgroup=VTE)

    groups = build((shell, nested))

    assert len(groups) == 1
    assert groups[0].category is Category.TERMINAL
    assert groups[0].name == "bash"
    assert groups[0].process_pids == (11, 12)


def test_build_groups_process_cycle_does_not_hang() -> None:
    first = pair(5, Category.OTHER, name="loop", ppid=6)
    second = pair(6, Category.OTHER, name="loop", ppid=5)
    shell_a = pair(7, Category.DEV_PROCESS, name="bash", ppid=8, cgroup=VTE)
    shell_b = pair(8, Category.DEV_PROCESS, name="bash", ppid=7, cgroup=VTE)

    groups = build((first, second, shell_a, shell_b))

    assert sorted(g.category.value for g in groups) == ["OTHER", "TERMINAL"]


def test_build_groups_other_processes_group_by_root_process_and_cwd() -> None:
    root = pair(10, Category.OTHER, name="syncthing", cwd="/srv/a")
    child = pair(11, Category.OTHER, name="syncthing-helper", ppid=10, cwd="/srv/a")
    unrelated = pair(20, Category.OTHER, name="syncthing", cwd="/srv/b")

    groups = build((child, root, unrelated))

    assert [(g.key, g.process_pids) for g in groups] == [
        ("syncthing|/srv/a", (10, 11)),
        ("syncthing|/srv/b", (20,)),
    ]
    assert groups[0].explanation == ("2 processi non riconducibili a un progetto o a un'app")
    assert (
        groups[1].explanation == "un processo syncthing non riconducibile a un progetto o a un'app"
    )


def test_build_groups_protected_processes_map_to_rf07_labels() -> None:
    pairs = (
        pair(1, Category.SYSTEM, name="systemd"),
        pair(2, Category.SYSTEM, name="cron"),
        pair(3, Category.SYSTEM, name="sshd", uid=1001),
        pair(4, Category.SESSION, name="gnome-shell"),
        pair(5, Category.SESSION, name="pipewire"),
        pair(6, Category.SESSION, name="wireplumber"),
        pair(7, Category.SELF, name="wimm"),
        pair(8, Category.SYSTEM, name="Xorg", uid=0),
    )

    groups = {g.key: g for g in build(pairs)}

    assert {key: (g.name, g.category, g.process_pids) for key, g in groups.items()} == {
        "self": ("where-is-my-memory", Category.SELF, (7,)),
        "session-audio": ("Audio", Category.SESSION, (5, 6)),
        "session-gnome": ("Sessione GNOME", Category.SESSION, (4,)),
        "other-users": ("Altri utenti", Category.SYSTEM, (3,)),
        "system-services": ("Servizi di sistema", Category.SYSTEM, (1, 2, 8)),
    }
    assert groups["system-services"].explanation == (
        "Servizi di sistema: Xorg, cron, systemd, non modificabile da qui"
    )
    assert groups["session-audio"].explanation == (
        "Audio: pipewire, wireplumber, non modificabile da qui"
    )


def test_build_groups_protected_explanation_caps_names_at_eight() -> None:
    names = [f"svc{i:02d}" for i in range(11)]
    pairs = tuple(pair(100 + i, Category.SYSTEM, name=n) for i, n in enumerate([*names, "svc00"]))

    (group,) = build(pairs)

    assert group.explanation == (
        "Servizi di sistema: svc00, svc01, svc02, svc03, svc04, svc05, svc06, svc07 "
        "e altri 3, non modificabile da qui"
    )


def test_build_groups_protected_ids_are_stable_across_pids() -> None:
    first = build((pair(1, Category.SYSTEM, name="systemd"),))
    second = build((pair(500, Category.SYSTEM, name="cron"),))

    assert first[0].id == second[0].id


def test_build_groups_shell_of_a_desktop_app_stays_in_the_app_group() -> None:
    code = pair(10, Category.DESKTOP_APP, appid="code", name="code", cgroup=CODE_SCOPE)
    integrated = pair(11, Category.DESKTOP_APP, appid="code", name="bash", ppid=10, cgroup=VTE)
    server = pair(5, Category.TERMINAL, appid="org.gnome.Terminal", cgroup=TERMINAL)
    code_under_terminal = pair(12, Category.BROWSER, appid="firefox", name="sh", ppid=5, cgroup=VTE)

    groups = {g.key: g for g in build((code, integrated, server, code_under_terminal))}

    assert groups["code"].process_pids == (10, 11)
    assert groups["firefox"].process_pids == (12,)
    assert groups["org.gnome.Terminal"].process_pids == (5,)


def test_build_groups_dev_server_explanation_names_folder_and_port() -> None:
    server = pair(10, Category.DEV_SERVER, name="uvicorn", cwd="/work/whitebox")
    groups = build_groups(
        grouping=GroupingInput(
            pairs=(server,),
            containers=(),
            project_root_by_cwd={"/work/whitebox": "/work/whitebox"},
            desktop_name_by_appid={},
            own_home=HOME,
            own_uid=1000,
            listen_ports_by_pid={10: frozenset({8000})},
        )
    )

    assert groups[0].explanation == (
        "un processo uvicorn in ascolto sulla porta 8000 nella cartella whitebox"
    )


def test_build_groups_dev_process_without_folder_omits_it() -> None:
    groups = build((pair(10, Category.DEV_PROCESS, name="make", cwd=None),))

    assert groups[0].explanation == "un processo make lanciato dal terminale"


def test_build_groups_output_is_sorted_and_deterministic() -> None:
    pairs = (
        pair(3, Category.OTHER, name="zzz"),
        pair(2, Category.OTHER, name="aaa"),
    )

    assert build(pairs) == build(tuple(reversed(pairs)))
    assert [g.name for g in build(pairs)] == ["aaa", "zzz"]


def test_build_groups_dev_server_without_ports_does_not_claim_terminal() -> None:
    groups = build((pair(10, Category.DEV_SERVER, name="vite", cwd=None),))

    assert groups[0].explanation == "un processo vite"
