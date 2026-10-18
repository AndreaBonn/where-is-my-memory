SAMPLE_INTERVAL_S = 60
ACTIVITY_WINDOW_S = 1800
CPU_ACTIVE_THRESHOLD_PCT = 1.0
NET_ACTIVE_THRESHOLD_BPS = 700
NOTIFY_AFTER_S = 7200
NOTIFY_MIN_BYTES = 209715200
NOTIFY_CATEGORIES = ("PROJECT", "CONTAINER", "DEV_SERVER", "DEV_PROCESS")
PRESSURE_WARNING_PCT = 15
PRESSURE_CRITICAL_PCT = 10
MAX_NOTIFICATIONS_PER_HOUR = 3
NOTIFY_WINDOW_S = 3600
PRESSURE_COOLDOWN_S = 3600
PRESSURE_TOP_GROUPS = 3
TERMINATE_TIMEOUT_S = 5
CONTAINER_STOP_TIMEOUT_S = 10
CONTAINER_STOP_WORKERS = 8
COMPOSE_TIMEOUT_S = 120
# SPECIFICHE 8.4: `POST /build/prune` with `all` can take minutes on a large cache; the
# client default (60 s) would report a failure while the daemon is still freeing space.
BUILD_PRUNE_TIMEOUT_S = 600
# Filesystems the root detection never probes (also any "fuse" or "fuse.*"): a stale mount blocks.
NETWORK_FSTYPES = frozenset(
    ("nfs", "nfs4", "cifs", "smb3", "smbfs", "afs", "ceph", "glusterfs", "9p", "autofs")
)
DEVDIRS_MIN_AGE_DAYS = 90
DEVDIRS_MAX_DEPTH = 6
DISK_SCAN_INTERVAL_S = 21600
# SPECIFICHE 7.6: the first disk scan waits, so startup is not slowed by directory walks.
DISK_SCAN_START_DELAY_S = 120
EXTRA_PROTECTED_NAMES: tuple[str, ...] = ()
FOREGROUND_TRACKING = True

PROTECTED_PROCESS_NAMES = (
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
DOCUMENT_APP_NAMES = (
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
DOCUMENT_DESKTOP_CATEGORIES = (
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
SHELL_NAMES = ("bash", "zsh", "fish", "sh", "dash")
AI_CLI_NAMES = ("claude", "codex", "gemini", "agy", "aider")
BROWSER_UNIT_NAMES = ("firefox", "google-chrome", "chromium", "brave-browser", "brave")
BROWSER_SCOPE_PATTERNS = tuple(
    pattern
    for name in BROWSER_UNIT_NAMES
    for pattern in (f"snap.{name}.*", f"app-gnome-{name}-*", f"app-flatpak-*{name}*")
)
PROJECT_ROOT_MARKERS = (
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
DB_PROCESS_NAMES = ("postgres", "mysqld", "mariadbd", "mongod", "redis-server")

CGROUP_RECORD_PREFIX = "0::"
DOCKER_SCOPE_PATTERNS = ("docker-*.scope",)
PODMAN_SCOPE_PATTERNS = ("libpod-*.scope", "libpod-conmon-*.scope")
PODMAN_SCOPE_TEMPLATE = "libpod-{container_id}.scope"
PODMAN_SCOPE_PREFIX = "libpod-"
PODMAN_CONMON_PREFIX = "conmon-"
VTE_SCOPE_PATTERNS = ("vte-spawn-*.scope",)
APP_SLICE = "app.slice"
SESSION_SLICE = "session.slice"
USER_UNIT_TEMPLATE = "user@{uid}.service"
SERVICE_SUFFIX = ".service"
SCOPE_SUFFIX = ".scope"
GNOME_SCOPE_PREFIX = "app-gnome-"
FLATPAK_SCOPE_PREFIX = "app-flatpak-"
SNAP_SCOPE_PREFIX = "snap."
SYSTEMD_USER_FLAG = "--user"
DBUS_NAME_PREFIX = "dbus-"
SYSTEMD_NAME = "systemd"
OLLAMA_NAME = "ollama"
OLLAMA_RUN_COMMAND = "run"
OPTION_PREFIX = "-"
CLI_WRAPPER_NAMES = ("node", "nodejs", "python", "python3", "bash", "sh", "bun", "deno")

REASON_SELF = "self"
REASON_EXCLUDED = "excluded"
REASON_SYSTEM = "system"
REASON_SESSION = "session"
REASON_PROTECTED_NAME = "protected_name"
REASON_SCOPE = "scope"
REASON_ANCESTOR = "ancestor"
REASON_AI_CLI = "ai_cli"
REASON_LISTEN = "listen"
REASON_TERMINAL_PROCESS = "terminal_process"
REASON_OTHER = "other"
REASON_USER_SERVICE = "user_service"
REASON_DOCUMENT_APP_FROM_TERMINAL = "document_app_from_terminal"
REASON_PODMAN_UNSEEN = "podman_unseen"

BROWSER_NAMES = (
    "chrome",
    "firefox",
    "chromium",
    "chromium-browser",
    "brave",
    "brave-browser",
    "google-chrome",
)
TERMINAL_NAMES = (
    "gnome-terminal-server",
    "xterm",
    "konsole",
    "alacritty",
    "kitty",
    "tilix",
    "xfce4-terminal",
    "kgx",
    "wezterm",
    "foot",
)
TERMINAL_APPIDS = ("org.gnome.Terminal", "org.gnome.Console", *TERMINAL_NAMES)
SESSION_SERVICE_PATTERNS = (
    "gsd-*",
    "evolution-*",
    "tracker-*",
    "gvfs*",
    "xdg-desktop-portal*",
    "at-spi*",
    "ibus*",
    "org.gnome.SettingsDaemon.*",
)

PLAN_TTL_S = 120
PLAN_ID_BYTES = 16

STATE_SAVE_INTERVAL_S = 300
# An unseen persisted entity is forgotten after this long without a sighting.
LAST_ACTIVE_RETENTION_S = 30 * 24 * 3600

# SPECIFICHE 10 (Disk view): sections show their largest entries up to this cap + a counter.
DISK_SECTION_CAP = 200

# SPECIFICHE 7.6.1 (directory size): GIL yield every N entries, I/O pause every M entries.
DIRSIZE_YIELD_EVERY = 1000
DIRSIZE_PAUSE_EVERY = 10000
DIRSIZE_PAUSE_S = 0.01
DISK_CACHE_FILENAME = "disk-cache.json"
DISK_CACHE_VERSION = 1

# SPECIFICHE 7.6 (dependency folders): the project subfolder whose first level counts for
# the age. The searched names live in core.devdir_rules.
DEVDIR_SOURCE_DIRNAME = "src"
SECONDS_PER_DAY = 86400
# SPECIFICHE 8.4 (caches): pip falls back to removing the folder content when the tool is not
# on PATH. Thumbnails and trash have no command.
CACHE_COMMAND_TIMEOUT_S = 300
# SPECIFICHE 8.4 (trash): the folders under the trash whose content is removed.
TRASH_CONTENT_DIRS = ("files", "info")
MOUNTINFO_PATH = "/proc/self/mountinfo"
MAX_RECORDED_REMOVAL_ERRORS = 10
