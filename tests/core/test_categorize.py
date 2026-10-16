from dataclasses import replace

import pytest

from wimm.core.categorize import (
    CategorizationContext,
    categorize_process,
    has_documents,
    is_terminal_shell,
)
from wimm.model.enums import Category, Protection, protection_of

from .helpers import DOCKER, FIREFOX, OLLAMA, TERMINAL, USER_PATH, VTE, ProcessChanges, process


def context() -> CategorizationContext:
    return CategorizationContext(
        own_uid=1000,
        own_pid=999,
        processes={},
        listen_ports_by_pid={},
        extra_protected_names=(),
        desktop_categories={},
    )


@pytest.mark.parametrize(
    ("changes", "category", "reason"),
    [
        ({"pid": 999, "uid": 0}, Category.SELF, "self"),
        ({"uid": 0}, Category.SYSTEM, "system"),
        ({"cgroup": "/user.slice/user-1000.slice/session-2.scope"}, Category.SYSTEM, "system"),
        ({"cgroup": "/user@10000.service/app.slice/foo.scope"}, Category.SYSTEM, "system"),
        ({"cgroup": USER_PATH + "session.slice/foo.service"}, Category.SESSION, "session"),
        ({"name": "gnome-shell"}, Category.SESSION, "protected_name"),
        ({"cgroup": FIREFOX}, Category.BROWSER, "scope"),
        ({"cgroup": USER_PATH + "app-gnome-code-42.scope"}, Category.DESKTOP_APP, "scope"),
        ({"name": "gnome-terminal-server", "cgroup": TERMINAL}, Category.TERMINAL, "scope"),
        ({"name": "claude"}, Category.AI_CLI, "ai_cli"),
        ({"cgroup": VTE}, Category.DEV_PROCESS, "terminal_process"),
        ({"cgroup": USER_PATH + "unrecognized.scope"}, Category.OTHER, "other"),
        ({"cgroup": OLLAMA}, Category.SYSTEM, "system"),
    ],
)
def test_ordered_rules(changes: ProcessChanges, category: Category, reason: str) -> None:
    decision = categorize_process(proc=process(**changes), context=context())
    assert (decision.category, decision.reason_code) == (category, reason)


@pytest.mark.parametrize("name", ["gnome-shell", "pipewire", "gsd-color", "gvfsd-metadata"])
def test_protected_names_globs(name: str) -> None:
    decision = categorize_process(proc=process(name=name), context=context())
    assert decision.category is not None
    assert protection_of(category=decision.category) is Protection.PROTECTED


def test_extra_names_add_without_removing_defaults() -> None:
    custom = replace(context(), extra_protected_names=("custom-*",))
    assert (
        categorize_process(proc=process(name="custom-agent"), context=custom).category
        is Category.SESSION
    )
    assert (
        categorize_process(proc=process(name="pipewire"), context=custom).category
        is Category.SESSION
    )
    assert (
        categorize_process(proc=process(name="custom-agent"), context=context()).category
        is Category.DEV_PROCESS
    )
    assert (
        categorize_process(proc=process(name="Pipewire"), context=custom).category
        is Category.DEV_PROCESS
    )


@pytest.mark.parametrize("uid", [1000, 0])
def test_docker_scope_is_excluded_before_system_rule(uid: int) -> None:
    decision = categorize_process(proc=process(uid=uid, cgroup=DOCKER), context=context())
    assert decision.category is None
    assert decision.reason_code == "excluded"


def test_docker_scope_inside_user_slice_is_excluded() -> None:
    decision = categorize_process(
        proc=process(cgroup=USER_PATH + "docker-id.scope"), context=context()
    )
    assert decision.reason_code == "excluded"


def test_own_pid_wins_over_docker_exclusion() -> None:
    decision = categorize_process(proc=process(pid=999, cgroup=DOCKER), context=context())
    assert decision.category is Category.SELF


