# ADR-002: Python di sistema e moduli da apt

- Stato: Accettata
- Data: 2026-10-17

## Context

`wimm` è distribuito come pacchetto `.deb` per Ubuntu 24.04 e usa tre librerie con una parte
nativa: PyGObject (Gio, GTK4, libadwaita), `psutil` e il client `docker`. Sulla macchina di
destinazione il runtime misurato è Python 3.12.3, `python3-gi` 3.48.2, `python3-psutil` 5.9.8,
`python3-docker` 5.0.3, GTK 4.14 e libadwaita 1.5 (`assets/SPECIFICHE.md`, Appendice B;
`docs/DEVIATIONS.md`, sezione "Nomi dei pacchetti e Recommends"). Le versioni hanno API diverse
da quelle più recenti: `psutil` 5.9 ha `Process.connections` e non `net_connections`, e
`docker` 5.0.3 non ha `stats(one_shot=...)` (Appendice B).

## Decision

Il runtime usa `/usr/bin/python3` e i moduli forniti da apt, dichiarati come `Depends` in `packaging/debian/control.in`.
`pyproject.toml` ha `dependencies = []`: `psutil`, `docker` e PyGObject non sono dipendenze PyPI
(`assets/SPECIFICHE.md` §14.1, `CLAUDE.md`).

Lo sviluppo gira sulle stesse librerie del pacchetto: `make setup` crea il venv con
`--system-site-packages` e `--python /usr/bin/python3` (§14.1), e un test verifica che nel venv
`psutil.__version__` e `docker.__version__` siano quelli di sistema
(`tests/test_runtime_versions.py`, T-0.1 di §16). La CI installa gli stessi pacchetti Noble e non
imposta `WIMM_SKIP_RUNTIME_PIN` (`docs/DEVIATIONS.md`, sezione "CI").

Gli stub di tipo sono la parte che non si è potuta tenere tutta fuori da PyPI. `pygobject-stubs`
dichiara `pygobject` come dipendenza e `uv sync` proverebbe a compilarlo, mettendo nel venv un
PyGObject diverso da `python3-gi`; `types-docker` esiste solo dalla 7.0.0. Il ripiego è in
`pyproject.toml`: override che elimina la dipendenza runtime degli stub, build degli stub con
`config = "Gtk4,Gdk4,Soup3"`, `types-psutil` serie 5.9 e `ignore_missing_imports` su `docker.*`
(`docs/DEVIATIONS.md`, sezione "Type stubs").

## Consequences

- I test girano sulle librerie che l'utente avrà installate, non su versioni più nuove.
- Il pacchetto è `all` e non porta con sé un ambiente virtuale: l'aggiornamento delle librerie
  passa da apt.
- Il codice può usare solo le API di `psutil` 5.9 e `docker` 5.0.3. Una chiamata non pubblica
  dell'SDK (`APIClient._url/_post/_result`, usata per la build cache) va ricontrollata a ogni
  aggiornamento di `python3-docker` (`docs/DEVIATIONS.md`).
- Il progetto è legato a Ubuntu 24.04 e alle sue versioni, che le asserzioni dei test fissano.
- Il tipo `Any` compare dove gli stub 5.9 di `psutil` non descrivono `memory_full_info()`; i
  collector convertono in `int` al confine.

## Alternatives considered

- **Dipendenze PyPI nel venv.** Scartata in §14.1: `uv` installerebbe versioni più nuove di quelle
  apt e i test girerebbero su librerie diverse da quelle del `.deb`. Per PyGObject la
  compilazione da PyPI fallisce sulla macchina (`girepository-2.0` mancante,
  `docs/DEVIATIONS.md`).
- **Stub di tipo completi da PyPI senza override.** Pesata e scartata in `docs/DEVIATIONS.md`, per
  i due motivi sopra.
- **Pacchetto con un ambiente virtuale incluso.** Alternativa dedotta, non presente nella
  specifica o nel piano: `build_deb.sh` copia i sorgenti (§12.3, §14.1) e non descrive questa via.
