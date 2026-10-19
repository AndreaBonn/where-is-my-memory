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

## Correzione del 2026-10-19

Il run del 2026-10-18 era incompleto. `uvx` sceglieva Python 3.11, che non legge la
sintassi 3.12 del progetto: bandit saltava 16 file di `src` ("syntax error while parsing
AST") e lo segnalava solo nel riepilogo, che `-q` nasconde. Il "nessun finding" valeva
quindi per una parte del codice. Ora `make audit` fissa l'interprete (`AUDIT_PYTHON := 3.12`).

Rieseguito su tutti i file (0 saltati): un finding, B108 (Medium, confidenza Medium) su
`src/wimm/core/constants.py`, la voce `"/tmp"` di `SYSTEM_PATH_PREFIXES`. È un falso
positivo: la tupla elenca i prefissi che una radice di sviluppo non può avere (ADR-007),
e l'app non apre mai un file in `/tmp` da lì. Il finding è soppresso solo su quella riga
(`# nosec B108`, con il motivo nel commento), così B108 resta attivo nel resto del codice.
pip-audit: "No known vulnerabilities found". `make audit` esce 0. BASIS: measured.