@pytest.mark.parametrize(
    ("scope", "category", "appid"),
    [
        ("app-gnome-org.gnome.TextEditor-42.scope", Category.DESKTOP_APP, "org.gnome.TextEditor"),
        ("snap.slack.slack-uuid.scope", Category.DESKTOP_APP, "slack"),
        ("app-flatpak-com.spotify.Client-42.scope", Category.DESKTOP_APP, "com.spotify.Client"),
        ("snap.firefox.firefox-uuid.scope", Category.BROWSER, "firefox"),
        ("app-gnome-firefox-42.scope", Category.BROWSER, "firefox"),
        ("app-gnome-google-chrome-42.scope", Category.BROWSER, "google-chrome"),
        ("app-gnome-chromium-42.scope", Category.BROWSER, "chromium"),
        ("app-gnome-brave-42.scope", Category.BROWSER, "brave"),
        ("app-gnome-org.gnome.Terminal-42.scope", Category.TERMINAL, "org.gnome.Terminal"),
    ],
)
def test_scope_recognition(scope: str, category: Category, appid: str) -> None:
    decision = categorize_process(proc=process(cgroup=USER_PATH + scope), context=context())
    assert (decision.category, decision.appid, decision.scope) == (category, appid, scope)


@pytest.mark.parametrize(
    "name", ["firefox", "chromium", "chromium-browser", "brave", "google-chrome"]
)
def test_browser_executable(name: str) -> None:
    assert (
        categorize_process(proc=process(name=name), context=context()).category is Category.BROWSER
    )


def test_real_terminal_tree_does_not_inherit_terminal() -> None:
    terminal = process(pid=10, name="gnome-terminal-server", cgroup="0::" + TERMINAL)
    shell = process(pid=11, ppid=10, name="zsh", cgroup="0::" + VTE)
    server = process(pid=12, ppid=11, name="uvicorn", cgroup="0::" + VTE)
    ctx = replace(
        context(),
        processes={10: terminal, 11: shell, 12: server},
        listen_ports_by_pid={12: frozenset({8000})},
    )
    assert categorize_process(proc=terminal, context=ctx).category is Category.TERMINAL
    assert categorize_process(proc=shell, context=ctx).category is Category.DEV_PROCESS
    assert is_terminal_shell(proc=shell)
    assert categorize_process(proc=server, context=ctx).category is Category.DEV_SERVER


@pytest.mark.parametrize("name", ["pyright", "tsserver", "node", "uvicorn"])
def test_editor_descendants_inherit_even_with_listen(name: str) -> None:
    editor = process(pid=10, cgroup=USER_PATH + "app-gnome-code-42.scope", name="code")
    middle = process(pid=11, ppid=10, cgroup=VTE)
    child = process(pid=12, ppid=11, name=name)
    ctx = replace(
        context(), processes={10: editor, 11: middle}, listen_ports_by_pid={12: frozenset({8000})}
    )
    result = categorize_process(proc=child, context=ctx)
    assert (result.category, result.inherited_from, result.appid) == (
        Category.DESKTOP_APP,
        10,
        "code",
    )


def test_browser_descendant_inherits_and_cycles_terminate() -> None:
    browser = process(pid=10, cgroup=FIREFOX)
    ctx = replace(context(), processes={10: browser})
    assert categorize_process(proc=process(ppid=10), context=ctx).category is Category.BROWSER
    child = process(pid=20, ppid=21, cgroup=USER_PATH + "unknown.scope")
    parent = replace(child, pid=21, ppid=20)
    ctx = replace(context(), processes={20: child, 21: parent})
    assert categorize_process(proc=child, context=ctx).category is Category.OTHER


@pytest.mark.parametrize("name", ["bash", "zsh", "fish", "sh", "dash"])
def test_shell_predicate_and_shell_ancestry(name: str) -> None:
    shell = process(pid=10, name=name)
    assert is_terminal_shell(proc=shell)
    assert not is_terminal_shell(proc=replace(shell, cgroup=USER_PATH + "other.scope"))
    ctx = replace(context(), processes={10: shell})
    child = process(ppid=10, cgroup=USER_PATH + "other.scope")
    assert categorize_process(proc=child, context=ctx).category is Category.DEV_PROCESS
    assert not is_terminal_shell(proc=child)


