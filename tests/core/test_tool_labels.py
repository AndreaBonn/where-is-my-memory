import pytest

from wimm.core.tool_labels import ToolLabel, ToolReason, tool_label

from .helpers import ProcessChanges, process

JAVA = "/usr/lib/jvm/java-17-openjdk-amd64/bin/java"
SDK = "/home/ada/Android/Sdk"


def _java_daemon(*, main_class: str, name: str = "java") -> ProcessChanges:
    return {
        "name": name,
        "exe": JAVA,
        "cmdline": (
            JAVA,
            "--add-opens=java.base/java.util=ALL-UNNAMED",
            "-Xmx512m",
            "-Dfile.encoding=UTF-8",
            "-cp",
            "/home/ada/.gradle/wrapper/dists/gradle-8.5-bin/lib/gradle-launcher-8.5.jar",
            main_class,
            "8.5",
        ),
    }


GRADLE = _java_daemon(main_class="org.gradle.launcher.daemon.bootstrap.GradleDaemon")
KOTLIN = _java_daemon(main_class="org.jetbrains.kotlin.daemon.KotlinCompileDaemon")
JDTLS: ProcessChanges = {
    "name": "java",
    "exe": JAVA,
    "cmdline": (
        JAVA,
        "-Declipse.application=org.eclipse.jdt.ls.core.id1",
        "-Dosgi.bundles.defaultStartLevel=4",
        "-Declipse.product=org.eclipse.jdt.ls.core.product",
        "-jar",
        "/opt/jdtls/plugins/org.eclipse.equinox.launcher_1.6.600.jar",
        "-data",
        "/home/ada/.cache/jdtls-workspace",
    ),
}

