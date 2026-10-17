# where-is-my-memory

## Fonte di verità

Prevale `assets/SPECIFICHE.md`, anche rispetto ai piani in `specs/`.
Usare gli ID `T-x.y` della specifica per riferimenti e attività.

## Comandi

- `make setup`: crea il venv con Python e pacchetti di sistema, sincronizza con uv.
- `make test`: esegue i test senza integrazione, UI e D-Bus; copertura core ≥90% quando presente.
- `make test-all`: esegue tutti i test su bus e display privati.
- `make lint`: controlla Ruff, formato, tipi con mypy e traduzioni con `scripts/check_i18n.py`.
- `make po`: aggiorna `po/en.po` con le stringhe nuove; `make mo` compila il catalogo.
- `make run`: avvia `scripts/dev_run.sh`, previsto in una fase successiva.
- `make deb`: esegue `scripts/build_deb.sh`, previsto in una fase successiva.

## Architettura prevista

Un solo processo GTK4. `core` contiene funzioni pure, senza psutil, Docker o gi.
I `collectors` leggono il sistema senza importare gi.
Il `service` conserva lo stato ed è l'unico esecutore delle azioni confermate.
La `ui` mostra i dati; la `tray` espone icona e menu via Gio/D-Bus.

## Convenzioni

Codice, commenti, log e commit in inglese. Stringhe UI con msgid italiano dentro `_()`;
le costanti di modulo con `N_()` e `_()` dove si mostrano, mai `_()` all'import.
Ogni stringa nuova va tradotta in `po/en.po` (`make po`), termini inglesi invariati.
Massimo 300 righe per file, 30 per funzione, 4 parametri.
Keyword argument espliciti, type hint completi, costanti nominate.
Test-first sul core. Nessuna azione distruttiva reale nei test (§0.5).
Usare fake o bersagli creati dal test; HOME e directory XDG sono isolate.
Commit atomici Conventional Commits su main; mai push automatico.
psutil, Docker e PyGObject arrivano da apt, non dalle dipendenze PyPI.
Pillow (`python3-pil`, solo sviluppo) serve a `scripts/build_icons.py` e ai suoi test.
Le icone in `data/icons` derivano da `assets/logo/wimm-logo.png`: mai modificarle a mano.

## Stato

Lotto L0-1: ambiente, controlli, CI e stub CLI Q-7.
La GUI sarà introdotta in T-1.8c.
