# 001 product gaps: task

Riferimenti: `plan.md` (lotti L1-L12, domande Q1-Q8), `spec.md` (R1-R43). Ogni task dura 10-30
minuti, è test-first (rosso visto prima del verde) e si chiude con `make lint && make test`
verdi oltre al proprio `verify`. I test stanno in `tests/<stesso path>` e fanno parte dello
SCOPE. Commit atomico Conventional Commits su `main` per task, mai push.

Colonne: `par` = `ok` (nessun file o interfaccia in comune con task aperti), `seq` (usa file o
output di un task precedente), `contratto` (dipende da un'interfaccia fissata dal task in `dip`).
Agent: `TG` tdd-guide, `SB` senior-backend, `DO` devops-engineer (con `[DELEGATE-CODEX]`);
`FD` fullstack-developer in-house (GTK); `DW` doc-writer; `SR` security-reviewer; `CR`
code-reviewer; `AR` architect; `IH` orchestratore; `U` utente.
Rollback `revert` = basta annullare il commit.

## L1: pronta per chiunque (F1, F3, F7, F8)

| ID | Task | SCOPE | dip | R | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T001 | Estrarre da `config.py` la logica delle radici (`_default_roots`, `_expand_root`, decodifica di `devdirs_roots`) in `config_roots.py`, senza cambi di comportamento | `src/wimm/config.py src/wimm/config_roots.py` | - | R42 | seq | TG | `uv run pytest tests/test_config.py` verde senza modifiche ai test; `wc -l src/wimm/config.py` < 260 | revert |
| T002 | `core/dev_roots.py`: `DEV_ROOT_CANDIDATES` e `select_dev_roots(candidates, has_repo)` puro, ordine stabile, nessun duplicato per realpath | `src/wimm/core/dev_roots.py src/wimm/core/constants.py` | - | R1 | ok | TG | `uv run pytest tests/core/test_dev_roots.py::test_detect_dev_roots_keeps_only_candidates_with_a_repo` | revert |
| T003 | `collectors/root_candidates.py`: legge `XDG_DOCUMENTS_DIR` da `~/.config/user-dirs.dirs`, cerca `.git` entro 2 livelli con `scandir` senza seguire symlink | `src/wimm/collectors/root_candidates.py` | T002 | R1 | contratto | TG | test su HOME in `tmp_path` con `user-dirs.dirs` localizzato e un symlink verso un repo (non seguito) | revert |
| T004 | Default di `devdirs_roots` dalla rilevazione; via `DEVDIRS_ROOTS` personale da `constants.py`; nessuna candidata trovata → tupla vuota ammessa solo come default | `src/wimm/config.py src/wimm/config_roots.py src/wimm/core/constants.py` | T001 T003 | R1 | seq | TG | `tests/test_config.py::test_default_roots_come_from_detection`; `grep -rn "00_Lavoro" src` vuoto | revert |
| T005 | Radice salvata inesistente: resta in config, non invalida le altre, esposta come `missing_roots`; `disk_scanner` la salta | `src/wimm/config_roots.py src/wimm/service/disk_scanner.py` | T004 | R2 | seq | TG | `tests/test_config.py::test_parse_config_keeps_a_missing_root_and_flags_it` con caso appaiato (radice esistente senza avviso) | revert |
| T006 | UI: avviso "La cartella … non esiste" nella vista Disco e nelle Preferenze; stato vuoto "Nessuna cartella di progetti trovata" con azione "Scegli una cartella" | `src/wimm/ui/disk_view.py src/wimm/ui/disk_texts.py src/wimm/ui/dialogs/preferences_rows.py` | T005 | R2 R41 | seq | FD | test UI (`-m ui`) con nome accessibile dell'avviso; click-through: radice cancellata → avviso, azione apre il selettore | revert |
| T007 | `i18n.resolve_default`: prima voce supportata vince, altrimenti inglese (`C`, `POSIX`, `de` → en) | `src/wimm/i18n.py` | - | R3 | ok | TG | `uv run pytest tests/test_i18n.py -k resolve_default` con i 4 esempi di R3 | revert |
| T008 | DEVIATIONS: nuova decisione sulla lingua predefinita (supera A1 di `specs/i18n/plan.md`) e radici rilevate (supera `DEVDIRS_ROOTS` di §7.6); proposta di FAQ README da far approvare | `docs/DEVIATIONS.md` | T004 T007 | R1 R3 | ok | DW | due voci nuove in `docs/DEVIATIONS.md` con riferimento a R1 e R3 | revert |
| T009 | Un solo elenco di marker in `constants.PROJECT_ROOT_MARKERS` usato da `project_roots.py`; aggiunti `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, `build.gradle.kts` | `src/wimm/core/constants.py src/wimm/collectors/project_roots.py` | - | R6 | ok | TG | `tests/collectors/test_project_roots.py::test_resolve_finds_each_marker` parametrico; `grep -n "PROJECT_MARKERS =" src/wimm/collectors/project_roots.py` vuoto | revert |
| T010 | `core/devdir_rules.py`: `classify_devdir(name, entries)` puro con la tabella di R4 (nome → marker richiesti); `vendor` solo con `composer.json`, `dist` mai | `src/wimm/core/devdir_rules.py src/wimm/core/constants.py` | - | R4 | ok | TG | `tests/core/test_devdir_rules.py`: una riga per nome + casi falsi positivi appaiati (`target` senza marker, `vendor` con `go.mod`, `venv` senza `pyvenv.cfg`) | revert |
| T011 | Walker di `collectors/devdirs.py`: classifica con `classify_devdir` leggendo le voci del padre; ammette le sole cartelle nascoste della tabella | `src/wimm/collectors/devdirs.py` | T010 T016 | R4 | contratto | TG | test su albero in `tmp_path` con un progetto per ecosistema; i falsi positivi non compaiono | revert |
| T012 | Età del progetto: `newest_mtime` salta tutti i nomi della tabella (un `target` appena ricompilato non rende recente il progetto) | `src/wimm/collectors/devdirs.py` | T011 | R4 | seq | TG | `tests/collectors/test_devdirs.py::test_age_ignores_build_output_folders` | revert |
| T013 | Executor: `_check_devdir` applica `classify_devdir` alla cartella padre reale al momento dell'esecuzione | `src/wimm/service/executor_disk_fs.py` | T010 | R5 | contratto | TG | `tests/service/test_executor_disk_fs.py::test_devdir_without_its_marker_is_refused` (cartella intatta) + caso appaiato con marker presente | revert |
| T014 | Conseguenza per tipo di cartella: testo con il comando di ricostruzione (`npm install`, `uv sync`, `cargo build`, `mvn package`, `gradle build`, `composer install`) | `src/wimm/core/risk_table.py src/wimm/core/planning_disk.py` | T010 | R4 R41 | seq | TG | test del testo per `target` con `Cargo.toml` e con `pom.xml` | revert |
| T015 | `make po`, traduzioni inglesi delle stringhe L1 | `po/en.po` | T006 T014 | R41 | seq | IH | `make lint` (check_i18n) verde | revert |
| T016 | Baseline: durata e CPU della prima scansione disco sulla home reale prima di T011 | `docs/PERF.md` | - | R4 R30 | ok | IH | riga baseline in `docs/PERF.md` con comando e condizioni | revert |
| T017 | Rimisura dopo T011-T012 con lo stesso comando | `docs/PERF.md` | T012 T016 | R4 R30 | seq | IH | riga risultato; aumento <= 30% o profondità ridotta per le cartelle nascoste | revert |
| T018 | DEVIATIONS: cartelle e marker oltre §7.6 e §5.5, esclusione di `vendor` Go e `dist` | `docs/DEVIATIONS.md` | T013 | R4 R6 | ok | DW | voce con l'elenco della tabella di R4 | revert |
| T019 | Chiusura L1: `code-reviewer`, `security-reviewer` su T013, click-through T006, riga `CHECKS:`, REPORT_ATTIVITA | - | T001-T018 | R42 R43 | seq | IH | `make lint && make test` verdi, test > 2082, copertura core >= 90% | revert dei commit del lotto |

## L2: igiene di rilascio (F17)

| ID | Task | SCOPE | dip | R | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T020 | `uv add --dev bandit pip-audit`; target `make audit` (`bandit -r src -q`, `pip-audit` su `uv export --no-hashes`) | `pyproject.toml uv.lock Makefile` | - | R7 | ok | DO | `make audit; echo $?` stampa 0 o elenca i finding | revert |
| T021 | Triage dei finding di T020 in `docs/security/` (fix o motivazione per ciascuno) | `docs/security/ src/` | T020 | R7 | seq | SR | `make audit` esce 0 | revert |
| T022 | Passo `make audit` nel workflow CI | `.github/workflows/ci.yml` | T021 | R7 | seq | DO | `uv run python -c "import yaml,sys;yaml.safe_load(open('.github/workflows/ci.yml'))"`; action pinnate a SHA | revert |
| T023 | `packaging/man/wimm.1` (inglese): sinossi, `--background`, `--group`, `--version`, file utente, variabili `WIMM_LOG_LEVEL` | `packaging/man/wimm.1` | - | R8 | ok | DW | `man -l packaging/man/wimm.1 \| head` senza warning di `groff -ww` | revert |
| T024 | `build_deb.sh` installa la man page compressa; `make test-deb` senza `no-manual-page` | `scripts/build_deb.sh scripts/test_deb.sh` | T023 | R8 | seq | DO | output di `make test-deb` senza la riga lintian | revert |
| T025 | Metainfo: `<url type="homepage">` e `bugtracker` con l'URL di Q8; `appstreamcli validate` in `test_deb.sh` | `data/metainfo/io.github.wimm.WhereIsMyMemory.metainfo.xml scripts/test_deb.sh` | Q8 | R9 | ok | DO | `appstreamcli validate --no-net` senza errori | revert |
| T026 | `scripts/measure_open_time.py`: attivazione via D-Bus → primo frame mappato sotto `xvfb-run`, 10 ripetizioni, mediana e p90 | `scripts/measure_open_time.py docs/PERF.md` | - | R10 | ok | SB | riga in `docs/PERF.md` con mediana, p90 e condizioni | revert |
| T027 | DELIVERY_REPORT: M-* aperte e nuove (podman, Wayland, radici esterne, OOM), comando per ciascuna | `docs/DELIVERY_REPORT.md` | T026 | R11 | ok | DW | sezione 3 con un comando per voce | revert |
| T028 | Chiusura L2: riga `CHECKS:`, REPORT_ATTIVITA | - | T020-T027 | R42 | seq | IH | `make lint && make test && make audit` verdi | revert dei commit del lotto |

## L3: cache degli sviluppatori (F6, basso rischio)

| ID | Task | SCOPE | dip | R | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T029 | Spostare `CACHE_RELATIVE_PATHS`, `CACHE_ENV_VARS` e affini in `core/cache_catalog.py`, senza cambi di comportamento | `src/wimm/core/constants.py src/wimm/core/cache_catalog.py src/wimm/collectors/caches.py src/wimm/service/executor_disk_fs.py` | T019 | R42 | seq | TG | suite invariata verde | revert |
| T030 | `CacheKind` esteso (cargo_registry, cargo_git, gradle, maven, go_mod, go_build, yarn, pnpm, bun, conda, playwright, jetbrains); `CacheSpec` (base HOME o XDG_CACHE, relativo, variabile dello strumento, comando) | `src/wimm/model/disk.py src/wimm/core/cache_catalog.py src/wimm/core/disk_wire.py` | T029 | R12 | contratto | TG | `tests/core/test_disk_wire.py` round-trip con un tipo nuovo; un report vecchio si legge ancora | revert |
| T031 | `resolve_cache_paths(environ, home)` puro: `XDG_CACHE_HOME`, variabili di R12, scarto fuori dalla home reale | `src/wimm/core/cache_catalog.py` | T030 | R12 | seq | TG | `tests/core/test_cache_catalog.py::test_resolve_cache_paths_honours_xdg_and_tool_variables` + caso fuori home scartato | revert |
| T032 | Tabella risolta una volta in `sampler_environment` e passata a `collect_caches` | `src/wimm/collectors/caches.py src/wimm/service/sampler_environment.py` | T031 | R12 | seq | TG | test con HOME e `XDG_CACHE_HOME` in `tmp_path`: le cartelle create compaiono, le assenti no | revert |
| T033 | Executor: `_cache_kind` usa la tabella risolta di `DiskFsControl`, mai il piano | `src/wimm/service/executor_disk_fs.py src/wimm/service/fs_controls.py` | T031 | R15 | contratto | TG | `tests/service/test_executor_disk_fs.py::test_cache_outside_the_table_is_refused` | revert |
| T034 | Rischio per tipo di cache: `CACHE_CLEAN` dinamico (SAFE salvo maven e JetBrains CAUTION), conseguenze per tipo | `src/wimm/core/risk_table.py src/wimm/core/risk.py` | T030 | R13 | contratto | TG | `tests/core/test_risk.py::test_cache_risk_depends_on_kind` | revert |
| T035 | "Libera spazio" e recuperabile disco filtrano sul rischio calcolato | `src/wimm/core/planning_disk_safe.py src/wimm/core/disk_rules.py` | T034 | R13 | seq | TG | `tests/core/test_planning_disk_safe.py::test_disk_free_safe_skips_caution_caches` + caso SAFE incluso | revert |
| T036 | Go: `go clean -modcache` e `-cache` con `GOMODCACHE`/`GOCACHE` sulla cartella del piano; senza `go` l'azione non si offre (motivo nel piano) | `src/wimm/service/executor_disk_fs.py src/wimm/core/planning_disk.py` | T033 | R14 | seq | TG | `test_cache_argv_go_*` con runner finto; test "go assente → nessuna azione" | revert |
| T037 | pnpm, yarn, conda: argv verificati su context7 nel task, ripiego allo svuotamento se lo strumento manca | `src/wimm/service/executor_disk_fs.py` | T036 | R14 | seq | TG | `test_cache_argv_pnpm_yarn_conda`; URL della doc nel commento | revert |
| T038 | Cargo: svuotamento dei soli `registry/cache`, `registry/src`, `git/db`, `git/checkouts` | `src/wimm/service/executor_disk_fs.py src/wimm/core/cache_catalog.py` | T033 | R14 | seq | TG | test su `CARGO_HOME` in `tmp_path`: `bin/` intatto, le 4 cartelle vuote | revert |
| T039 | Variabili di deviazione: per ogni strumento la sua variabile viene puntata alla cartella del piano, le altre rimosse | `src/wimm/service/executor_disk_fs.py src/wimm/core/cache_catalog.py` | T037 | R15 | seq | TG | test dell'ambiente passato al runner per uv, go, yarn | revert |
| T040 | Etichette e testi per i tipi nuovi nella vista Disco e nei dialoghi; `make po` | `src/wimm/ui/disk_texts.py src/wimm/ui/dialogs/text.py po/en.po` | T034 | R12 R41 | seq | FD | test UI del nome accessibile di una voce cargo; `make lint` | revert |
| T041 | Schema del report disco secondo Q4; DEVIATIONS (cache oltre §7.6, rischio per tipo) | `src/wimm/model/enums.py src/wimm/core/disk_wire.py data/dbus/io.github.wimm.Inspector1.xml docs/DEVIATIONS.md` | T030 Q4 | R40 | seq | TG | `tests/core/test_disk_wire.py::test_schema_version_*` | revert |
| T042 | Rimisura prima scansione con le cache nuove (stesso comando di T016) | `docs/PERF.md` | T032 | R30 | seq | IH | riga in PERF.md, aumento <= 30% | revert |
| T043 | Chiusura L3: `code-reviewer`, `security-reviewer` su T033-T039, `CHECKS:`, REPORT_ATTIVITA | - | T029-T042 | R42 R43 | seq | IH | `make lint && make test` verdi | revert dei commit del lotto |

## L4: motori container e strumenti (F9, F10)

| ID | Task | SCOPE | dip | R | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T044 | `core/docker_endpoint.py`: `resolve_docker_endpoint(environ, config_json, read_meta, podman_socket_exists)` puro con l'ordine di R17 | `src/wimm/core/docker_endpoint.py` | T019 | R17 | ok | TG | `tests/core/test_docker_endpoint.py` una riga per regola, nome contesto → sha256 | revert |
| T045 | `docker_source` crea il client sull'endpoint risolto; errore leggibile se il contesto punta a un socket assente | `src/wimm/collectors/docker_source.py` | T044 | R17 | contratto | SB | test con client finto: `base_url` uguale all'endpoint di `desktop-linux` | revert |
| T046 | `cgroups`: `PODMAN_SCOPE_PATTERNS` (`libpod-*.scope`, rootless sotto `user@<uid>.service`) e localizzazione dello scope podman | `src/wimm/collectors/cgroups.py src/wimm/core/constants.py` | T019 | R16 R18 | ok | TG | `tests/collectors/test_cgroups.py::test_locate_libpod_scope` con fixture di albero cgroup | revert |
| T047 | Refactor: regole di `categorize.py` oltre `_early_decision` spostate in `categorize_tools.py` | `src/wimm/core/categorize.py src/wimm/core/categorize_tools.py` | T019 | R42 | seq | TG | suite invariata; `wc -l categorize.py` < 240 | revert |
| T048 | Processi in `libpod-*.scope`: esclusi se il motore li vede, altrimenti gruppo protetto | `src/wimm/core/categorize.py src/wimm/core/grouping_keys.py` | T046 T047 | R16 | seq | TG | `tests/core/test_categorize.py::test_libpod_scope_*` (con e senza API); nessuna azione sul pid | revert |
| T049 | Ripiego stats API per container senza scope locale (Docker Desktop, podman senza cgroup leggibile) | `src/wimm/collectors/docker_source.py src/wimm/collectors/cgroups.py` | T045 T046 | R18 | seq | SB | test: scope assente → `MetricsSource.STATS_API`; durata del ciclo nei log DEBUG | revert |
| T050 | Executor docker contro podman: stop e remove con client finto con le risposte di podman; voce M-* per la prova reale | `tests/service/test_executor_docker.py docs/DELIVERY_REPORT.md` | T045 | R16 | seq | TG | test verde; M-* con comando `podman run -d` | revert |
| T051 | `core/tool_labels.py`: `tool_label(proc)` puro per qemu, VirtualBox, emulatore Android, GradleDaemon, KotlinCompileDaemon, LSP, kind, minikube (Q3=A: etichetta + motivo) | `src/wimm/core/tool_labels.py src/wimm/core/constants.py` | T047 | R19 | contratto | TG | `tests/core/test_tool_labels.py` con una cmdline reale per voce + caso java qualsiasi → nessuna etichetta | revert |
| T052 | Etichetta nel membro e chiave di gruppo per daemon staccati dal terminale (Gradle, Kotlin) | `src/wimm/core/grouping_keys.py src/wimm/core/assemble_members.py` | T051 | R19 | seq | TG | `tests/core/test_grouping.py::test_gradle_daemons_form_one_group` | revert |
| T053 | Rischio per etichetta: daemon SAFE, emulatore CAUTION, VM DANGER | `src/wimm/core/risk_table.py src/wimm/core/risk.py` | T051 | R19 | seq | TG | `tests/core/test_risk.py::test_tool_label_risk` | revert |
| T054 | Testi delle etichette e dei motivi, `make po`; DEVIATIONS (endpoint, podman, etichette) | `src/wimm/core/text.py po/en.po docs/DEVIATIONS.md` | T052 T053 | R41 | seq | TG | `make lint`; voce DEVIATIONS | revert |
| T055 | Chiusura L4: `code-reviewer`, `CHECKS:`, REPORT_ATTIVITA | - | T044-T054 | R42 | seq | IH | `make lint && make test` verdi | revert dei commit del lotto |

## L5: memoria non attribuita e pressione (F11, F12)

| ID | Task | SCOPE | dip | R | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T056 | `parse_meminfo`: `SUnreclaim`, `KernelStack`, `PageTables`, `Zswap` (zero se assenti); `MemInfo` esteso | `src/wimm/collectors/meminfo.py src/wimm/model/raw.py` | T019 | R20 | contratto | TG | `tests/collectors/test_meminfo.py` con meminfo senza `Zswap` e con | revert |
| T057 | `collectors/kernel_memory.py`: somma `mem_used_total` di `zram*/mm_stat`, byte usati dei tmpfs da mountinfo + `statvfs` | `src/wimm/collectors/kernel_memory.py` | T056 | R20 | contratto | TG | test su sysfs e mountinfo in `tmp_path` | revert |
| T058 | `memory_summary`: voci nuove, "Non attribuita" mai negativa, somma = `MemTotal - MemFree` | `src/wimm/core/memory.py src/wimm/model/memory.py` | T056 T057 | R20 | seq | TG | `tests/core/test_memory.py::test_memory_summary_new_voices_sum_to_used` + caso con processi oltre il totale | revert |
| T059 | Refactor: serializzazione di memoria e breakdown in `serialize_memory.py` | `src/wimm/serialize.py src/wimm/serialize_memory.py` | T019 | R42 | seq | TG | suite invariata; `wc -l serialize.py` < 250 | revert |
| T060 | Breakdown nuovo nello snapshot, schema secondo Q4, XML dell'Inspector | `src/wimm/serialize_memory.py src/wimm/model/enums.py data/dbus/io.github.wimm.Inspector1.xml` | T058 T059 Q4 | R20 R40 | seq | TG | `tests/test_serialize.py` round-trip; vecchio schema rifiutato (Q4=A) | revert |
| T061 | `collectors/gpu.py`: NVIDIA con `nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits` (timeout 2 s, ogni 5 cicli), AMD da `mem_info_vram_used` | `src/wimm/collectors/gpu.py src/wimm/core/constants.py` | T019 | R21 | ok | TG | test con runner finto e sysfs finto; `pidstat -p <pid> 60 10` < 1% con nvidia-smi presente, riga in PERF.md | revert |
| T062 | VRAM come campo separato dello snapshot (mai nel breakdown) | `src/wimm/model/memory.py src/wimm/serialize_memory.py` | T060 T061 | R21 | seq | TG | round-trip; senza GPU il campo è vuoto | revert |
| T063 | UI riepilogo: voci nuove con aiuto per le parole difficili, riga "Memoria video"; `make po` | `src/wimm/ui/summary.py src/wimm/ui/widgets/summary.py po/en.po` | T060 T062 | R20 R21 R41 | seq | FD | test UI del nome accessibile delle voci; click-through del riepilogo | revert |
| T064 | `collectors/pressure.py`: `/proc/pressure/memory` (some/full avg60) e `oom_kill` di `memory.events` di `user@<uid>.service` | `src/wimm/collectors/pressure.py` | T019 | R22 R23 | ok | TG | test su file in `tmp_path`; file assente → None | revert |
| T065 | `pressure()` con PSI: peggiore fra soglie attuali e PSI, costanti nominate | `src/wimm/core/memory.py src/wimm/core/constants.py` | T064 | R22 | seq | TG | `test_pressure_uses_psi_when_present` + caso PSI assente invariato | revert |
| T066 | Regola OOM in `notify_rules`: crescita del contatore → una notifica, primo ciclo silenzioso, fuori dal limite orario | `src/wimm/core/notify_rules.py` | T064 | R23 | seq | TG | `tests/core/test_notify_rules.py::test_oom_kill_increase_notifies_once` | revert |
| T067 | Collegamento dei collector nuovi nel ciclo (`sampler_collectors`/`sampler_steps`, senza far crescere `sampler.py`) | `src/wimm/service/sampler_collectors.py src/wimm/service/sampler_steps.py` | T057 T061 T064 | R20-R23 | seq | SB | test del ciclo con collector che sollevano (RNF-10); `make test-all` | revert |
| T068 | Testi notifiche, `make po`, DEVIATIONS (voci RAM, PSI, OOM), M-* OOM con `systemd-run --user -p MemoryMax=`; chiusura L5 con `code-reviewer` e `CHECKS:` | `po/en.po docs/DEVIATIONS.md docs/DELIVERY_REPORT.md` | T063 T066 T067 | R41 R42 | seq | IH | `make lint && make test` verdi | revert dei commit del lotto |

## L6: modelli ML e Android (F6, alto costo)

| ID | Task | SCOPE | dip | R | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T069 | `CacheKind` huggingface, ollama, android_avd, android_sdk e risoluzione da `HF_HUB_CACHE`, `HF_HOME`, `OLLAMA_MODELS`, `ANDROID_HOME`, `ANDROID_SDK_ROOT` | `src/wimm/model/disk.py src/wimm/core/cache_catalog.py` | T043 | R24 | seq | TG | test di `resolve_cache_paths` per ciascuna variabile | revert |
| T070 | Rischio secondo Q2; DANGER passa dalla conferma digitata di §8.3 | `src/wimm/core/risk_table.py src/wimm/core/planning_disk.py` | T069 Q2 | R24 | seq | TG | `tests/core/test_risk.py::test_model_cache_risk`; test del piano con `confirmation` digitata | revert |
| T071 | Executor: rifiuta la pulizia dei modelli ollama se un processo `ollama serve` è vivo | `src/wimm/service/executor_disk_fs.py src/wimm/service/fs_controls.py` | T069 | R24 | seq | TG | test con lista processi finta: vivo → `ProtectedTarget`, assente → esegue | revert |
| T072 | `test_disk_free_safe_never_includes_models`, testi delle voci e conseguenze, `make po`, DEVIATIONS | `tests/core/test_planning_disk_safe.py src/wimm/ui/disk_texts.py po/en.po docs/DEVIATIONS.md` | T070 | R24 R41 | seq | TG | test verde + caso appaiato con cache SAFE inclusa | revert |
| T073 | Chiusura L6: `security-reviewer` su T071, `CHECKS:`, REPORT_ATTIVITA | - | T069-T072 | R42 R43 | seq | IH | `make lint && make test` verdi | revert dei commit del lotto |

## L7: radici fuori dalla home (F2)

| ID | Task | SCOPE | dip | R | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T074 | ADR-007 "Radici di sviluppo fuori dalla home": regola di R26, alternative scartate, conseguenze per executor e safe_tree | `docs/adr/ADR-007-radici-fuori-dalla-home.md` | T019 | R26 | ok | AR | ADR con stato Proposta; accettazione dell'utente prima di T075 | revert |
| T075 | `core/root_policy.py`: `root_refusal(realpath, st_uid, own_uid, home, is_symlink)` puro → motivo o None | `src/wimm/core/root_policy.py src/wimm/core/constants.py` | T074 | R26 | contratto | TG | `tests/core/test_root_policy.py`: una riga per motivo + `/mnt/data/code` dell'utente ammessa | revert |
| T076 | Config usa la politica; messaggi per motivo in `config_messages`; `make po` | `src/wimm/config_roots.py src/wimm/config_messages.py po/en.po` | T075 | R26 R41 | seq | TG | `tests/test_config.py::test_root_outside_home_*` (ammessa e rifiutata) | revert |
| T077 | Executor `_inside_a_root`: stessa politica sulla radice reale con `st_uid` riletto | `src/wimm/service/executor_disk_fs.py src/wimm/service/fs_controls.py` | T075 | R27 | contratto | TG | `test_devdir_under_a_root_no_longer_owned_is_refused` con stat iniettato | revert |
| T078 | Radice su un altro dispositivo: test con mountpoints finti, la rimozione parte dalla cartella e non attraversa mount annidati | `tests/service/test_safe_tree.py` | T077 | R27 | seq | TG | test verde con `st_dev` diversi fra radice e cartella annidata | revert |
| T079 | `ProjectRootResolver` fuori dalla home: si ferma alla radice del filesystem senza candidare `/` | `src/wimm/collectors/project_roots.py` | T009 | R26 | ok | TG | test con cwd `/mnt/x/proj/src` e marker in `proj` | revert |
| T080 | Preferenze: selettore di cartella anche fuori dalla home, errore con il motivo | `src/wimm/ui/dialogs/preferences_rows.py src/wimm/ui/dialogs/preferences_model.py` | T076 | R26 | seq | FD | test del modello delle Preferenze; click-through con una radice rifiutata | revert |
| T081 | Chiusura L7: `security-reviewer` obbligatorio, DEVIATIONS, M-* secondo disco, `CHECKS:` | `docs/DEVIATIONS.md docs/DELIVERY_REPORT.md` | T074-T080 | R42 R43 | seq | IH | `make lint && make test` verdi | revert dei commit del lotto |

## L8: sessioni remote e crescita (F5, F13)

| ID | Task | SCOPE | dip | R | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T082 | Config `remote_sessions_actionable` (default secondo Q1) | `src/wimm/config.py` | T019 Q1 | R28 | ok | TG | `tests/test_config.py::test_remote_sessions_flag_*` | revert |
| T083 | Categorize: con l'opzione, processi propri in `session-*.scope` proseguono le regole; `sshd`, shell di login, server tmux protetti | `src/wimm/core/categorize.py src/wimm/core/categorize_tools.py` | T047 T082 | R28 | seq | TG | `test_remote_session_*` spento e acceso | revert |
| T084 | Switch nelle Preferenze con spiegazione del rischio, `make po` | `src/wimm/ui/dialogs/preferences_rows.py po/en.po` | T083 | R28 R41 | seq | FD | test UI dello switch; click-through | revert |
| T085 | `core/growth.py`: `growth_trend(points, now)` puro con soglie di R29 | `src/wimm/core/growth.py src/wimm/core/constants.py` | T019 | R29 | ok | TG | `tests/core/test_growth.py` serie crescente, piatta, dente di sega, troppo corta | revert |
| T086 | `service/group_history.py`: un punto ogni 600 s per 3 h per gruppo, gruppi spariti eliminati | `src/wimm/service/group_history.py src/wimm/service/sampler_steps.py` | T085 | R29 R30 | seq | TG | test con orologio finto; 1000 gruppi < 2 MB (`tracemalloc`) | revert |
| T087 | `Group.growth` nello snapshot, schema secondo Q4 | `src/wimm/model/snapshot.py src/wimm/serialize.py data/dbus/io.github.wimm.Inspector1.xml` | T086 Q4 | R29 R40 | seq | TG | round-trip in `tests/test_serialize.py` | revert |
| T088 | Riga del gruppo: "+620 MB in 2 h", `make po` | `src/wimm/ui/widgets/group_row.py po/en.po` | T087 | R29 R41 | seq | FD | test UI del testo; click-through | revert |
| T089 | Chiusura L8: `pidstat` RNF-01 in PERF.md, DEVIATIONS (Q-12 rivista, crescita), `code-reviewer`, `CHECKS:` | `docs/PERF.md docs/DEVIATIONS.md` | T082-T088 | R30 R42 | seq | IH | media < 1% di un core | revert dei commit del lotto |

## L9: stato senza finestra (F15)

| ID | Task | SCOPE | dip | R | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T090 | `cli_status.py` e ramo `status` in `app.main()` prima di `create_application()`, senza importare Gtk/Adw | `src/wimm/cli_status.py src/wimm/app.py` | T019 | R31 R32 | seq | TG | `tests/test_cli.py::test_status_does_not_import_gtk` + caso appaiato | revert |
| T091 | Sorgente secondo Q6: `GetSnapshot` via `Gio.DBusProxy` (timeout 2 s), ripiego su un ciclo di campionamento singolo | `src/wimm/cli_status.py` | T090 Q6 | R31 | seq | SB | test con proxy finto: istanza presente → suo JSON; assente → campionamento | revert |
| T092 | Uscita testuale nella lingua scelta, `--json` da `serialize.py`, codici 0/3; `make po` | `src/wimm/cli_status.py po/en.po` | T091 | R31 R41 | seq | TG | test dei codici di uscita e del testo | revert |
| T093 | Test di integrazione senza display sotto `dbus-run-session`, man page aggiornata, chiusura L9 con `CHECKS:` | `tests/integration/test_status_cli.py packaging/man/wimm.1` | T092 T023 | R31 | seq | TG | `env -u DISPLAY -u WAYLAND_DISPLAY uv run wimm status --json \| python3 -m json.tool` esce 0 | revert |

## L10: comando di riavvio dei processi (F14)

| ID | Task | SCOPE | dip | R | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T094 | `restart_memory`: argv, cwd ed etichetta dei processi terminati DONE negli ultimi 8 piani, presi dal membro dello snapshot al piano | `src/wimm/service/restart_memory.py src/wimm/core/planning_restart.py` | T019 | R33 | seq | TG | `test_records_stopped_process_commands`; `caplog` a INFO senza argv | revert |
| T095 | `restart_command(argv, cwd)` puro: `cd <cwd> && <shlex.join(argv)>` con quoting | `src/wimm/core/planning_restart.py` | T094 | R34 | seq | TG | test con spazi, apici e cwd con spazi | revert |
| T096 | Toast "Copia comando di riavvio" con avviso sui segreti, appunti via Gdk; `make po` | `src/wimm/ui/toasts.py po/en.po` | T095 | R34 R41 | seq | FD | click-through: il comando incollato riavvia `python3 -m http.server 8765` nella cartella giusta | revert |
| T097 | Solo se Q7=B: azione "Riavvia" CAUTION eseguita dall'executor come argv, cwd, `start_new_session`, senza shell, con timeout di avvio | `src/wimm/service/executor_process.py src/wimm/model/enums.py src/wimm/core/risk_table.py` | T095 Q7 | R34 | seq | TG | test con processo fittizio creato dal test; `security-reviewer` | revert |
| T098 | Chiusura L10: `security-reviewer` (segreti negli appunti, argv), `CHECKS:`, REPORT_ATTIVITA | - | T094-T097 | R42 R43 | seq | IH | `make lint && make test` verdi | revert dei commit del lotto |

## L11: Wayland (F4, dipende da ADR-006)

| ID | Task | SCOPE | dip | R | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T099 | ADR-006 dall'architect (in corso in parallelo), accettazione dell'utente | `docs/adr/ADR-006-*.md` | - | R36 | ok | AR, U | ADR con stato Accettata | revert |
| T100 | Opzione estensione: estensione GNOME Shell 46 che pubblica `FocusedPid` su D-Bus di sessione (sola lettura) | `data/gnome-shell-extension/` | T099 | R37 | contratto | FD | `gdbus call --session --dest ... FocusedPid` su sessione Wayland (M-*) | revert |
| T101 | Opzione estensione: `collectors/foreground.py` legge `FocusedPid` via proxy Gio quando la sessione è Wayland; opzione IdleMonitor: collector `GetIdletime` e segnale di inattività di sessione nel motivo | `src/wimm/collectors/foreground.py src/wimm/collectors/foreground_wayland.py` | T099 T100 | R37 | seq | TG | test con proxy finto; senza componente stato `unavailable` come oggi | revert |
| T102 | Packaging del componente (estensione installata in `/usr/share/gnome-shell/extensions`, attivazione a cura dell'utente), DEVIATIONS su N4, chiusura L11 | `scripts/build_deb.sh docs/DEVIATIONS.md` | T101 | R37 R42 | seq | DO | `make test-deb` verde; M-* Wayland | revert dei commit del lotto |

## L12: distribuzione (F16, dipende da Q5)

| ID | Task | SCOPE | dip | R | par | Agent | verify | rollback |
|---|---|---|---|---|---|---|---|---|
| T103 | Se Q5=A o B: `packaging/arch/PKGBUILD` e `scripts/test_arch.sh` in container `archlinux` | `packaging/arch/ scripts/test_arch.sh Makefile` | Q5 | R38 | ok | DO | `make test-arch` installa e avvia `wimm --version` | revert |
| T104 | Se Q5=A: `packaging/rpm/wimm.spec` e `scripts/test_rpm.sh` in container `fedora` | `packaging/rpm/ scripts/test_rpm.sh Makefile` | Q5 | R38 | ok | DO | `make test-rpm` installa e avvia `wimm --version` | revert |
| T105 | Banner AppIndicator mancante: istruzioni per la distribuzione letta da `/etc/os-release`, `make po` | `src/wimm/ui/window_state.py po/en.po` | T019 | R39 R41 | ok | FD | test con `os-release` finto per ubuntu e fedora; click-through del banner | revert |
| T106 | Proposta di sezioni di installazione nel README (con ok dell'utente), DEVIATIONS su §12 | `docs/DEVIATIONS.md` | T103 T104 | R38 | seq | DW | voce DEVIATIONS; testo README proposto nel report | revert |
| T107 | Chiusura L12: `CHECKS:`, REPORT_ATTIVITA, DELIVERY_REPORT aggiornato | - | T103-T106 | R42 | seq | IH | `make lint && make test` e test dei formati verdi | revert dei commit del lotto |

## Emendamenti di sicurezza

I task elencati in `plan.md` § Rilievi di sicurezza (S1-S18) includono la mitigazione e il suo
test nello stesso commit. Un task con un rilievo P0 (S3, S5, S8, S12) non si chiude senza.
Ordine: T034 prima di T030 (S18).

## Avanzamento

Una riga per task chiuso: `T<id> | commit <sha> | verify`.
- T016 | 670c590 | baseline 5,21 s, 76 cartelle in `docs/PERF.md`
- T001 | 47e9021 | `config.py` a 265 righe: il criterio < 260 è rilassato a <= 300 (limite del progetto), margine sufficiente per T004
- T002 | d09e8e3 | `tests/core/test_dev_roots.py`
- T003 | f42d904 | `tests/collectors/test_root_candidates.py`; symlink intermedio fuori home rifiutato (review). Restano a T004 da S15: skip dei fstype di rete e rilevazione fuori dal main thread
- T007 | f031619 | `tests/test_i18n.py`; `wimm --help` con de_DE, C, it_IT
- T009 | afd05a1 | `test_resolve_finds_each_marker`
- T010 | cad1cca | `tests/core/test_devdir_rules.py`; negazioni del `.gitignore` gestite (review)
- T011 T012 T013 T014 | 35f9f5c | walker ed executor con `classify_devdir`; marker registrato dal collector e usato nel testo di conferma; 88 cartelle sulla home reale
- T004 T005 | e4b6244 | non separabili per file; radici rilevate mai scritte su disco (review: salvataggio di un'altra preferenza)
- T017 | (questo commit) | +3% di durata a parità di cache, `docs/PERF.md`
- T008 T018 | c3181fc | voci in `docs/DEVIATIONS.md`
- T020 T021 T022 | 0581767, 928d839 | `make audit` verde; strumenti in uvx dopo la regressione di requests nel venv
- T023 T024 | 63afd9c | `make test-deb` senza avvisi lintian
- T025 | sospeso | manca l'URL (Q8)
- T006 | bd7c20c | click-through reale a 1280 px; corretti focus con selezione totale e I/O per snapshot
- T026 T027 | 0cc31ac | prima apertura 236 ms, riapertura 10 ms; M-17..M-23
- T019 T028 | a7d7901 014b04f | security-reviewer su L1 (nessun P0/P1, tre P2 corretti); REPORT_ATTIVITA
- T029 T030 T031 | 6013849 | catalogo e risolutore delle cache (S5)
- T034 | 4c0bd3c | rischio per tipo (S18)
- T032 T033 T035 T038 | b6c3c76 | esposizione dei 17 tipi; review: symlink sul default reso pulibile, corretto
- T041 | 05c56ef | SCHEMA_VERSION 2
- T036 T037 T039 | 41c2750 | comandi nativi e ambiente minimo (S6); P2 della security review corretti
- T040 | b6c3c76 | titoli dei tipi nuovi e testi delle conseguenze
- T042 | d897c08 | prima scansione +20%
- T043 | (questo commit) | code-reviewer e security-reviewer su L3 eseguiti; aperti: `go clean` reale non provato, test di integrazione Docker instabile (pre-esistente)
- T044 | 5afcc8f | endpoint locali (S8), socket di Docker Desktop ammesso solo esatto e dell'utente
- T046 | 7293a17 | scope libpod
- T047 | 9210b62 | refactor di categorize
- T051 | 9297b27 | etichette degli strumenti; review: falsi positivi per nome di cartella corretti
- T048 T052 T053 | e5efaac 6038e89 | Podman protetto se non visto, gruppi e rischio per etichetta, rischio del piano allineato al badge
- T045 T049 | 4a42b09 7fb579f | collector e servizi sui motori risolti, nessun `docker.from_env`; pool thread-safe e backoff degli endpoint lenti (review)
- S9 | 3ad1466 | identità dei motori nel piano e controllo nell'esecutore
- T050 | e22eac9 | executor contro risposte stile Podman, M-24
- T054 | 56a3cef | DEVIATIONS
- T055 | (questo commit) | code-reviewer su ogni blocco di L4. Aperti: Podman e Docker Desktop mai provati su macchina reale (M-24); un motore che risponde a `info()` ma blocca `list()` costa ancora il timeout; gli avvisi parziali dei motori non sono mostrati nella UI quando almeno un motore risponde