CASES: dict[str, tuple[ProcessChanges, ToolLabel, ToolReason]] = {
    "qemu": (
        {
            "name": "qemu-system-x86",
            "exe": "/usr/bin/qemu-system-x86_64",
            "cmdline": (
                "/usr/bin/qemu-system-x86_64",
                "-name",
                "guest=debian12,debug-threads=on",
                "-machine",
                "pc-q35-8.2,accel=kvm",
                "-m",
                "4096",
                "-smp",
                "4",
            ),
        },
        ToolLabel.VIRTUAL_MACHINE,
        ToolReason.GUEST_MEMORY,
    ),
    "virtualbox-headless": (
        {
            "name": "VBoxHeadless",
            "exe": "/usr/lib/virtualbox/VBoxHeadless",
            "cmdline": (
                "/usr/lib/virtualbox/VBoxHeadless",
                "--comment",
                "ubuntu-server",
                "--startvm",
                "5f1d6a8e-2f6d-4b0e-9a3c-0c1b7d1f2a44",
            ),
        },
        ToolLabel.VIRTUAL_MACHINE,
        ToolReason.GUEST_MEMORY,
    ),
    "virtualbox-gui": (
        {
            "name": "VirtualBoxVM",
            "exe": "/usr/lib/virtualbox/VirtualBoxVM",
            "cmdline": (
                "/usr/lib/virtualbox/VirtualBoxVM",
                "--comment",
                "win11",
                "--startvm",
                "0a7c3e55-5d1e-4e3b-8a2f-7b9e6f2d1c08",
            ),
        },
        ToolLabel.VIRTUAL_MACHINE,
        ToolReason.GUEST_MEMORY,
    ),
    "android-emulator-qemu": (
        {
            "name": "qemu-system-x86",
            "exe": f"{SDK}/emulator/qemu/linux-x86_64/qemu-system-x86_64",
            "cmdline": (
                f"{SDK}/emulator/qemu/linux-x86_64/qemu-system-x86_64",
                "-avd",
                "Pixel_6_API_34",
                "-netdelay",
                "none",
                "-netspeed",
                "full",
            ),
        },
        ToolLabel.ANDROID_EMULATOR,
        ToolReason.GUEST_MEMORY,
    ),
    "android-emulator-launcher": (
        {
            "name": "emulator",
            "exe": f"{SDK}/emulator/emulator",
            "cmdline": (f"{SDK}/emulator/emulator", "-avd", "Pixel_6_API_34"),
        },
        ToolLabel.ANDROID_EMULATOR,
        ToolReason.GUEST_MEMORY,
    ),
    "gradle-daemon": (GRADLE, ToolLabel.GRADLE_DAEMON, ToolReason.BACKGROUND_BUILD_DAEMON),
    "kotlin-daemon": (KOTLIN, ToolLabel.KOTLIN_DAEMON, ToolReason.BACKGROUND_BUILD_DAEMON),
    "rust-analyzer": (
        {
            "name": "rust-analyzer",
            "exe": "/home/ada/.rustup/toolchains/stable/bin/rust-analyzer",
            "cmdline": ("/home/ada/.rustup/toolchains/stable/bin/rust-analyzer",),
        },
        ToolLabel.LANGUAGE_SERVER,
        ToolReason.EDITOR_BACKGROUND_SERVICE,
    ),
    "gopls": (
        {
            "name": "gopls",
            "exe": "/home/ada/go/bin/gopls",
            "cmdline": ("/home/ada/go/bin/gopls", "-mode=stdio"),
        },
        ToolLabel.LANGUAGE_SERVER,
        ToolReason.EDITOR_BACKGROUND_SERVICE,
    ),
    "pyright-node": (
        {
            "name": "node",
            "exe": "/usr/bin/node",
            "cmdline": (
                "/usr/bin/node",
                "/home/ada/.nvm/versions/node/v20.11.0/bin/pyright-langserver",
                "--stdio",
            ),
        },
        ToolLabel.LANGUAGE_SERVER,
        ToolReason.EDITOR_BACKGROUND_SERVICE,
    ),
    "pylsp": (
        {
            "name": "python3",
            "exe": "/usr/bin/python3.12",
            "cmdline": ("/usr/bin/python3", "/home/ada/.local/bin/pylsp", "-v"),
        },
        ToolLabel.LANGUAGE_SERVER,
        ToolReason.EDITOR_BACKGROUND_SERVICE,
    ),
    "typescript-language-server": (
        {
            "name": "node",
            "exe": "/usr/bin/node",
            "cmdline": (
                "/usr/bin/node",
                "/usr/lib/node_modules/typescript-language-server/lib/cli.mjs",
                "--stdio",
            ),
        },
        ToolLabel.LANGUAGE_SERVER,
        ToolReason.EDITOR_BACKGROUND_SERVICE,
    ),
    "jdtls": (JDTLS, ToolLabel.LANGUAGE_SERVER, ToolReason.EDITOR_BACKGROUND_SERVICE),
    "clangd": (
        {
            "name": "clangd",
            "exe": "/usr/bin/clangd-18",
            "cmdline": ("/usr/bin/clangd-18", "--background-index", "--clang-tidy"),
        },
        ToolLabel.LANGUAGE_SERVER,
        ToolReason.EDITOR_BACKGROUND_SERVICE,
    ),
    "kind-cli": (
        {
            "name": "kind",
            "exe": "/usr/local/bin/kind",
            "cmdline": ("/usr/local/bin/kind", "create", "cluster", "--name", "dev"),
        },
        ToolLabel.KIND_CLUSTER,
        ToolReason.LOCAL_CLUSTER,
    ),
    "minikube-cli": (
        {
            "name": "minikube",
            "exe": "/usr/local/bin/minikube",
            "cmdline": ("/usr/local/bin/minikube", "tunnel"),
        },
        ToolLabel.MINIKUBE_CLUSTER,
        ToolReason.LOCAL_CLUSTER,
    ),
    "minikube-kvm2-driver": (
        {
            "name": "qemu-system-x86",
            "exe": "/usr/bin/qemu-system-x86_64",
            "cmdline": (
                "/usr/bin/qemu-system-x86_64",
                "-name",
                "guest=minikube,debug-threads=on",
                "-m",
                "6000",
            ),
        },
        ToolLabel.MINIKUBE_CLUSTER,
        ToolReason.LOCAL_CLUSTER,
    ),
    "minikube-virtualbox-driver": (
        {
            "name": "VBoxHeadless",
            "exe": "/usr/lib/virtualbox/VBoxHeadless",
            "cmdline": (
                "/usr/lib/virtualbox/VBoxHeadless",
                "--comment",
                "minikube",
                "--startvm",
                "9c2f77a1-1b64-4d0f-8f0e-3b8d5e6a7c12",
            ),
        },
        ToolLabel.MINIKUBE_CLUSTER,
        ToolReason.LOCAL_CLUSTER,
    ),
}


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
