# 002 disco granulare: task

Riferimenti: `plan.md` (fasi L0-L6, domande Q1-Q4), `spec.md` (S1-S20). Gli id T-6.x sono
quelli che T-6.1 aggiunge alla Fase 6 del §16 di `assets/SPECIFICHE.md`. Ogni task dura 10-30
minuti, è test-first (rosso visto prima del verde) e si chiude con `make lint && make test`
verdi oltre al proprio `verify`. I test stanno in `tests/<stesso path>` e fanno parte dello
SCOPE. Commit atomico Conventional Commits su `main` per task, mai push.

Colonne: `par` = `ok` (nessun file o interfaccia in comune con task aperti), `seq` (usa file o
output di un task precedente), `contratto` (dipende da un'interfaccia fissata dal task in `dip`).
Agent: `TG` tdd-guide, `SB` senior-backend (con `[DELEGATE-CODEX]`); `FD` fullstack-developer
in-house (GTK); `DW` doc-writer; `SR` security-reviewer; `CR` code-reviewer; `IH`
orchestratore. Rollback `revert` = basta annullare il commit.

## L0: specifica e baseline

| ID | Task | SCOPE | dip | S | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T-6.1 | SPECIFICHE: RF-29 (spiegazione in riga), RF-22 esteso a `cache_item_remove`, RF-51 (elementi), RF-52 (non attribuito), RF-53 (selezione multipla), §8.3 con il dialogo di RF-53, Fase 6 nel §16 con T-6.2-T-6.40; decisioni O1 e O3 citate | `assets/SPECIFICHE.md` | - | tutte | seq | DW | `grep -c "RF-29\|RF-5[123]\|T-6\." assets/SPECIFICHE.md` >= 45; diff rivisto dall'utente | revert |
| T-6.2 | Baseline: numero di test (`make test`), durata della scansione disco sulla home reale; voce DEVIATIONS "HuggingFace: rimozione per elemento senza il comando del tool" (assunzione del plan) | `docs/PERF.md docs/DEVIATIONS.md` | T-6.1 | S20 | ok | IH | riga baseline in `docs/PERF.md` con comando e condizioni | revert |

## L1: spiegazione in riga (O1)

| ID | Task | SCOPE | dip | S | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T-6.3 | `core/row_consequence.py`: `row_consequence(kind, target, marker)` puro, testo = conseguenze di `assess_risk` unite da `join_consequences` (corretto da R2), o `devdir_consequence` | `src/wimm/core/row_consequence.py` | - | S1 S3 | ok | TG | `tests/core/test_row_consequence.py` parametrico su ogni `CacheKind`, devdir con e senza marker, immagine locale e da registry | revert |
| T-6.4 | Il planner usa `row_consequence` per cache e devdir (stesso testo del dialogo); `planning_disk.py` resta <= 290 righe | `src/wimm/core/planning_disk.py` | T-6.3 | S1 | seq | TG | test esistenti verdi; `test_plan_cache_clean_consequence_matches_row_consequence` | revert |
| T-6.5 | `DiskRowView.consequence`; `make_row` riceve il testo e usa `RISK_TEXT` per il badge | `src/wimm/ui/disk_model.py` | T-6.3 | S2 | contratto | TG | `tests/ui/test_disk_model.py::test_make_row_badge_is_the_short_risk_text` + caso appaiato riga senza azione | revert |
| T-6.6 | Righe di cache, cestino, devdir (`disk_view.py`) e Docker (`disk_view_docker.py`) passano la conseguenza | `src/wimm/ui/disk_view.py src/wimm/ui/disk_view_docker.py` | T-6.5 | S1 S3 | seq | TG | `tests/ui/test_disk_view.py::test_cache_row_subtitle_carries_the_dialog_consequence` e una riga per tipo | revert |
| T-6.7 | Rimozione di `DISK_RISK_CONSEQUENCE` se orfano; `make po`, traduzioni | `src/wimm/ui/format.py po/en.po` | T-6.6 | S2 S19 | seq | IH | `grep -rn DISK_RISK_CONSEQUENCE src` vuoto; `make lint` | revert |
| T-6.8 | GTK: sottotitolo percorso + conseguenza su righe separate, `subtitle_lines=0` (era 4, corretto da R4), nome accessibile con la conseguenza | `src/wimm/ui/pages/disk_rows.py` | T-6.6 | S4 | seq | FD | test `-m ui` sul nome accessibile; render osservato a 360 e 1280 px senza sovrapposizioni; click-through di un bottone per sezione | revert |
| T-6.9 | Chiusura L1: `code-reviewer`, riga `CHECKS:`, REPORT_ATTIVITA | - | T-6.3-T-6.8 | S20 | seq | IH | `make lint && make test` verdi, test > baseline | revert dei commit del lotto |

## L2: elementi delle cache in sola lettura (O3)

| ID | Task | SCOPE | dip | S | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T-6.10 | `model/cache_items.py`: `CacheItem`, `CacheRest`; `CacheEntry.items`/`rest` opzionali; `disk_wire` (`OPTIONAL_FIELDS`), `SCHEMA_VERSION` 5, XML D-Bus | `src/wimm/model/cache_items.py src/wimm/model/disk.py src/wimm/model/enums.py src/wimm/core/disk_wire.py data/dbus/io.github.wimm.Inspector1.xml` | T-6.2 | S18 | contratto | TG | `tests/core/test_disk_wire.py` round-trip con elementi; schema 4 rifiutato; validazione: somma <= size | revert |
| T-6.11 | `core/cache_items.py`: `TreeListing` (nomi, tipi, dimensioni, target dei link), dispatch per tipo, `CACHE_ITEMS_CAP`=50, ordinamento, resto = size meno elementi | `src/wimm/core/cache_items.py src/wimm/core/constants.py` | T-6.10 | S5 S6 S8 | contratto | TG | `tests/core/test_cache_items.py::test_items_and_rest_sum_to_cache_size`; tipo senza regola → nessun elemento | revert |
| T-6.12 | `core/cache_items_hf.py`: repo `models--`/`datasets--`/`spaces--`, file regolari + blob raggiunti solo dai suoi link, condiviso, non attribuito; link fuori dalla cache ignorati | `src/wimm/core/cache_items_hf.py` | T-6.11 | S7 S8 | seq | TG | `tests/core/test_cache_items_hf.py` con fixture che riproduce il layout misurato (magazzino `blobs/3b/...`, un repo standard, un blob condiviso, un blob orfano, un link verso `/tmp`) | revert |
| T-6.13 | `collectors/cache_items.py`: `scandir` senza seguire link, `readlink`, dimensioni via `measure_dir_size`; `collect_caches` allega gli elementi | `src/wimm/collectors/cache_items.py src/wimm/collectors/caches.py` | T-6.11 | S5 | contratto | TG | test su albero in `tmp_path`; nessun `os.path.realpath` su link fuori cache (test) | revert |
| T-6.14 | Rimisura della scansione con lo stesso comando di T-6.2 | `docs/PERF.md` | T-6.13 | S20 | seq | IH | riga risultato, aumento <= 15% o causa e scelta dichiarate | revert |
| T-6.15 | `ui/disk_items.py`: sotto-righe pure (titolo leggibile `org/nome` da `models--org--nome`, "Condiviso fra più modelli", "Non attribuito" con la sua frase, "e altre N") | `src/wimm/ui/disk_items.py src/wimm/ui/disk_texts.py` | T-6.11 T-6.5 | S5 S8 | contratto | TG | `tests/ui/test_disk_items.py` con il report di fixture HF | revert |
| T-6.16 | GTK: riga di cache con elementi come `Adw.ExpanderRow`, sotto-righe senza azione in questa fase; bottone della cache "Pulisci tutta la cache" | `src/wimm/ui/pages/disk_item_rows.py src/wimm/ui/pages/disk_rows.py src/wimm/ui/format.py` | T-6.15 T-6.8 | S5 S9 | seq | FD | test `-m ui`: espansione mostra 5 modelli e "Non attribuito"; render 360/1280; click-through espandi/chiudi | revert |
| T-6.17 | `make po`, traduzioni; DEVIATIONS schema 5 | `po/en.po docs/DEVIATIONS.md` | T-6.16 | S18 S19 | seq | IH | `make lint` | revert |
| T-6.18 | Chiusura L2: `code-reviewer`, `type-design-analyzer` sui tipi nuovi, `CHECKS:` | - | T-6.10-T-6.17 | S20 | seq | IH | suite verde; scansione reale mostra XTTS-v2 con i GB del magazzino | revert dei commit del lotto |

## L3: rimozione del singolo modello HuggingFace

| ID | Task | SCOPE | dip | S | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T-6.19 | `ActionKind.CACHE_ITEM_REMOVE`, `TargetShape.TARGET`, `ItemFingerprint` (cartella + blob esclusivi con ino/dev) | `src/wimm/model/enums.py src/wimm/model/actions.py` | T-6.10 | S10 | contratto | TG | `tests/model/test_actions.py` validazione dell'impronta | revert |
| T-6.20 | `core/planning_cache_item.py` + voci in `risk_table` (rischio per elemento); verifica con context7 di `huggingface_hub` cache API, esito in DEVIATIONS | `src/wimm/core/planning_cache_item.py src/wimm/core/risk_table.py src/wimm/core/planning.py docs/DEVIATIONS.md` | T-6.19 T-6.12 | S10 | seq | TG | `tests/core/test_planning_cache_item.py`: piano con un passo, id sconosciuto → `InvalidRequest` | revert |
| T-6.21 | `service/executor_cache_item.py`: controlli di S12 (cache in tabella, regola pura, niente link, owner, impronta) | `src/wimm/service/executor_cache_item.py src/wimm/service/fs_controls.py` | T-6.20 | S12 | seq | TG | `tests/service/test_executor_cache_item.py::test_*_is_refused` (`../`, fuori tabella, link, owner, ino cambiato), ognuno con il caso che passa; bersaglio intatto | revert |
| T-6.22 | Rimozione HF: esclusività ricalcolata sui link attuali, `remove_directory` sulla cartella, `remove` dei blob esclusivi via `safe_tree`; blob diventato condiviso → resta, esito lo dice | `src/wimm/service/executor_cache_item.py src/wimm/service/safe_tree.py` | T-6.21 | S7 S12 | seq | TG | test in `tmp_path`: blob esclusivo rimosso, blob condiviso dopo il piano intatto, liberato = byte rimossi | revert |
| T-6.23 | Dispatch dell'azione nel servizio, rimisura della cache dopo l'esito | `src/wimm/service/actions.py src/wimm/service/disk_scanner.py` | T-6.22 | S14 | seq | SB | test del servizio con executor finto: esito con liberato, report aggiornato | revert |
| T-6.24 | GTK: "Rimuovi" sulle sotto-righe, testi del dialogo (`dialogs/text.py`), `make po` | `src/wimm/ui/pages/disk_item_rows.py src/wimm/ui/dialogs/text.py src/wimm/ui/window_disk.py po/en.po` | T-6.23 T-6.16 | S10 S14 | seq | FD | click-through su un modello di test in una HOME isolata: dialogo, conferma, esito, riga sparita | revert |
| T-6.25 | Chiusura L3: `security-reviewer` su T-6.21-T-6.22, `code-reviewer`, `CHECKS:` | - | T-6.19-T-6.24 | S20 | seq | IH | suite verde | revert dei commit del lotto |

## L6: selezione multipla (eseguita dopo L3)

| ID | Task | SCOPE | dip | S | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T-6.26 | `ActionKind.DISK_FREE_SELECTED`, `ActionRequest.selected_ids` (solo per questa azione), escludibile | `src/wimm/model/enums.py src/wimm/model/actions.py` | T-6.19 | S16 | contratto | TG | validazione: `selected_ids` vuoto o su altra azione → `ValueError` | revert |
| T-6.27 | `core/planning_disk_selected.py`: un passo per id dai planner singoli, DANGER rifiutato (Q3=A), cache intera e suoi elementi non insieme | `src/wimm/core/planning_disk_selected.py src/wimm/core/planning.py` | T-6.26 | S16 S17 | seq | TG | `tests/core/test_planning_disk_selected.py` con il caso di DoD (elemento CAUTION + build cache) | revert |
| T-6.28 | `ui/disk_selection.py`: stato puro della selezione, esclusione reciproca cache/elementi, totale, azzeramento a ogni nuovo report | `src/wimm/ui/disk_selection.py` | T-6.26 | S16 S17 | ok | TG | `tests/ui/test_disk_selection.py` | revert |
| T-6.29 | GTK: modalità "Seleziona", caselle, "Libera i selezionati (N, X GB)", dialogo raggruppato per rischio; `make po` | `src/wimm/ui/pages/disk.py src/wimm/ui/pages/disk_header.py src/wimm/ui/pages/disk_rows.py src/wimm/ui/dialogs/confirm.py po/en.po` | T-6.27 T-6.28 | S16 | seq | FD | click-through: seleziona 2 voci, togline una nel dialogo, conferma; render 360/1280 | revert |
| T-6.30 | Chiusura L6: `code-reviewer`, `CHECKS:` | - | T-6.26-T-6.29 | S20 | seq | IH | suite verde | revert dei commit del lotto |

## L4: Android SDK, AVD, Playwright, JetBrains

| ID | Task | SCOPE | dip | S | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T-6.31 | `core/cache_items_android.py`: pacchetti SDK da `package.xml` (id `path` con `;`), mai `cmdline-tools`/`licenses`; AVD da `<nome>.ini` + `<nome>.avd` | `src/wimm/core/cache_items_android.py` | T-6.11 | S6 | ok | TG | fixture con `platforms/android-35/package.xml`; `licenses` assente dagli elementi | revert |
| T-6.32 | Executor SDK: `sdkmanager --sdk_root=<cache> --uninstall <id>` (argv verificato con `--help` nel task), solo con il tool, nessun fallback di cancellazione | `src/wimm/service/executor_cache_item.py src/wimm/core/cache_specs.py` | T-6.31 T-6.22 | S11 | seq | TG | `test_item_argv_android_sdk` con runner finto; tool assente → azione non offerta | revert |
| T-6.33 | Executor AVD: `avdmanager delete avd -n <nome>`; rifiuto con emulatore `-avd <nome>` in esecuzione | `src/wimm/service/executor_cache_item.py` | T-6.31 T-6.22 | S11 S13 | seq | TG | test con processo finto in esecuzione → rifiuto; caso appaiato senza | revert |
| T-6.34 | `core/cache_items_misc.py`: Playwright (`<browser>-<rev>`) e JetBrains (prodotto+versione); rimozione via `safe_tree` | `src/wimm/core/cache_items_misc.py src/wimm/service/executor_cache_item.py` | T-6.22 | S6 S11 | seq | TG | fixture con 2 revisioni di chromium; nome non riconosciuto → non elemento | revert |
| T-6.35 | Testi, `make po`, `security-reviewer`, `code-reviewer`, `CHECKS:` | `po/en.po src/wimm/core/risk_table.py` | T-6.31-T-6.34 | S19 S20 | seq | IH | suite verde | revert dei commit del lotto |

## L5: ollama per modello (dopo la risposta a Q2)

| ID | Task | SCOPE | dip | S | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T-6.36 | Elementi ollama dalla home: manifest `manifests/<host>/<ns>/<nome>/<tag>`, dimensione dai layer, layer condivisi in "Condiviso" | `src/wimm/core/cache_items_ollama.py` | T-6.11 | S6 S7 | ok | TG | fixture con due modelli che condividono un layer | revert |
| T-6.37 | (Q2=A) collector `ollama list` con timeout per l'installazione di sistema: voce di sola rimozione, nessun accesso ai file | `src/wimm/collectors/ollama_models.py` | T-6.36 | S6 | seq | TG | parser su output reale registrato come fixture; tool assente → nessuna voce | revert |
| T-6.38 | Executor `ollama rm <nome>:<tag>`: richiede il server attivo (inverso di `OllamaServing`), argv in lista | `src/wimm/service/executor_cache_item.py` | T-6.36 T-6.22 | S11 S13 | seq | TG | test: server assente → rifiuto con messaggio; pulizia intera con server attivo resta rifiutata | revert |
| T-6.39 | GTK e testi della conferma DANGER (frase = nome del modello), `make po` | `src/wimm/ui/disk_items.py src/wimm/ui/dialogs/text.py po/en.po` | T-6.38 | S10 S19 | seq | FD | click-through con runner finto | revert |
| T-6.40 | Chiusura L5: `security-reviewer`, `code-reviewer`, `CHECKS:`, REPORT_ATTIVITA | - | T-6.36-T-6.39 | S20 | seq | IH | suite verde | revert dei commit del lotto |
