**English** | [Italiano](SECURITY.it.md)

# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 1.1.x | Yes |
| < 1.1 | No, update to the latest release |

## Reporting a Vulnerability

Report vulnerabilities privately through
[GitHub Security Advisories](https://github.com/AndreaBonn/where-is-my-memory/security/advisories/new),
not through public issues.

Please include:

- a description of the vulnerability and the affected version
- steps to reproduce
- expected and actual behavior
- the impact: what an attacker or a malicious local file could achieve

<!-- TODO: add the response times you commit to, if any -->
The fix is released first; the advisory is made public after the release.

## Security Measures Implemented

The app runs as your user and acts only on your own processes, containers and files. The
measures below are in the code:

- **No privilege escalation**: no `sudo`, `pkexec` or `setcap` anywhere in the sources,
  packaging or data files. Every external command is an argument list without a shell and
  with a timeout (`src/wimm/service/fs_controls.py:75`, `src/wimm/service/compose.py:129`,
  `src/wimm/collectors/foreground.py:112`).
- **Confirmation enforced in the service**: a Danger action runs only when the typed phrase
  matches exactly; the check is in the service, not only in the dialog
  (`src/wimm/service/plan_registry.py:31`).
- **Processes stopped, not killed**: the executor sends `SIGTERM` to the process tree, never
  an automatic `SIGKILL` (`src/wimm/service/executor_process.py:23`).
- **Safe deletion on disk**: removal walks through open directory descriptors with
  `O_NOFOLLOW`, so a path swapped for a link while the app works is not followed
  (`src/wimm/service/safe_tree.py:23`). Before removing, the target directory is checked
  again by inode, device and real path (`src/wimm/service/executor_disk_fs.py:65`).
- **Docker data kept**: removing a container never removes its volumes
  (`src/wimm/service/executor_docker.py:55`).
- **Read-only D-Bus inspector**: the D-Bus interface exposes data and has no writable
  property (`src/wimm/service/inspector_dbus.py:46`); command lines are redacted before they
  are exported (`src/wimm/snapshot_redaction.py:14`).
- **Private files**: configuration, state and log are written with mode `0600` in
  directories with mode `0700`, through exclusive creation with `O_NOFOLLOW` and an atomic
  rename (`src/wimm/paths.py:7`, `src/wimm/paths.py:62`, `src/wimm/paths.py:79`).
- **Checks in CI**: bandit on the sources and pip-audit on the locked development
  dependencies run on every push (`Makefile`, target `audit`; `.github/workflows/ci.yml`).

Notes from the internal review, with the open hardening items below the exploitability bar,
are in [docs/security/T-6.1-security-baseline.md](docs/security/T-6.1-security-baseline.md).

## Out of Scope

- Attacks that need code already running as your user: such code can read `/proc` and act on
  your processes without this app.
- Vulnerabilities in GTK, libadwaita, psutil, the Docker SDK or other system libraries:
  report them to their maintainers or to Ubuntu.
- Data loss after you confirmed an action whose dialog described that loss.

---

[Back to README](README.md)
