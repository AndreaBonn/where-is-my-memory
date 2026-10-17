from wimm.core import constants as c


def test_configuration_defaults() -> None:
    assert (
        c.SAMPLE_INTERVAL_S,
        c.ACTIVITY_WINDOW_S,
        c.CPU_ACTIVE_THRESHOLD_PCT,
        c.NET_ACTIVE_THRESHOLD_BPS,
        c.NOTIFY_AFTER_S,
        c.NOTIFY_MIN_BYTES,
    ) == (60, 1800, 1.0, 700, 7200, 209715200)  # 60 s: user decision for RNF-01, DEVIATIONS
    assert c.NOTIFY_CATEGORIES == ("PROJECT", "CONTAINER", "DEV_SERVER", "DEV_PROCESS")
    assert (
        c.PRESSURE_WARNING_PCT,
        c.PRESSURE_CRITICAL_PCT,
        c.MAX_NOTIFICATIONS_PER_HOUR,
        c.TERMINATE_TIMEOUT_S,
    ) == (15, 10, 3, 5)
    assert (c.DEVDIRS_MIN_AGE_DAYS, c.DEVDIRS_MAX_DEPTH, c.DISK_SCAN_INTERVAL_S) == (90, 6, 21600)
    assert c.EXTRA_PROTECTED_NAMES == ()
    assert c.FOREGROUND_TRACKING is True


def test_protected_names_specification() -> None:
    assert c.PROTECTED_PROCESS_NAMES == (
        "gnome-shell",
        "gnome-session-binary",
        "gnome-session-ctl",
        "Xorg",
        "Xwayland",
        "systemd",
        "dbus-daemon",
        "dbus-broker",
        "pipewire",
        "pipewire-pulse",
        "wireplumber",
        "pulseaudio",
        "gsd-*",
        "gvfsd*",
        "gvfs-*",
        "xdg-desktop-portal*",
        "xdg-document-portal",
        "xdg-permission-store",
        "at-spi*",
        "ibus-*",
        "tracker-miner-*",
        "evolution-*",
        "goa-*",
        "gnome-keyring-daemon",
        "ssh-agent",
        "gpg-agent",
        "snapd*",
    )


def test_domain_lists_specification() -> None:
    assert c.DOCUMENT_APP_NAMES == (
        "code",
        "codium",
        "cursor",
        "idea",
        "pycharm",
        "gedit",
        "gnome-text-editor",
        "soffice.bin",
        "slack",
        "discord",
        "telegram-desktop",
        "thunderbird",
        "obsidian",
    )


def test_document_desktop_categories_specification() -> None:
    assert c.DOCUMENT_DESKTOP_CATEGORIES == (
        "TextEditor",
        "IDE",
        "Development",
        "Office",
        "WordProcessor",
        "Spreadsheet",
        "Presentation",
        "Graphics",
        "Email",
        "Chat",
        "InstantMessaging",
    )


def test_execution_and_project_lists_specification() -> None:
    assert c.SHELL_NAMES == ("bash", "zsh", "fish", "sh", "dash")
    assert c.AI_CLI_NAMES == ("claude", "codex", "gemini", "agy", "aider")
    assert c.DB_PROCESS_NAMES == ("postgres", "mysqld", "mariadbd", "mongod", "redis-server")
    assert c.PROJECT_ROOT_MARKERS == (
        ".git",
        "pyproject.toml",
        "package.json",
        "compose.yaml",
        "docker-compose.yml",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
    )
    assert (
        tuple(
            pattern
            for name in ("firefox", "google-chrome", "chromium", "brave-browser", "brave")
            for pattern in (f"snap.{name}.*", f"app-gnome-{name}-*", f"app-flatpak-*{name}*")
        )
        == c.BROWSER_SCOPE_PATTERNS
    )
