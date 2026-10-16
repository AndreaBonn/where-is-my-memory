from dataclasses import replace

import pytest

from wimm.core.categorize import categorize_process, has_documents
from wimm.model.enums import Category

from .helpers import USER_PATH, VTE, process
from .test_categorize import context


def test_escaped_scope_browser_and_desktop_metadata() -> None:
    browser = process(
        name="chrome_crashpad", cgroup=USER_PATH + r"app-gnome-google\x2dchrome-123.scope"
    )
    assert categorize_process(proc=browser, context=context()).category is Category.BROWSER
    app = process(cgroup=USER_PATH + r"app-gnome-update\x2dnotifier-14943.scope")
    ctx = replace(context(), desktop_categories={"update-notifier": ("Office",)})
    result = categorize_process(proc=app, context=ctx)
    assert result.appid == "update-notifier"
    assert has_documents(
        appid=result.appid, categories=ctx.desktop_categories, process_name=app.name
    )
    handler = process(cgroup=USER_PATH + "app-gnome-code-url-handler-42.scope")
    assert categorize_process(proc=handler, context=ctx).category is Category.DESKTOP_APP


@pytest.mark.parametrize("source", ["exe", "cmdline"])
def test_protected_truncated_name_uses_executable_identity(source: str) -> None:
    truncated = process(name="gnome-session-b")
    protected = replace(truncated, exe="/usr/libexec/gnome-session-binary")
    if source == "cmdline":
        protected = replace(truncated, cmdline=("/usr/libexec/gnome-session-binary",))
    result = categorize_process(proc=protected, context=context())
    assert (result.category, result.reason_code) == (Category.SESSION, "protected_name")
    assert categorize_process(proc=truncated, context=context()).category is Category.DEV_PROCESS


@pytest.mark.parametrize("slice_name", ["app.slice", "session.slice"])
@pytest.mark.parametrize("name", ["syncthing", "ollama"])
def test_user_services_are_conservative_even_with_shell_parent(slice_name: str, name: str) -> None:
    root = USER_PATH.removesuffix("app.slice/") + slice_name + "/"
    service = process(name=name, ppid=10, cgroup=root + name + ".service")
    ctx = replace(
        context(),
        processes={10: process(pid=10, name="bash")},
        listen_ports_by_pid={20: frozenset({8000})},
    )
    result = categorize_process(proc=service, context=ctx)
    assert (result.category, result.reason_code) == (Category.OTHER, "user_service")
    terminal = replace(service, cgroup=VTE)
    assert categorize_process(proc=terminal, context=ctx).category is Category.DEV_SERVER


@pytest.mark.parametrize("source", ["name", "exe", "cmdline"])
def test_document_app_from_terminal_and_descendant(source: str) -> None:
    editor = process(pid=10, name="code", cmdline=("code", "."))
    if source == "exe":
        editor = replace(editor, name="renamed", exe="/usr/bin/code", cmdline=None)
    if source == "cmdline":
        editor = replace(editor, name="renamed", cmdline=("/usr/bin/code", "."))
    ctx = replace(context(), processes={10: editor}, listen_ports_by_pid={20: frozenset({8000})})
    result = categorize_process(proc=editor, context=ctx)
    assert (result.category, result.reason_code, result.appid) == (
        Category.DESKTOP_APP,
        "document_app_from_terminal",
        "code",
    )
    child = categorize_process(proc=process(ppid=10), context=ctx)
    assert (child.category, child.inherited_from) == (Category.DESKTOP_APP, 10)
    assert categorize_process(proc=process(), context=ctx).category is Category.DEV_SERVER


@pytest.mark.parametrize("name", ["firefox", "google-chrome", "chromium", "brave-browser", "brave"])
@pytest.mark.parametrize(
    "form",
    ["snap.{name}.app-1.scope", "app-gnome-{name}-1.scope", "app-flatpak-org.{name}.App-1.scope"],
)
def test_browser_scope_patterns_are_anchored(name: str, form: str) -> None:
    browser = process(cgroup=USER_PATH + form.format(name=name))
    assert categorize_process(proc=browser, context=context()).category is Category.BROWSER
    unrelated = process(cgroup=USER_PATH + "snap.brave-tools.foo-1.scope")
    assert categorize_process(proc=unrelated, context=context()).category is Category.DESKTOP_APP


@pytest.mark.parametrize("interpreter", ["node", "python", "python3", "bun", "deno"])
def test_ai_cli_skips_interpreter_options(interpreter: str) -> None:
    cli = process(name=interpreter, cmdline=(interpreter, "--inspect", "-x", "/usr/bin/claude"))
    assert categorize_process(proc=cli, context=context()).category is Category.AI_CLI
    other = replace(cli, cmdline=(interpreter, "--inspect", "/usr/bin/server", "claude"))
    assert categorize_process(proc=other, context=context()).category is Category.DEV_PROCESS
    options = replace(cli, cmdline=(interpreter, "--inspect"))
    assert categorize_process(proc=options, context=context()).category is Category.DEV_PROCESS


@pytest.mark.parametrize("slice_name", ["app.slice", "session.slice"])
def test_user_service_preserves_known_session_and_terminal(slice_name: str) -> None:
    root = USER_PATH.removesuffix("app.slice/") + slice_name + "/"
    known = process(cgroup=root + r"gsd\x2dcolor.service")
    assert categorize_process(proc=known, context=context()).category is Category.SESSION
    terminal = replace(
        process(cgroup=root + "terminal.service"), exe="/usr/bin/gnome-terminal-server"
    )
    assert categorize_process(proc=terminal, context=context()).category is Category.TERMINAL


def test_document_name_outside_vte_remains_other() -> None:
    editor = process(name="code", cgroup=USER_PATH + "unknown.scope")
    assert categorize_process(proc=editor, context=context()).category is Category.OTHER
    assert (
        categorize_process(proc=replace(editor, cgroup=VTE), context=context()).category
        is Category.DESKTOP_APP
    )
