# T021 Triage di bandit e pip-audit (001-product-gaps, 2026-10-18)

Comando: `make audit` (bandit 1.9.4 su `src`, pip-audit 2.10.1 sulle dipendenze esportate da uv).

## bandit

Primo run: 3 finding, tutti B404 (severità Low, confidenza High, CWE-78), cioè il solo
`import subprocess`:

| Sito | Uso |
|---|---|
| `src/wimm/collectors/foreground.py:5` | `xprop` per la finestra in primo piano |
| `src/wimm/service/compose.py:6` | `docker compose ... down` |
| `src/wimm/service/fs_controls.py:5` | comandi di pulizia delle cache (`uv`, `pip`, `npm`) |

Verdetto: falso positivo per costruzione. B404 non segnala una chiamata ma l'import, e
l'inventario dei tre siti in `T-6.1-security-baseline.md` § 2 mostra per ciascuno lista di
argomenti, nessuna shell, timeout e comando fisso. Nessun finding B602/B603/B607 sulle
chiamate stesse. B404 è escluso in `pyproject.toml` (`[tool.bandit] skips`), non riga per
riga, perché il controllo resta attivo per ogni altro test di bandit. Dopo l'esclusione:
nessun finding, exit 0. BASIS: measured.

## pip-audit

"No known vulnerabilities found". Le dipendenze runtime sono vuote (psutil, docker e
PyGObject arrivano da apt, ADR-002): l'audit copre gli strumenti di sviluppo. I pacchetti
apt seguono gli aggiornamenti di sicurezza di Ubuntu e restano fuori da questo controllo.
`--no-deps --disable-pip` evita che pip provi a compilare PyGObject dagli stub; l'export è
interamente pinnato. BASIS: measured.