@pytest.mark.parametrize("name", ["claude", "codex", "gemini", "agy", "aider"])
def test_ai_cli_name_or_command(name: str) -> None:
    assert (
        categorize_process(proc=process(name=name), context=context()).category is Category.AI_CLI
    )
    proc = process(name="node", cmdline=("node", "/usr/bin/" + name))
    assert categorize_process(proc=proc, context=context()).category is Category.AI_CLI


def test_ai_cli_requires_terminal_and_ollama_run_tokens() -> None:
    run = process(name="ollama", cmdline=("ollama", "run", "llama"))
    assert categorize_process(proc=run, context=context()).category is Category.AI_CLI
    assert (
        categorize_process(
            proc=replace(run, cmdline=("ollama", "serve")), context=context()
        ).category
        is Category.DEV_PROCESS
    )
    outside = replace(run, cgroup=USER_PATH + "unknown.scope")
    assert categorize_process(proc=outside, context=context()).category is Category.OTHER
    misleading = process(cmdline=("echo", "not-claude", "ollama run"))
    assert categorize_process(proc=misleading, context=context()).category is Category.DEV_PROCESS


def test_listen_rule_and_precedence() -> None:
    ctx = replace(context(), listen_ports_by_pid={20: frozenset({8000})})
    assert categorize_process(proc=process(), context=ctx).category is Category.DEV_SERVER
    assert categorize_process(proc=process(name="claude"), context=ctx).category is Category.AI_CLI
    assert (
        categorize_process(proc=process(name="pipewire"), context=ctx).category is Category.SESSION
    )


@pytest.mark.parametrize(
    ("appid", "categories", "name", "expected"),
    [
        ("code", {"code": ("IDE",)}, "worker", True),
        ("code", {"code": ("Audio",)}, "code", False),
        ("code", {"code": ()}, "code", False),
        ("missing", {}, "code", True),
        (None, {}, "slack", True),
        (None, {}, "spotify", False),
    ],
)
def test_documents(
    appid: str | None, categories: dict[str, tuple[str, ...]], name: str, expected: bool
) -> None:
    assert has_documents(appid=appid, categories=categories, process_name=name) is expected


@pytest.mark.parametrize(
    "service",
    [
        "gsd-color",
        "evolution-source-registry",
        "tracker-miner-fs",
        "gvfs-daemon",
        "xdg-desktop-portal-gtk",
        "at-spi-bus",
        "ibus-daemon",
    ],
)
def test_session_service_cgroups(service: str) -> None:
    proc = process(cgroup=USER_PATH + service + ".service")
    decision = categorize_process(proc=proc, context=context())
    assert (decision.category, decision.reason_code) == (Category.SESSION, "session")


def test_systemd_user_and_protected_ancestor() -> None:
    proc = process(name="systemd", cmdline=("systemd", "--user"))
    decision = categorize_process(proc=proc, context=context())
    assert (decision.category, decision.reason_code) == (Category.SESSION, "session")
    protected = process(pid=10, name="pipewire", cgroup=FIREFOX)
    child = process(ppid=10)
    ctx = replace(context(), processes={10: protected})
    assert categorize_process(proc=child, context=ctx).category is Category.DEV_PROCESS


@pytest.mark.parametrize("name", ["chrome", "renamed-browser"])
def test_browser_executable_and_descendant(name: str) -> None:
    browser = replace(process(pid=10, name=name), exe="/opt/google/chrome/chrome")
    ctx = replace(context(), processes={10: browser})
    assert categorize_process(proc=browser, context=ctx).category is Category.BROWSER
    assert categorize_process(proc=process(ppid=10), context=ctx).category is Category.BROWSER


def test_ai_cli_argument_is_not_an_entrypoint() -> None:
    reader = process(name="cat", cmdline=("cat", "/home/user/documents/claude"))
    assert categorize_process(proc=reader, context=context()).category is Category.DEV_PROCESS
    wrapper = process(name="node", cmdline=("node", "/usr/bin/claude"))
    assert categorize_process(proc=wrapper, context=context()).category is Category.AI_CLI
