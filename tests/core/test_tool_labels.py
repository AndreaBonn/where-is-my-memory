import pytest

from wimm.core.tool_labels import tool_label

from .helpers import ProcessChanges, process
from .tool_labels_helpers import CASES, JAVA


@pytest.mark.parametrize("key", CASES)
def test_tool_label_recognizes_real_command_line(key: str) -> None:
    changes, label, reason = CASES[key]

    assert tool_label(proc=process(**changes)) == (label, reason)


JAVA_ANY: ProcessChanges = {
    "name": "java",
    "exe": JAVA,
    "cmdline": (JAVA, "-Xmx2g", "-jar", "/opt/app/billing-service.jar", "--port=8080"),
}


@pytest.mark.parametrize(
    "changes",
    [
        JAVA_ANY,
        {"name": "node", "exe": "/usr/bin/node", "cmdline": ("/usr/bin/node", "server.js")},
        {
            "name": "python3",
            "exe": "/usr/bin/python3.12",
            "cmdline": ("/usr/bin/python3", "app.py"),
        },
        {"name": "qemu-img", "exe": "/usr/bin/qemu-img", "cmdline": ("/usr/bin/qemu-img", "info")},
        {"name": "kindle", "exe": "/opt/kindle/kindle", "cmdline": ("/opt/kindle/kindle",)},
        {
            "name": "grep",
            "exe": "/usr/bin/grep",
            "cmdline": (
                "/usr/bin/grep",
                "org.gradle.launcher.daemon.bootstrap.GradleDaemon",
                "log.txt",
            ),
        },
        {"name": "worker", "exe": None, "cmdline": None},
        {
            "name": "node",
            "exe": "/usr/bin/node",
            "cmdline": ("/usr/bin/node", "/home/u/work/gopls/build.js"),
        },
        {
            "name": "python3",
            "exe": "/usr/bin/python3.12",
            "cmdline": ("/usr/bin/python3", "/home/u/src/clangd/tools/gen.py"),
        },
        {
            "name": "emulator",
            "exe": "/opt/game/emulator",
            "cmdline": ("/opt/game/emulator", "rom.nes"),
        },
    ],
    ids=[
        "java-any",
        "node-script",
        "python-script",
        "qemu-img",
        "kindle",
        "grep-gradle",
        "bare",
        "script-in-a-gopls-folder",
        "script-in-a-clangd-folder",
        "other-emulator",
    ],
)
def test_tool_label_unrelated_process_has_no_label(changes: ProcessChanges) -> None:
    assert tool_label(proc=process(**changes)) is None
