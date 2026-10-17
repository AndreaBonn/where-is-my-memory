# where-is-my-memory: task

Riferimenti: `plan.md` (assunzioni A1-A11, domande Q-1..Q-12, checklist M-1..M-16), `spec.md`
(R1-R68), `assets/SPECIFICHE.md` (prevale). Id = `T-x.y` della §16; un suffisso `a/b/c/d` spezza un
task oltre 30 min, mai rinumerato. `T-0.3` e `T-6.x` sono aggiunte dell'utente (D-U3, Fase 6).

Colonne: `par` = `ok` (nessun file o interfaccia in comune con task aperti), `seq` (usa l'output o i
file di un altro task), `contratto` (dipende da un'interfaccia fissata dal task in `dip`).
Agent: `TG` tdd-guide, `SB` senior-backend, `DO` devops-engineer, tutti con `[DELEGATE-CODEX]`;
`FD` fullstack-developer in-house; `DW` doc-writer; `SR` security-reviewer; `IH` orchestratore.
SCOPE: path relativi alla root; i test sono sempre in `tests/<stesso path>`, inclusi nello SCOPE.
Rollback `revert` = basta annullare il commit. Ogni task si chiude con `make lint && make test`
verdi oltre al proprio `verify`; il test rosso si vede prima del verde (test-first).

## Fase 0: scheletro

| Id | Descrizione | verify | dip | R | par | agent | SCOPE | rollback |
|---|---|---|---|---|---|---|---|---|
| T-0.1a | `git init`; `pyproject.toml` (hatchling, `wimm = "wimm.app:main"`, `requires-python>=3.12`, `dependencies=[]`, gruppo dev §14.1), ruff (select §14.1, line 100, S602/S604), mypy strict su `core/` e `model.py`, Makefile (setup/test/test-all/lint/run/deb, `--cov=src/wimm/core --cov-fail-under=90` in `test`), `src/wimm/__init__.py` con `__version__`, `tests/test_runtime_versions.py`. Chiude la premessa stub (A9): prova pin, se fallisce applica il ripiego della tabella premesse e scrive `docs/DEVIATIONS.md` | `make setup && make lint && make test` verdi; il test asserisce `psutil.__version__=="5.9.8"` e `docker.__version__=="5.0.3"`; `docs/DEVIATIONS.md` ha la voce "stub" | - | R37 R65 R68 | seq | DO | `pyproject.toml Makefile uv.lock .gitignore src/wimm/__init__.py tests/test_runtime_versions.py tests/conftest.py docs/DEVIATIONS.md` | revert; `rm -r .venv` se il venv è corrotto |
| T-0.1b | `CLAUDE.md` (comandi, architettura breve, convenzioni lingua), `LICENSE` GPL-3.0-or-later, `README.md` minimo, `docs/REPORT_ATTIVITA.md` vuoto, `tests/test_source_limits.py` (300/30/4, allowlist nominata per le sole firme dettate da Gio) | il test limiti fallisce su un file di prova da 31 righe di funzione e passa sul repo | T-0.1a | R57 | seq | DO | `CLAUDE.md LICENSE README.md docs/REPORT_ATTIVITA.md tests/test_source_limits.py` | revert |
| T-0.2a | `model.py`: enum (`Category`, `Protection`, `Risk`, `ActivityState`, `ActionKind` §8.1), dataclass frozen `RawProcess`, `RawContainer`, `RawSocket`, `MemInfo`, `Entity`, `Group`, `Snapshot`, `ActionRequest` (con `excluded_ids` se Q-5=A), `Plan`, `PlanStep`. Contratto di tutti i task successivi | `uv run mypy src/wimm/model.py` strict verde; test di costruzione con valori di §6.5 | T-0.1a | R58 R61 | contratto | TG | `src/wimm/model.py tests/test_model.py` | revert |
| T-0.2b | `serialize.py` Snapshot <-> JSON schema 1 (byte interi, ISO 8601 con fuso, enum come stringhe §6.5); fixture `tests/fixtures/snapshot_whitebox.json` | round-trip `from_json(to_json(s)) == s` sulla fixture; JSON con `pressure` fuori vocabolario rifiutato | T-0.2a | R63 | seq | TG | `src/wimm/serialize.py tests/test_serialize.py tests/fixtures/snapshot_*.json` | revert |
| T-0.3 | `.github/workflows/ci.yml`: `ubuntu-24.04`, `permissions: contents: read`, `actions/checkout` e `astral-sh/setup-uv` pinnate a SHA con commento di versione, `persist-credentials: false`, `apt-get install python3-gi python3-psutil python3-docker gir1.2-gtk-4.0 gir1.2-adw-1`, `make setup`, `make lint`, `make test` | `yamllint .github/workflows/ci.yml` verde; `grep -E "uses: .+@[0-9a-f]{40}"` trova ogni `uses:`; nessun `pull_request_target`. Run verde dopo il push dell'utente | T-0.1a | R66 | ok | DO | `.github/workflows/ci.yml` | revert |

**CP-0** checkpoint umano (M-1, Q-7): l'utente conferma che lo skeleton parte prima della Fase 1.

## Fase 1: sola visione

| Id | Descrizione | verify | dip | R | par | agent | SCOPE | rollback |
|---|---|---|---|---|---|---|---|---|
| T-1.1a | `collectors/meminfo.py`: `parse_meminfo(text) -> MemInfo` (kB -> byte), lettore di `/proc/meminfo`; `collectors/disk.py` con `shutil.disk_usage` per `/` e la mount della home | test su fixture copiata da `/proc/meminfo`; esecuzione reale entro 2% di `free -b` nello stesso istante | T-0.2a | R43 | contratto | SB | `src/wimm/collectors/{__init__,meminfo,disk}.py tests/collectors/ tests/fixtures/meminfo*` | revert |
| T-1.1b | `core/constants.py` (default §11, `PROTECTED_PROCESS_NAMES`, `DOCUMENT_APP_NAMES`, categorie documento), `core/memory.py`: PSS/USS+swap per gruppo, container `memory.current - inactive_file`, breakdown con `kernel_cache` e `unattributed >= 0`, `reclaimable_now` (Q-6), `pressure` | test con valori: kernel_cache = Cached+Buffers+SReclaimable-Shmem; unattributed mai negativo; pressure `warning` a 14% e `critical` a 9% | T-0.2a | R1 R2 | contratto | TG | `src/wimm/core/{__init__,constants,memory}.py tests/core/` | revert |
| T-1.2a | `collectors/cgroups.py` parte processi: `parse_proc_cgroup(text)` (riga `0::`), `parse_proc_stat_tpgid(text)`, `is_docker_scope(path)`; fixture coi 4 cgroup reali di §5.1 | test sui 4 esempi reali di §5.1 e su un `stat` con nome contenente spazi e parentesi | T-0.2a | R58 | ok | SB | `src/wimm/collectors/cgroups.py tests/collectors/test_cgroups.py tests/fixtures/cgroup*` | revert |
| T-1.2b | `collectors/processes.py`: psutil iniettato, campi §7.1 per uid proprio, solo name/uids/rss per gli altri, esclusione scope Docker, `NoSuchProcess/AccessDenied/ZombieProcess` per processo; `collectors/project_roots.py` (marker §5.5.3, cache) (A4) | test con psutil finto che solleva per un PID: gli altri restano; esecuzione reale elenca i processi utente in < 1,5 s (log durata) | T-1.2a | R33 R58 | seq | SB | `src/wimm/collectors/{processes,project_roots}.py tests/collectors/` | revert |
| T-1.3 | `collectors/sockets.py`: `psutil.net_connections("tcp")`, porte LISTEN per PID, quadruple non-LISTEN, connessioni per porta del server anche fra antenato/discendente | test: `python3 -m http.server 0` avviato dal test compare con la sua porta in LISTEN; ucciso in `finally` | T-0.2a | R60 | ok | SB | `src/wimm/collectors/sockets.py tests/collectors/test_sockets.py` | revert |
| T-1.4a | `core/categorize.py` parte 1: regole 1-4 (SELF per pid, SYSTEM altro uid o fuori `user@<uid>.service` (Q-12), esclusione scope Docker, SESSION e lista protetta con glob, `extra_protected_names` che aggiunge e non toglie) | una riga di test per regola; `gnome-shell`, `pipewire`, `gsd-color`, processo uid 0 -> protected; rimuovere un default via config non ha effetto (con caso positivo: aggiungere un nome lo protegge) | T-1.1b | R47 R58 | contratto | TG | `src/wimm/core/categorize.py tests/core/test_categorize.py` | revert |
| T-1.4b | `core/categorize.py` parte 2: regole 5-9 secondo Q-1 e Q-3 (BROWSER/DESKTOP_APP/TERMINAL per scope o antenato, helper editor, AI_CLI, DEV_SERVER, DEV_PROCESS, shell senza azioni, OTHER), "con documenti" da Categories o `DOCUMENT_APP_NAMES` | albero reale gnome-terminal-server -> zsh -> uvicorn (LISTEN) = DEV_SERVER; `claude` in vte-spawn = AI_CLI; firefox snap = BROWSER; pyright figlio di code = DESKTOP_APP | T-1.4a | R46 R58 | seq | TG | `src/wimm/core/categorize.py tests/core/test_categorize.py` | revert |
| T-1.4c | `collectors/desktop_entries.py`: indice dei `.desktop` nelle 4 directory di §5.5.5 (Name, Categories, appid), cache per mtime | test su tmpdir con 2 `.desktop` finti; appid `org.gnome.Terminal` risolto dal file reale | T-0.2a | R8 | ok | SB | `src/wimm/collectors/desktop_entries.py tests/collectors/test_desktop_entries.py tests/fixtures/desktop/` | revert |
| T-1.5a | `collectors/cgroups.py` parte container: `parse_memory_stat`, `parse_cpu_stat`, `parse_net_dev` (somma senza `lo`), fallback di localizzazione via `/proc/<pid>/cgroup` | test su fixture dei 3 formati reali; path assente -> fallback attivato | T-1.2a | R44 | seq | SB | `src/wimm/collectors/cgroups.py tests/collectors/test_cgroups.py tests/fixtures/` | revert |
| T-1.5b | `collectors/docker_source.py`: client iniettato, `containers.list(all=True)`, label/mounts/state/ports/pid, lettura cgroup, `docker.available=false` col motivo, fallback `stats(stream=False)` limitato (R9 §18). Solo lettura | test con client finto che solleva `DockerException`: snapshot con `available=false`; esecuzione reale: memoria dei container in esecuzione entro 5% di `docker stats --no-stream` | T-1.5a | R39 R44 | seq | SB | `src/wimm/collectors/docker_source.py tests/collectors/test_docker_source.py` | revert |
| T-1.6a | `core/grouping.py` parte 1: gruppi compose per label con `working_dir`, container singoli, processi per radice di progetto, figli di app/browser/terminal all'antenato | test: 6 container `whitebox` + 1 senza compose -> 2 gruppi; processi con stessa radice -> 1 gruppo | T-1.4b | R44 | seq | TG | `src/wimm/core/grouping.py tests/core/test_grouping.py` | revert |
| T-1.6b | `core/grouping.py` parte 2: fusione PROJECT (radice uguale, antenata o discendente del `working_dir`), gruppi app per scope con Name da `.desktop`, resto per processo radice, id stabile = hash(categoria, chiave); spiegazione in `core/text.py` | test: compose + uvicorn con cwd in `working_dir` = 1 gruppo PROJECT; id identico fra due campioni con PID diversi; spiegazione contiene cartella e porta | T-1.6a | R8 | seq | TG | `src/wimm/core/{grouping,text}.py tests/core/` | revert |
| T-1.7a | `service/history.py`: ring buffer per entità (`deque(maxlen=finestra/intervallo+1)`), delta CPU di processo+figli, quadruple nuove, tasso rete container, rimozione dopo 2 cicli di assenza | test: connessione presente in 2 campioni consecutivi non è nuova; entità assente 3 cicli rimossa | T-0.2a | R60 | ok | TG | `src/wimm/service/{__init__,history}.py tests/service/test_history.py` | revert |
| T-1.7b | `core/activity.py`: `assess_activity` (active/idle/unknown, `since`, persistenza che vince sulla storia corta ma non su un campione attivo, gruppo), motivi coi numeri in `core/text.py` | test: HMR (websocket aperta, CPU 0,1%) -> idle col motivo "connessione aperta da un browser"; storia di 4 min -> unknown "in osservazione da 4 minuti"; `last_active_at` persistito -> idle subito | T-1.7a | R9 R10 R11 R45 R60 | seq | TG | `src/wimm/core/{activity,text}.py tests/core/` | revert |
| T-3.1a | (anticipato da Fase 3, Q-4) `core/risk.py`: `assess_risk` righe processi/app della tabella §5.3 (idle/active, foreground `tpgid`, AI_CLI, BROWSER, DESKTOP_APP con/senza documenti, TERMINAL, SIGKILL e database locali); conseguenze in `core/text.py` | test parametrico: una riga di tabella = un caso con livello e testo atteso | T-1.4b | R59 | seq | TG | `src/wimm/core/{risk,text}.py tests/core/test_risk.py` | revert |
| T-3.1b | `core/risk.py` righe container, compose, immagini, build cache, volumi, cache, cestino, devdir; rischio di gruppo = massimo dei membri; `primary_action` | test parametrico sulle righe restanti; gruppo safe+caution -> caution | T-3.1a | R59 | seq | TG | `src/wimm/core/{risk,text}.py tests/core/test_risk.py` | revert |
| T-1.8a | `service/sampler.py`: ciclo nel `ThreadPoolExecutor(max_workers=1)` senza sovrapposizioni, collector -> history -> core -> `Snapshot`, eccezione di un collector isolata, durata ciclo a DEBUG | test con collector che solleva: il ciclo dopo produce snapshot; test che un secondo ciclo non parte se il primo è in corso | T-1.1b T-1.3 T-1.5b T-1.6b T-1.7b T-3.1b | R33 R40 | seq | SB | `src/wimm/service/sampler.py tests/service/test_sampler.py` | revert |
| T-1.8b | `service/app_service.py` (solo `snapshot()`, `config()`, segnale `snapshot-updated` via `GLib.idle_add`), `service/errors.py`, `config.py` (Config frozen coi default, load da JSON), `logging_setup.py` (stderr + rotante 1 MB x 3, `WIMM_LOG_LEVEL`, niente cmdline a INFO) | test servizio iterando `GLib.MainContext`: segnale emesso sul main loop; test formatter: cmdline assente a INFO, presente a DEBUG | T-1.8a | R38 | seq | SB | `src/wimm/service/{app_service,errors}.py src/wimm/{config,logging_setup}.py tests/service/ tests/test_config.py tests/test_logging_setup.py` | revert |
| T-1.8c | `service/inspector_dbus.py` + `data/dbus/*.xml` (GetSnapshot, GetDiskReport, Version), `app.py` (Adw.Application, `HANDLES_COMMAND_LINE`, `hold()`, `--background`, `--group`, `--version` senza bus, `WIMM_APP_ID`), `scripts/dev_run.sh` | test `dbus`: introspezione ha solo i 3 membri, `GetSnapshot` è JSON schema 1; `gdbus call --session --dest io.github.wimm.WhereIsMyMemory.Devel ... GetSnapshot` restituisce JSON valido con `make run` | T-1.8b | R43 R45 R62 R63 | seq | SB | `src/wimm/{app,__main__}.py src/wimm/service/inspector_dbus.py data/dbus/ scripts/dev_run.sh tests/service/test_inspector_dbus.py` | revert |
| T-1.9a | `ui/viewmodel.py` puro: snapshot -> righe (ordinamento per recuperabile, filtri, ricerca, formati "1,1 GB", "da 5 h", badge testo), righe Sistema | test con fixture: ordine, filtro Inattivi, durate, riga protetta senza azione | T-0.2b T-3.1b | R1 R3 R4 R7 | contratto | FD | `src/wimm/ui/{__init__,viewmodel}.py tests/ui/test_viewmodel.py` | revert |
| T-1.9b | `ui/window.py`: `Adw.ApplicationWindow` 960x720 creata alla prima apertura, ViewSwitcher, menu (Preferenze, Silenzia 1 h, Info, Esci), `close-request` nasconde, dimensioni ricordate, widget `summary.py`, `memory_bar.py` (con legenda testuale), `risk_badge.py` | test `ui`: `close-request` restituisce True e il processo resta; `make run` apre con dati in < 1 s (M-2) | T-1.9a T-1.8c | R29 R34 R43 | seq | FD | `src/wimm/ui/window.py src/wimm/ui/widgets/ tests/ui/` | revert |
| T-1.9c | `ui/pages/overview.py` + `widgets/group_row.py`: righe espandibili coi membri, filtri, ricerca `Ctrl+F`, menu contestuale (copia comando/PID, apri cartella), stati Loading/Empty/Error/Edge di §10.3, pulsanti azione presenti ma senza esecuzione | test `ui`: riga protetta 0 pulsanti, actionable 1; 300 gruppi fixture costruiti senza errori; nome da 200 caratteri ellissato | T-1.9b | R3 R4 R5 R20 | seq | FD | `src/wimm/ui/pages/overview.py src/wimm/ui/widgets/group_row.py tests/ui/` | revert |
| T-1.9d | `ui/pages/system.py` (sola lettura), `Adw.Breakpoint` < 600 px, scorciatoie F5/Ctrl+,, nomi accessibili e tooltip sui pulsanti icona | test `ui`: ogni pulsante solo icona ha label accessibile; render a 360 e 1280 px senza sovrapposizioni (screenshot), click-through da tastiera (M-4) | T-1.9c | R7 R20 R47 | seq | FD | `src/wimm/ui/pages/system.py src/wimm/ui/window.py tests/ui/` | revert |
| T-1.10a | Port da sysbar di `status_notifier.py` e `dbus_menu.py` in `tray/` (limiti rispettati, `XAyatanaLabelGuide` = "88,8 GB inattivi", `ItemIsMenu=false`, `Activate`/`SecondaryActivate`, `IconThemePath` in dev); icone `data/icons/.../wimm-{normal,warning,critical}-symbolic.svg` | test `dbus` su bus privato: Get di `XAyatanaLabelGuide` e `ItemIsMenu`; `Activate` chiama la callback | T-1.8c | R25 R27 | ok | FD | `src/wimm/tray/{__init__,status_notifier,dbus_menu}.py data/icons/ tests/tray/` | revert |
| T-1.10b | `tray/menu_model.py` puro (`build_menu(snapshot)`, 5 inattivi, "Silenzia notifiche per 1 h", "Esci", voce errore dopo 3 cicli falliti), scelta icona a 3 stati ed etichetta (assente < 100 MB), `tray/tray.py` collegato ad `AppService`, `LayoutUpdated` solo se l'hash cambia | test puro su build_menu e icona; `make run`: icona, etichetta, clic sinistro e destro, gruppo del menu apre la finestra espansa (M-2) | T-1.10a T-1.9c | R25 R26 R27 | seq | FD | `src/wimm/tray/{menu_model,tray}.py src/wimm/app.py tests/tray/` | revert |
| T-1.11 | `tray/watcher.py`: `Gio.bus_watch_name` su `org.kde.StatusNotifierWatcher`, ri-registrazione a ogni `name-appeared`, `Adw.Banner` se il watcher manca dopo 10 s (finestra aperta anche con `--background`), banner tolto alla comparsa | test `dbus` con watcher finto che sparisce e ricompare: 2 registrazioni; Alt+F2 r (M-3) | T-1.10b | R53 R62 | seq | FD | `src/wimm/tray/watcher.py src/wimm/ui/window.py tests/tray/test_watcher.py` | revert |

## Fase 2: pacchetto

| Id | Descrizione | verify | dip | R | par | agent | SCOPE | rollback |
|---|---|---|---|---|---|---|---|---|
| T-2.1 | `data/desktop/` (lanciatore `DBusActivatable=false`, `X-GNOME-UsesNotifications=true`; autostart `--background`, `NoDisplay=true`), icona app scalable e symbolic, `data/metainfo/*.metainfo.xml`; `apt-cache policy` sui nomi di Depends/Recommends, `Recommends` corretto (A2), voce in DEVIATIONS | `desktop-file-validate` e `appstreamcli validate` senza errori; output `apt-cache policy` citato in DEVIATIONS | T-1.10a | R28 R64 R68 | ok | DO | `data/desktop/ data/icons/hicolor/*/apps/ data/metainfo/ docs/DEVIATIONS.md` | revert |
| T-2.2 | `packaging/debian/{control.in,postinst,prerm,copyright}`, `scripts/build_deb.sh` (staging §12.2, versione da `pyproject.toml`, Maintainer da `WIMM_MAINTAINER` o `git config`, errore se assenti, `Installed-Size`, `dpkg-deb --build --root-owner-group`) | `make deb`; `dpkg-deb --info` mostra Depends di §12.1; `--contents` elenca i file di §12.2; build con `git config` vuoto e senza `WIMM_MAINTAINER` fallisce; `shellcheck` verde | T-2.1 | R28 R42 R64 | seq | DO | `packaging/ scripts/build_deb.sh Makefile` | revert |
| T-2.3 | `scripts/test_deb.sh`: container `ubuntu:24.04` (nome `wimm-test-deb`, `--rm`), `apt install ./dist/*.deb`, file presenti, `wimm --version`, `lintian` installato e eseguito nel container (A7), `apt remove` senza residui di sistema | lo script esce 0 e stampa la versione; lintian senza errori (warning riportati); dopo `apt remove` nessun file in `/usr/lib/python3/dist-packages/wimm` | T-2.2 | R64 | seq | DO | `scripts/test_deb.sh` | revert; `docker rm -f wimm-test-deb` se resta |
| T-2.4 | README per utente finale: installazione, primo avvio (logout/login o `wimm --background`), file utente, disinstallazione, FAQ (browser non misurabile, VS Code Q-2, SSH Q-12) | M-7; lettura a contesto pulito (`reader-test`) | T-2.3 | R67 | ok | DW | `README.md` | revert |

Fine Fase 2: M-5, M-6 (installazione sull'host e logout/login).

## Fase 3: azioni su processi e container

| Id | Descrizione | verify | dip | R | par | agent | SCOPE | rollback |
|---|---|---|---|---|---|---|---|---|
| T-3.2a | `core/planning.py`: `plan_action` per singolo bersaglio, impronte §8.2 (processo pid+create_time+uid+hash cmdline, container id+status, compose nome+insieme id), `plan_id` `secrets.token_urlsafe(16)`, scadenza 120 s, `confirm_phrase` per `danger` | test: piano su volume ha `confirm_phrase` = nome; piano su entità protected solleva `ProtectedTarget` | T-3.1b | R17 R61 | contratto | TG | `src/wimm/core/planning.py tests/core/test_planning.py` | revert |
| T-3.2b | `group_stop` (processi poi container), `stop_all_idle_safe` (solo idle e safe), `excluded_ids` (Q-5), rischio aggregato e stima di recupero | test: 3 gruppi (idle safe, idle caution, active safe) -> solo il primo; esclusione toglie lo step e ricalcola la stima | T-3.2a | R15 R16 | seq | TG | `src/wimm/core/planning.py tests/core/test_planning.py` | revert |
| T-3.3a | `service/executor.py` processi: `ProcessControl` `Protocol`, rivalidazione (create_time, uid, protezione, non wimm né antenato), `TargetChanged`, "già fatto" | test con fake: piano a mano su processo protetto e su uid diverso -> `ProtectedTarget`, con caso positivo appaiato che termina un processo non protetto; PID riusato -> `TargetChanged` | T-3.2a | R36 R50 R61 | contratto | SB | `src/wimm/service/executor.py src/wimm/service/controls.py tests/service/test_executor.py` | revert |
| T-3.3b | Terminate: albero `children(recursive=True)`, SIGTERM figli poi radice, `wait_procs(timeout)`, esito `not_responding`, nessun SIGKILL automatico; integrazione | fake registra ordine figli->radice e zero SIGKILL; integrazione: `http.server` creato dal test terminato via piano | T-3.3a | R12 | seq | SB | `src/wimm/service/executor.py tests/service/ tests/integration/test_terminate.py` | revert |
| T-3.4 | Executor container: `DockerControl` `Protocol`, `stop(timeout=10)`, `remove(v=False)` solo se fermo, stop in parallelo | integrazione: `alpine sleep` con `wimm.test=1` fermato e rimosso; remove su container in esecuzione rifiutato | T-3.3a | R13 | seq | SB | `src/wimm/service/{executor,controls}.py tests/integration/test_containers.py` | revert; `docker rm -f $(docker ps -aq -f label=wimm.test=1)` |
| T-3.5 | `AppService.plan`/`execute`: registro piani, scadenza, `ConfirmationMismatch`, esecuzione nel worker, segnale `action-finished` con esito per step, delta MemAvailable/disco dopo 3 s, campionamento immediato, piano eliminato dopo l'uso | test servizio con executor finto: esito sul main loop; secondo `execute` stesso id -> `PlanNotFound`; frase sbagliata -> `ConfirmationMismatch` | T-3.3b T-3.4 | R15 R17 R18 R49 | seq | SB | `src/wimm/service/app_service.py tests/service/test_app_service.py` | revert |
| T-3.6 | Compose `stop`/`down`/`down -v` via `subprocess.run` a lista, `timeout=120`; chiude la premessa §7.3 su progetto in tmpdir con 2 `alpine` e label; se `down` senza file non funziona, ripiego SDK per label + `networks.prune` | integrazione: progetto creato, fermato e rimosso; voce in DEVIATIONS con l'output osservato | T-3.4 | R13 R68 | seq | SB | `src/wimm/service/{executor,compose}.py tests/integration/test_compose.py docs/DEVIATIONS.md` | revert; `docker compose -p wimm-test-* down -v` |
| T-3.7a | `ui/dialogs/confirm.py`: 3 livelli (safe suggested, caution con avviso e destructive, danger con `Adw.EntryRow` che abilita solo a testo identico), dialogo multiplo con toggle (Q-5) | test `ui`: danger disabilitato con testo diverso, abilitato con nome esatto; M-8 | T-3.5 T-1.9c | R17 R49 | seq | FD | `src/wimm/ui/dialogs/confirm.py src/wimm/ui/pages/overview.py tests/ui/` | revert |
| T-3.7b | Toast con esito e "Dettagli", stato loading durante l'esecuzione, piano scaduto -> "La situazione è cambiata, ricalcolo…", "Forza chiusura" come nuovo piano su processo che ignora SIGTERM | test `ui` con servizio finto; M-8 su processo di test che ignora SIGTERM: offre Forza chiusura | T-3.7a | R12 R18 R48 | seq | FD | `src/wimm/ui/ tests/ui/` | revert |
| T-3.8a | `app_close`: SIGTERM al solo processo principale del gruppo, attesa, esito | test con fake: segnale solo alla radice, figli non toccati | T-3.3b | R12 | seq | SB | `src/wimm/service/executor.py tests/service/test_executor.py` | revert |
| T-3.8b | Verifica premessa Firefox (Q-9): istanza con profilo di test, 2 schede, SIGTERM, rilancio, lettura sessionstore; conseguenza in `core/text.py` allineata, se persa rischio `danger` con frase "Firefox" (R8 §18). Esplorativo: non delegato | voce in DEVIATIONS con l'osservazione; test di `assess_risk` aggiornato all'esito | T-3.8a | R59 R68 | seq | IH | `src/wimm/core/{risk,text}.py tests/core/test_risk.py docs/DEVIATIONS.md` | revert |

Fine Fase 3: reinstallazione (M-5), M-8.

## Fase 4: notifiche, silenzi, preferenze

| Id | Descrizione | verify | dip | R | par | agent | SCOPE | rollback |
|---|---|---|---|---|---|---|---|---|
| T-4.1 | `core/notify_rules.py`: `evaluate_notifications` (idle con episodio `group_id+since`, pressione a `pressure_critical_pct` (Q-10) con top 3 e cooldown 1 h per tipo, limite 3/60 min con aggregazione, categorie, ignorati, silenziati) | test: stesso episodio 2 cicli -> 1 notifica; 5 gruppi idle -> 3 + 1 aggregata "2 gruppi inattivi"; AI_CLI idle -> nessuna | T-1.7b | R21 R22 R24 R51 | ok | TG | `src/wimm/core/notify_rules.py tests/core/test_notify_rules.py` | revert |
| T-4.2a | `service/notifier.py`: `Gio.Notification`, id `idle-<group>`/`pressure-ram`/`pressure-disk`, azioni `app.open-group` e `app.snooze-group` (parametro `s`) | test: le azioni registrate sono solo quelle due; notifica con stesso id sostituisce | T-4.1 | R23 | seq | SB | `src/wimm/service/notifier.py tests/service/test_notifier.py` | revert |
| T-4.2b | Azioni applicazione in `app.py`: `open-group` mostra la finestra sul gruppo, `snooze-group` silenzia 24 h; collegamento sampler -> notify_rules -> notifier | M-10 con `notify_after_s=60` e server di test | T-4.2a T-1.9c | R23 R51 | seq | FD | `src/wimm/app.py src/wimm/ui/window.py tests/ui/` | revert |
| T-4.3a | `service/state_store.py`: `state.json` atomico (tmp + `os.replace`) ogni 5 min e all'uscita; `last_active_at` per identità, silenzi, ignorati, episodi notificati | test: file troncato -> stato vuoto con WARNING e app viva; riavvio simulato conserva `since`; M-11 | T-1.7b | R11 R41 R51 | ok | SB | `src/wimm/service/state_store.py tests/service/test_state_store.py` | revert |
| T-4.3b | `AppService.snooze/set_ignored/snooze_all`, ignorati fuori da "recuperabile ora" e notifiche, pulsanti "Silenzia"/"Ignora" nelle righe e "Silenzia 1 h" in menu e tray (`snooze_all` assorbe `AppService.mute_notifications` di T-1.10b, uno stato solo); gli snooze per gruppo di `NotificationCoordinator` (T-4.2b) passano nello stato condiviso e nello snapshot, così finestra e notifiche vedono lo stesso silenzio | test servizio: gruppo ignorato non conta nel recuperabile; `snooze_all(3600)` sopprime tutte le notifiche | T-4.3a T-4.2b | R19 | seq | FD | `src/wimm/service/app_service.py src/wimm/ui/ src/wimm/tray/ tests/` | revert |
| T-4.4a | `config.py`: `parse_config` (tipi, intervalli §11, chiavi sconosciute WARNING, default per campo invalido), `update_config` con errori per campo, salvataggio JSON | test: `sample_interval_s=5` -> errore sul campo e default; chiave ignota -> WARNING; valore valido salvato e riletto | T-1.8b | R30 | ok | TG | `src/wimm/config.py src/wimm/service/app_service.py tests/test_config.py` | revert |
| T-4.4b | `ui/dialogs/preferences.py` (`Adw.PreferencesDialog`, campi RF-50, errore sul campo) | M-12; test `ui`: errore mostrato sul campo | T-4.4a | R30 | seq | FD | `src/wimm/ui/dialogs/preferences.py tests/ui/` | revert |

Fine Fase 4: reinstallazione (M-5), M-10, M-11, M-12.

## Fase 5: disco

| Id | Descrizione | verify | dip | R | par | agent | SCOPE | rollback |
|---|---|---|---|---|---|---|---|---|
| T-5.1a | `core/disk_rules.py`: immagini in uso / dangling / locali, volumi orfani, cartelle oltre età, ordinamento e cap 200 con contatore | test su output `df` di fixture: classificazione per ogni tipo | T-3.1b | R6 | ok | TG | `src/wimm/core/disk_rules.py tests/core/test_disk_rules.py tests/fixtures/docker_df*` | revert |
| T-5.1b | `collectors/disk_report.py` parte Docker: `client.api.df()` -> `DiskReport` | esecuzione reale coerente con `docker system df -v` (sola lettura) | T-5.1a | R6 R44 R52 | seq | SB | `src/wimm/collectors/disk_report.py tests/collectors/test_disk_report.py` | revert |
| T-5.2a | Calcolo dimensioni §7.6.1 (`st_blocks*512`, inode visti, no symlink, cessione GIL, pausa ogni 10.000) e cache `disk-cache.json` per mtime | test su tmpdir con symlink, hard link, cartelle annidate: dimensione attesa esatta; seconda chiamata usa la cache | T-0.2a | R6 | ok | SB | `src/wimm/collectors/dirsize.py tests/collectors/test_dirsize.py` | revert |
| T-5.2b | `collectors/caches.py` (uv, npm, pip, cestino, miniature) e `collectors/devdirs.py` (radici, profondità, nascoste tranne `.venv`, età su primo livello e `src/`) | test su HOME in tmpdir; scansione reale delle radici di default < 60 s la prima volta e < 5 s la seconda | T-5.2a | R6 | seq | SB | `src/wimm/collectors/{caches,devdirs}.py tests/collectors/` | revert |
| T-5.2c | Worker disco in `service/` (avvio +2 min, ogni 6 h, `rescan_disk`), `disk_report()`, segnale `disk-report-updated`, `GetDiskReport` sull'Inspector, `reclaimable_now.disk` (Q-6) | test servizio: `rescan_disk` emette il segnale; `gdbus ... GetDiskReport` JSON valido | T-5.1b T-5.2b | R63 | seq | SB | `src/wimm/service/{app_service,disk_scanner,inspector_dbus}.py tests/service/` | revert |
| T-5.3a | Planner per azioni disco (impronte cartella realpath+ino+dev, immagine id, volume nome) | test: piano devdir con impronta; volume -> danger con frase | T-3.2b T-5.1a | R14 R61 | seq | TG | `src/wimm/core/planning.py tests/core/test_planning.py` | revert |
| T-5.3b | Executor Docker disco: `images.remove`, prune dangling/unused, `prune_builds`, prune container fermi, `volumes.get().remove()` con rivalidazione (immagine non usata, RefCount 0) | fake per prune e build cache (Q-8); integrazione: immagine `alpine` ritaggata `wimm-test:<uuid>` rimossa; volume `wimm-test-<uuid>` rimosso | T-5.3a T-3.4 | R14 | seq | SB | `src/wimm/service/executor.py tests/service/ tests/integration/test_disk_docker.py` | revert; `docker volume rm` / `docker rmi` dei soli nomi `wimm-test-*` |
| T-5.3c | Executor cartelle/cache/cestino: validazioni §8.2 (no symlink, dentro radice, nome esatto, stesso inode), `rmtree` con `onexc`, cache via `subprocess.run` a lista con timeout, cestino `files`+`info` | test con HOME in tmpdir: rifiuto path fuori radice, symlink, nome `node_module`; caso positivo cancella `node_modules` di test | T-5.3a | R14 R56 | seq | SB | `src/wimm/service/executor.py tests/service/test_executor_disk.py` | revert |
| T-5.4a | `ui/pages/disk.py`: sezioni Docker, Cache, Cartelle, Cestino; ultima scansione, "Scansiona ora" con spinner; stati §10.3 | test `ui` con report fixture da 10.000 cartelle: 200 righe + contatore | T-5.2c | R6 | seq | FD | `src/wimm/ui/pages/disk.py tests/ui/` | revert |
| T-5.4b | Azioni dalla vista Disco tramite dialoghi di T-3.7a | click-through su ogni tipo di riga con bersagli di test; M-13 per la build cache reale | T-5.4a T-5.3b T-5.3c | R14 R52 | seq | FD | `src/wimm/ui/pages/disk.py tests/ui/` | revert |
| T-5.5a | `collectors/foreground.py`: X11 (`XDG_SESSION_TYPE=x11`) `_NET_ACTIVE_WINDOW`/`_NET_WM_PID` via `xprop` a lista con timeout; disattivato su Wayland o con `foreground_tracking=false` | test con `subprocess` finto; con `XDG_SESSION_TYPE=wayland` restituisce "disattivato" | T-1.8a | R46 | ok | SB | `src/wimm/collectors/foreground.py tests/collectors/test_foreground.py` | revert |
| T-5.5b | Attività per BROWSER/DESKTOP_APP/TERMINAL dal primo piano in `history`/`activity`, wiring nel sampler | test: app mai in primo piano per la finestra -> idle; in primo piano -> active; M-14 | T-5.5a T-1.7b | R46 | seq | TG | `src/wimm/core/activity.py src/wimm/service/{history,sampler}.py tests/` | revert |

Fine Fase 5: reinstallazione (M-5), M-13, M-14.

## Fase 6: hardening

| Id | Descrizione | verify | dip | R | par | agent | SCOPE | rollback |
|---|---|---|---|---|---|---|---|---|
| T-6.1 | Security baseline sull'intero repo: `security-reviewer` (subprocess, path, D-Bus, log), RNF-05 grep, review dei test contro R56 | report senza P0/P1 aperti; grep `sudo\|pkexec\|setcap\|shell=True` vuoto con caso positivo su file di prova | T-5.5b | R35 R37 R56 | ok | SR | read-only; fix nei moduli segnalati con task dedicato | revert dei fix |
| T-6.2 | README rifinito (installazione, uso, FAQ, disinstallazione, screenshot) | `reader-test` a contesto pulito; M-7 | T-6.1 | R67 | ok | DW | `README.md docs/` | revert |
| T-6.3 | ADR in `docs/adr/`: processo unico + SNI via Gio, Python di sistema e moduli apt, rischio per coppia entità-azione, Inspector D-Bus in sola lettura, JSON per config | 5 file `ADR-00N-*.md` con Context/Decision/Consequences/Alternatives | T-6.1 | R67 | ok | DW | `docs/adr/` | revert |
| T-6.4 | Verifica da clone pulito: `git clone` in tmpdir, `make setup && make lint && make test && make test-all` | tutti verdi in tmpdir; differenze rispetto al checkout annotate | T-6.1 | R54 R67 | ok | DO | read-only (tmpdir) | n/a |
| T-6.5 | Misure RNF-01/02/03/04 sull'installato (pidstat, ps rss dopo 1 h, log durata ciclo) e scrittura dei numeri in `docs/REPORT_ATTIVITA.md` | numeri nel report con data e condizioni; M-15 | T-6.4 | R31 R32 R33 R34 R55 | seq | IH | `docs/REPORT_ATTIVITA.md` | revert |
| T-6.6 | Delivery Report: DoD §17 voce per voce con evidenza, M-1..M-16, premesse chiuse, deviazioni, `CHECKS:` | report consegnato; M-16 spuntata dall'utente | T-6.5 | R42 R54 R67 | seq | DW | `docs/DELIVERY_REPORT.md docs/REPORT_ATTIVITA.md` | revert |

## Lotti di delega (2-4 task per invocazione)

Ogni prompt delegato porta: `[DELEGATE-CODEX]`, gli id e le righe di questa tabella, le sezioni
della spec citate, le decisioni Q applicate, la riga `SCOPE:` (unione degli SCOPE dei task).

| Lotto | Agent | Task | Dopo |
|---|---|---|---|
| L0-1 | DO | T-0.1a, T-0.1b, T-0.3 | - |
| L0-2 | TG | T-0.2a, T-0.2b | L0-1 |
| CP-0 | utente | M-1 | L0-2 |
| L1-1 | SB | T-1.1a, T-1.2a, T-1.3, T-1.4c | CP-0 (parallelo a L1-2) |
| L1-2 | TG | T-1.1b, T-1.4a, T-1.4b | CP-0, Q-1 Q-3 Q-12 chiuse |
| L1-3 | SB | T-1.2b, T-1.5a, T-1.5b | L1-1 |
| L1-4 | TG | T-1.6a, T-1.6b, T-1.7a, T-1.7b | L1-2, L1-3 |
| L1-5 | TG | T-3.1a, T-3.1b | L1-2 (Q-4) |
| L1-6 | SB | T-1.8a, T-1.8b, T-1.8c | L1-4, L1-5 |
| L1-7 | FD | T-1.9a, T-1.9b | L1-6 |
| L1-8 | FD | T-1.9c, T-1.9d | L1-7 |
| L1-9 | FD | T-1.10a, T-1.10b, T-1.11 | L1-8 |
| L2-1 | DO | T-2.1, T-2.2, T-2.3 | L1-9 |
| L2-2 | DW | T-2.4 | L2-1 |
| L3-1 | TG | T-3.2a, T-3.2b | L2-1 (Q-5) |
| L3-2 | SB | T-3.3a, T-3.3b, T-3.4 | L3-1 |
| L3-3 | SB | T-3.5, T-3.6, T-3.8a | L3-2 |
| L3-4 | FD | T-3.7a, T-3.7b | L3-3 |
| L3-5 | IH | T-3.8b | L3-3 (Q-9) |
| L4-1 | TG | T-4.1, T-4.4a | Fase 3 |
| L4-2 | SB | T-4.2a, T-4.3a | L4-1 |
| L4-3 | FD | T-4.2b, T-4.3b, T-4.4b | L4-2 |
| L5-1 | TG | T-5.1a, T-5.3a | Fase 4 |
| L5-2 | SB | T-5.1b, T-5.2a, T-5.2b, T-5.2c | L5-1 |
| L5-3 | SB | T-5.3b, T-5.3c | L5-2 |
| L5-4 | FD | T-5.4a, T-5.4b | L5-3 |
| L5-5 | SB | T-5.5a, T-5.5b (logica test-first) | Fase 4 (parallelo a L5-1) |
| L6-1 | SR, DW, DO, IH | T-6.1, poi T-6.2 T-6.3 T-6.4 in parallelo, poi T-6.5, T-6.6 | Fase 5 |

## Criteri aggiunti dalla review del piano

I rilievi S1-S7 e T1-T12 sono mappati sui task in `plan.md` § Rilievi degli specialisti integrati.
Il prompt di delega di ogni lotto riporta i criteri dei propri task, perché l'agent non legge il piano.

### Criteri aggiunti dalla review di T-1.7 (per T-1.8a)

- La CPU "processo più figli" di §5.4 si calcola come somma dei delta per PID presenti in
  entrambi i campioni, con identità `pid` + `create_time`, non dal cumulato aggregato. Un figlio
  che termina fra due campioni farebbe scendere il cumulato, il delta diventerebbe `None` e
  l'attività andrebbe persa.
- Le quadruple di un server sono quelle non-LISTEN sulle porte in LISTEN del processo **e dei
  suoi discendenti** (`non_listening_for_ports`). Se la scansione dei socket fallisce, il
  campione porta `connections=None`.
