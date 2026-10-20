SAMPLE_INTERVAL_S = 60
ACTIVITY_WINDOW_S = 1800
CPU_ACTIVE_THRESHOLD_PCT = 1.0
NET_ACTIVE_THRESHOLD_BPS = 700
NOTIFY_AFTER_S = 7200
NOTIFY_MIN_BYTES = 209715200
NOTIFY_CATEGORIES = ("PROJECT", "CONTAINER", "DEV_SERVER", "DEV_PROCESS")
PRESSURE_WARNING_PCT = 15
PRESSURE_CRITICAL_PCT = 10
# /proc/pressure/memory, 60 s average: `some` stall at or above warns, `full` stall is critical.
PSI_SOME_WARNING_AVG60 = 10.0
PSI_FULL_CRITICAL_AVG60 = 5.0
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
# fuseblk serves local NTFS and exFAT disks through FUSE: owner and mode come from the daemon.
FUSE_FSTYPES = frozenset(("fuse", "fuseblk"))
# ADR-007: a development root never sits at or below these (the root "/" is too shallow anyway).
SYSTEM_PATH_PREFIXES = (
    "/usr",
    "/etc",
    "/var",
    "/boot",
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/opt",
    "/snap",
    "/root",
    "/srv",
    # A refused prefix, never a temp file the app opens: bandit B108 misreads the literal.
    "/tmp",  # nosec B108
    # Merged-/usr links and the fsck folder: paths of the system, whatever their owner says.
    "/bin",
    "/sbin",
    "/lib",
    "/lib32",
    "/lib64",
    "/libx32",
    "/lost+found",
)
# ADR-007: a root needs more than two path components, so "/mnt/data" is refused.
ROOT_MIN_COMPONENTS = 3
DEVDIRS_MIN_AGE_DAYS = 90
DEVDIRS_MAX_DEPTH = 6
DISK_SCAN_INTERVAL_S = 21600
# SPECIFICHE 7.6: the first disk scan waits, so startup is not slowed by directory walks.
DISK_SCAN_START_DELAY_S = 120
EXTRA_PROTECTED_NAMES: tuple[str, ...] = ()
FOREGROUND_TRACKING = True
REMOTE_SESSIONS_ACTIONABLE = False

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
    "mosh-server*",
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
SHELL_NAMES = ("bash", "zsh", "fish", "sh", "dash", "ksh", "tcsh", "csh", "nu")
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
LOGIN_SESSION_SCOPE_PATTERNS = ("session-*.scope",)
SSHD_NAME_PATTERNS = ("sshd", "sshd-*", "sshd:*")
MOSH_SERVER_PATTERNS = ("mosh-server*",)
LOGIN_INFRASTRUCTURE_NAMES = ("tmux*", "screen", "SCREEN")
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
REASON_REMOTE_LOGIN = "remote_login"
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
# Design note L5 (T-6.37c): `ollama list` in the scan answers in about 0.2 s; the system
# store entry has no file behind it, so its path field only names the command.
OLLAMA_LIST_TIMEOUT_S = 10
OLLAMA_LIST_COMMAND = "list"
OLLAMA_SYSTEM_PATH = "ollama list"
OLLAMA_COMMAND_ENV_KEYS = ("PATH", "LANG", "HOME", "OLLAMA_HOST")
# SPECIFICHE 8.4 (trash): the folders under the trash whose content is removed.
TRASH_CONTENT_DIRS = ("files", "info")
MOUNTINFO_PATH = "/proc/self/mountinfo"
MAX_RECORDED_REMOVAL_ERRORS = 10

# SPECIFICHE R29 (growth indicator): one point per group every 10 minutes for 3 hours.
GROWTH_SAMPLE_INTERVAL_S = 600
GROWTH_WINDOW_S = 3 * 3600
# "Growing" means the group gained at least this much and at least this fraction of where it
# started, over a span and a number of points long enough not to be a spike.
GROWTH_MIN_BYTES = 256 * 1024 * 1024
GROWTH_MIN_RATIO = 0.2
GROWTH_MIN_SPAN_S = 3600
# Points needed to cover the span: 7 at 600 s (6 would cover only 3000 s).
GROWTH_MIN_POINTS = GROWTH_MIN_SPAN_S // GROWTH_SAMPLE_INTERVAL_S + 1
# Falls summing to more than this fraction of the net gain mean a sawtooth, not a leak.
GROWTH_MAX_DROP_FRACTION = 0.25
# A fall between two samples smaller than this is jitter, not a cache emptying: 32 MiB is
# above the swing (about 20 MiB) of a +-10 MiB wobble and an eighth of GROWTH_MIN_BYTES.
GROWTH_NOISE_BYTES = 32 * 1024 * 1024
# Medians of the first and last third of the series stand for its start and end.
GROWTH_EDGE_PARTS = 3

# The UI shows at most this many items of one cache and folds the rest into "e altre N";
# the core returns every item.
CACHE_ITEMS_CAP = 50
