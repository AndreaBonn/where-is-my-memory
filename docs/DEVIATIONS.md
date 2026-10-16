# Scostamenti e verifiche

Premesse [DA VERIFICARE] della specifica chiuse durante lo sviluppo e scelte che se ne
discostano, ciascuna con l'evidenza osservata.

## Type stubs (T-0.1a): premessa smentita, ripiego applicato

La premessa di §14.1 era che `pygobject-stubs`, `types-psutil` e `types-docker` si
installassero accanto ai moduli apt. Due punti non reggono:

- `pygobject-stubs` 2.18.0 dichiara la dipendenza `pygobject`. `uv sync` prova a compilarlo da
  PyPI e fallisce (`Dependency 'girepository-2.0' is required but not found`). Se riuscisse,
  metterebbe nel venv un PyGObject diverso da `python3-gi` 3.48.2 e i test non girerebbero
  più sul runtime del pacchetto.
- `types-docker` esiste solo dalla 7.0.0, mentre il runtime è docker 5.0.3. L'API tipizzata
  descriverebbe metodi e parametri che la 5.0.3 non ha (per esempio `stats(one_shot=...)`).

Ripiego in `pyproject.toml`:

- `[tool.uv] override-dependencies = ["pygobject; sys_platform == 'never'"]` elimina la
  dipendenza runtime degli stub. `gi` resta quello di `/usr/lib/python3/dist-packages`
  (verificato con `uv run python -c "import gi; print(gi.__file__)"`).
- `no-binary-package` e `config-settings-package` costruiscono gli stub con
  `config = "Gtk4,Gdk4,Soup3"`. Verificato: `gi-stubs/repository/Gtk.pyi` contiene
  `from ._Gtk4 import *`, e `mypy --strict` su una sonda risolve `Gtk.Box` e
  `Adw.AlertDialog` ai tipi GTK4 e Adw 1.
- `types-psutil==5.9.5.20240516`, l'ultima serie 5.9. Limite osservato: con questi stub i
  campi di `memory_full_info()` (`pfullmem`) risultano `Any`. I collector convertono quindi
  in `int` in modo esplicito al confine e i dataclass di `model.py` restano tipizzati.
- Nessuno stub per docker: override mypy `ignore_missing_imports` su `docker.*`. Il SDK si
  usa solo dietro `Protocol` tipizzati (`DockerControl`, sorgente dei container), quindi il
  resto del codice non vede `Any`.

Esito: `make setup`, `make lint` (ruff, ruff format, mypy) e `make test` (19 passed) verdi
il 2026-10-16. BASIS: measured.

## CI (T-0.3)

- Action pinnate a SHA: `actions/checkout` v6.1.0 =
  `d23441a48e516b6c34aea4fa41551a30e30af803`, `astral-sh/setup-uv` v8.3.2 =
  `11f9893b081a58869d3b5fccaea48c9e9e46f990`. SHA riverificati con `git ls-remote`.
- Noble pubblica python3-psutil 5.9.8 e python3-docker 5.0.3, gli stessi pin di
  `tests/test_runtime_versions.py`. La CI quindi non imposta `WIMM_SKIP_RUNTIME_PIN`.
  BASIS: inferred da packages.ubuntu.com; la CI remota non è ancora stata eseguita.
- La CI esegue `make test`, non `make test-all`: i test UI, D-Bus e di integrazione hanno
  bisogno di una sessione grafica e di Docker (decisione D-U3 di `plan.md`).

## `stop_group` / `group_stop` (T-0.2a)

§6.5 (esempio JSON, `primary_action.kind`) e l'esempio di chiamata in §8.1 scrivono
`stop_group`. L'enum `ActionKind` di §8.1 e il paragrafo "Semantica di `group_stop`" usano
invece `group_stop`. Vale `group_stop`, perché l'enum è la definizione e gli esempi sono
illustrativi. Il decoder rifiuta `stop_group`. BASIS: measured.
