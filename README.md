**English** | [Italiano](README.it.md)

<div align="center">

<img src="assets/logo/wimm-logo.png" alt="Where Is My Memory logo" width="128">

# Where Is My Memory

A tray app for Ubuntu that shows what is holding your RAM and disk, grouped by project, and
frees it only after you confirm.

[![CI](https://github.com/AndreaBonn/where-is-my-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/AndreaBonn/where-is-my-memory/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/AndreaBonn/where-is-my-memory/main/badges/test-badge.json)](https://github.com/AndreaBonn/where-is-my-memory/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/AndreaBonn/where-is-my-memory/main/badges/coverage-badge.json)](https://github.com/AndreaBonn/where-is-my-memory/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/AndreaBonn/where-is-my-memory)](https://github.com/AndreaBonn/where-is-my-memory/releases/latest)
[![License: GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)
[![Ubuntu 24.04](https://img.shields.io/badge/ubuntu-24.04-e95420)](docs/user-guide.md#requirements)

</div>

After a few days of work the computer slows down and RAM is almost gone, even though little
seems to be open. The cause is usually something left running: Docker containers of a
project closed days ago, development servers, terminal sessions, heavy programs forgotten in
the background.

Where Is My Memory shows what uses memory and disk, grouped by project and by type, and tells
apart what is in use from what is running but idle. For each group it says how much memory
you would get back and how long it has been idle. It lives in the top bar of the GNOME
desktop and sends a notification when a group stays idle for hours or when memory or disk
are running out. It can stop and clean up what you do not need, but only after a dialog that
lists what happens and how much space comes back.

## In practice

![The Overview tab with demo data](docs/img/overview-en.png)

The pictures use demo data, not a real computer.

## What it does

- Groups processes and containers by project, application and type, with the memory each
  group holds and the memory you would get back.
- Tells in use from idle using CPU, network and, on X11, which window was in front, and shows
  the reason for every verdict.
- Lists what can be freed on disk: package caches, Docker images, containers, volumes and
  build cache, dependency folders of old projects, AI models, Android emulators, Playwright
  browsers, JetBrains products and the trash.
- Rates every action Safe, Caution or Danger. Danger actions ask you to type the name of the
  target before the button works.
- Sends GNOME notifications for long-idle groups and for low memory or disk, at most 3 per
  hour.
- Prints a one-shot report from the terminal with `wimm status`, also over SSH.
- Interface in Italian and English.

It never uses `sudo` while running, never force-closes a program by itself and never deletes
anything without your confirmation.

## Installation

Requirements: Ubuntu 24.04 with GNOME. Docker or Podman only if you want to manage
containers.

1. Download `where-is-my-memory_1.1.0_all.deb` from the
   [latest release](https://github.com/AndreaBonn/where-is-my-memory/releases/latest).

2. Install it from the folder where you saved it:

   ```bash
   sudo apt install ./where-is-my-memory_1.1.0_all.deb
   ```

3. Log out and back in, or start it right away:

   ```bash
   wimm --background
   ```

`apt` installs the required libraries by itself. The full guide, with every view, the
preferences and the answers to common questions, is in
[docs/user-guide.md](docs/user-guide.md).

## Usage

| Command | What it does |
|---|---|
| `wimm` | opens the window |
| `wimm --background` | starts with the tray icon only, as at login |
| `wimm status` | prints memory, memory pressure, the 5 largest groups and free disk, then exits |
| `wimm status --json` | the same in JSON |
| `wimm --version` | prints the version |

The window has two tabs. Overview lists the groups and what you can free without losing
anything; Disk lists what can be freed on disk, in three tiers by risk.

![The Disk tab with demo data](docs/img/disk-en.png)

## Development

Requirements: Ubuntu 24.04, system Python 3.12 or later, [uv](https://docs.astral.sh/uv/),
`make` and these apt packages:

```bash
sudo apt install python3-gi python3-psutil python3-docker python3-pil gettext gir1.2-gtk-4.0 gir1.2-adw-1
```

The virtual environment uses the system Python with `--system-site-packages`, because GTK,
psutil and the Docker SDK come from apt and not from PyPI
([ADR-002](docs/adr/ADR-002-python-di-sistema-e-moduli-apt.md)).

| Command | What it does |
|---|---|
| `make setup` | creates the virtual environment and syncs dependencies with uv |
| `make run` | starts the app in development mode |
| `make test` | runs the tests without integration, UI and D-Bus, with a 90% coverage floor on `core` |
| `make test-all` | runs every test on a private X display and session bus (needs Xvfb) |
| `make lint` | Ruff, formatting, mypy and the translation check |
| `make audit` | bandit on the sources and pip-audit on the development dependencies |
| `make po` / `make mo` | update and compile the English catalog `po/en.po` |
| `make deb` | builds the package in `dist/` |
| `make test-deb` | installs the package in an Ubuntu 24.04 container and checks install and removal |

Everything runs in one GTK 4 process. `core` holds pure functions with no system access;
`collectors` read processes, containers and the disk; `service` keeps the state and is the
only place that runs confirmed actions; `ui` and `tray` show the data.

```text
src/wimm/
  core/        pure rules: grouping, activity, risk, planning, texts
  collectors/  readers for /proc, cgroups, Docker, caches, foreground window
  service/     state, notifications, the executor of confirmed actions, D-Bus
  ui/          the GTK 4 / libadwaita window and dialogs
  tray/        the StatusNotifierItem icon and its menu
tests/         pytest suite, mirrors src/wimm
packaging/     Debian, RPM and Arch packaging, man page
docs/          user guide, ADRs, security notes
```

The reference specification is `assets/SPECIFICHE.md` (Italian); deviations from it are in
`docs/DEVIATIONS.md`. CI (`.github/workflows/ci.yml`) runs lint, tests and the security
audit on every push and updates the test and coverage badges on `main`.

## Security

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## License

Released under the GNU General Public License v3.0 or later. See [LICENSE](LICENSE).

## Author

Andrea Bonacci ([AndreaBonn](https://github.com/AndreaBonn)).

## Support the project

<div align="center">

Where Is My Memory is free to use. If it helps you and you want to give something back, you
can leave a tip via PayPal. The amount is up to you and it is entirely optional.

[![Donate with PayPal](https://img.shields.io/badge/Donate-PayPal-00457C?logo=paypal&logoColor=white&style=for-the-badge)](https://paypal.me/AndreaBonacci19)

</div>

If you found this project useful, consider giving it a
[star on GitHub](https://github.com/AndreaBonn/where-is-my-memory): it helps others find it.
