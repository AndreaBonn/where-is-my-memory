# 001 product gaps: requisiti

Fonte: audit di prodotto F1-F17 (2026-10-18). Obiettivo: rendere where-is-my-memory utile a
qualsiasi sviluppatore Linux su Ubuntu 24.04, non solo all'autore. `assets/SPECIFICHE.md` resta
la fonte di verità: ogni requisito che la estende o la contraddice si registra in
`docs/DEVIATIONS.md` nel lotto che lo implementa. Gli id `R<n>` valgono solo dentro questa
cartella (le R1-R68 di `specs/where-is-my-memory/` sono un altro spazio di nomi).

Formato: `R<n> | F | requisito | Definition of Done (verificabile) | criterio di successo`.
I nomi dei test sono quelli da creare; il test si vede rosso prima del verde.

## Requisiti trasversali

- R40 | tutti | Politica di versione dello schema (Q4) | ogni lotto che cambia la forma di snapshot o report disco aggiorna `SCHEMA_VERSION` secondo Q4, `data/dbus/io.github.wimm.Inspector1.xml` e una voce in DEVIATIONS; `tests/test_serialize.py` fa il round-trip della forma nuova e rifiuta la vecchia (Q4=A) | `GetSnapshot` su un'istanza aggiornata restituisce `"schema": <nuovo>`
- R41 | tutti | Parità delle traduzioni | ogni stringa nuova sta in `_()`/`N_()` con msgid italiano e ha la traduzione in `po/en.po`; `make lint` (che esegue `scripts/check_i18n.py`) passa | zero msgid senza traduzione a fine lotto
- R42 | tutti | Floor di qualità | dopo ogni lotto `make lint` pulito, `make test` verde con un numero di test maggiore della baseline (2082), copertura `src/wimm/core` >= 90%, `tests/test_source_limits.py` verde (300/30/4) | il lotto si chiude con la riga `CHECKS:` e un commit atomico per task
- R43 | tutti | Nessuna azione distruttiva reale nei test, nessun root, nessuna azione automatica | ogni test di executor usa bersagli creati nel `tmp_path` o fake; nessun nuovo `sudo`/`pkexec`; nessun nuovo percorso che esegue un piano senza conferma | `grep -rn "sudo\|pkexec" src` vuoto; revisione `security-reviewer` sui lotti L1, L3, L6, L7, L10

## L1: pronta per chiunque (F1, F3, F7, F8)

- R1 | F1 | Radici di sviluppo rilevate in automatico | senza `devdirs_roots` salvato, la radice predefinita è l'elenco delle cartelle candidate esistenti (`~/code`, `~/projects`, `~/src`, `~/dev`, `~/git`, `~/workspace`, `~/Documents`, `~/Documenti` e la cartella documenti di `~/.config/user-dirs.dirs`) che contengono almeno una cartella `.git` entro 2 livelli; nessun percorso personale resta in `core/constants.py`. Esempio: HOME di test con `~/code/a/.git` e `~/Documents/foto/` → radici `(~/code,)`. Test `tests/core/test_dev_roots.py::test_detect_dev_roots_keeps_only_candidates_with_a_repo` | la ricerca legge al massimo 2 livelli per candidata, senza seguire symlink
- R2 | F1 | Radice mancante segnalata, non scartata | una radice salvata che non esiste più resta in configurazione, non invalida le altre ed è mostrata nella vista Disco e nelle Preferenze con "La cartella … non esiste"; nessuna radice trovata mostra lo stato vuoto con l'azione "Scegli una cartella". Test `tests/test_config.py::test_parse_config_keeps_a_missing_root_and_flags_it` (caso appaiato: radice esistente accettata senza avviso) | click-through: Preferenze con una radice cancellata mostra l'avviso
- R3 | F3 | Lingua predefinita inglese fuori dalle locali italiane | senza scelta salvata vince la prima voce supportata delle variabili di locale (`LANGUAGE` voce per voce, poi `LC_ALL`, `LC_MESSAGES`, `LANG`); se nessuna è `it*` o `en*` la lingua è l'inglese, `C` e `POSIX` compresi. Esempi: `LANG=de_DE.UTF-8` → en; `LANGUAGE=de:it` → it; `LANG=C` → en; `LANG=it_IT.UTF-8` → it. Test `tests/test_i18n.py::test_resolve_default_*` | la scelta salvata nelle Preferenze continua a prevalere
- R4 | F7 | Cartelle di dipendenze per più ecosistemi | il report disco trova `node_modules`, `.venv`, `venv` (solo con `pyvenv.cfg` dentro), `target` (solo con `Cargo.toml` o `pom.xml` accanto), `.gradle` e `build` (solo con `build.gradle`, `build.gradle.kts`, `settings.gradle` o `settings.gradle.kts` accanto), `.next` e `.nuxt` (solo con `package.json`), `.tox` (solo con `tox.ini`, `pyproject.toml` o `setup.cfg`), `vendor` (solo con `composer.json`); `vendor` di Go e `dist` non sono candidati. Le cartelle trovate non contano per l'età del progetto. Test `tests/core/test_devdir_rules.py` con una riga per nome e il caso falso positivo appaiato (`target` senza marker, `vendor` con solo `go.mod`) | prima scansione sulla home reale: durata registrata in `docs/PERF.md`, aumento <= 30% sulla baseline misurata nello stesso task
- R5 | F7 | L'executor rivaluta la regola del nome | al momento dell'esecuzione l'executor applica la stessa funzione pura di R4 sulla cartella padre reale: un `target` il cui `Cargo.toml` è sparito dopo il piano dà `ProtectedTarget` e la cartella resta intatta. Test `tests/service/test_executor_disk_fs.py::test_devdir_without_its_marker_is_refused` | nessun nome nuovo si cancella senza il suo marker
- R6 | F8 | Marker di progetto per Rust, Go, Java | `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, `build.gradle.kts` raggruppano i processi nel progetto; un solo elenco di marker (oggi duplicato fra `core/constants.py:95` e `collectors/project_roots.py:4`). Test `tests/collectors/test_project_roots.py::test_resolve_finds_each_marker` parametrico | `cargo run` in un crate senza `.git` finisce nel gruppo del crate

## L2: igiene di rilascio (F17, parte automatizzabile)

- R7 | F17 | Audit di sicurezza eseguibile | `make audit` esegue `bandit -r src` e `pip-audit` sulle dipendenze dichiarate (export di uv, non i pacchetti apt); esce 0 o ogni finding è triagiato in `docs/security/`; la CI lo esegue | `make audit` verde in locale e nel workflow
- R8 | F17 | Pagina di manuale | `wimm.1` installata in `/usr/share/man/man1/` dal `.deb`; `make test-deb` non riporta più `no-manual-page` di lintian | `man -l packaging/man/wimm.1` mostra opzioni e file utente
- R9 | F17 | Metainfo con homepage | `<url type="homepage">` e `bugtracker` con l'URL fornito dall'utente (Q8); `appstreamcli validate` senza errori | validazione nel test del pacchetto
- R10 | F17 | RNF-04 misurata | uno script misura il tempo dall'attivazione dell'app al primo frame della finestra su display virtuale; il numero è in `docs/PERF.md` con condizioni dichiarate; il cronometro sul display reale resta una verifica manuale | numero registrato, sotto 1 s o deviazione dichiarata
- R11 | F17 | Verifiche manuali aggiornate | `docs/DELIVERY_REPORT.md` elenca le M-* ancora aperte e quelle nuove dei lotti (Wayland, podman, radici esterne) con il comando da eseguire | l'utente le spunta; la CI remota parte al suo primo push

## L3: cache degli sviluppatori (F6, voci a basso rischio)

- R12 | F6 | Catalogo delle cache | oltre a uv, npm, pip, cestino e miniature il report misura: cargo registry e git, gradle caches, maven `~/.m2/repository`, go module cache e build cache, yarn, pnpm store, bun, conda pkgs, ms-playwright, JetBrains; i percorsi rispettano `XDG_CACHE_HOME` e le variabili dello strumento (`CARGO_HOME`, `GOMODCACHE`, `GOCACHE`, `GRADLE_USER_HOME`, `YARN_CACHE_FOLDER`, `BUN_INSTALL_CACHE_DIR`, `CONDA_PKGS_DIRS`, `PLAYWRIGHT_BROWSERS_PATH`); un percorso fuori dalla home reale si ignora con un log. Test `tests/core/test_cache_catalog.py::test_resolve_cache_paths_honours_xdg_and_tool_variables` | una cartella assente non produce voci
- R13 | F6 | Rischio per voce di cache | `CACHE_CLEAN` non è più statico: il rischio dipende dal tipo di cache (ADR-003, coppia entità/azione). SAFE: uv, npm, pip, cargo, gradle, go, yarn, pnpm, bun, conda, playwright; CAUTION: maven (gli artefatti di `mvn install` non si riscaricano), JetBrains (l'IDE reindicizza). "Libera spazio" e il recuperabile del riepilogo includono solo le voci SAFE. Test `tests/core/test_planning_disk_safe.py::test_disk_free_safe_skips_caution_caches` (caso appaiato: una voce SAFE entra nel piano) | nessuna voce CAUTION/DANGER in un piano "Libera spazio"
- R14 | F6 | Comando nativo dove esiste | go: `go clean -modcache` e `go clean -cache` con `GOMODCACHE`/`GOCACHE` puntati alla cartella del piano (i file della module cache sono in sola lettura: senza `go` l'azione non si offre); pnpm: `pnpm store prune` sullo store del piano; yarn: `yarn cache clean` con la cartella del piano; conda: `conda clean --all --yes`; cargo: nessun comando stabile, si svuotano solo `registry/cache`, `registry/src`, `git/db`, `git/checkouts`, mai `bin`. Ogni argv è verificato sulla documentazione corrente nel task (context7). Test `tests/service/test_executor_disk_fs.py::test_cache_argv_*` | nessun comando con `shell=True`, tutti con timeout
- R15 | F6 | Il tipo di cache si decide dal posto, non dal piano | l'executor riceve all'avvio la stessa tabella risolta di R12 e riconosce la cartella dal suo percorso reale; un piano con un percorso non in tabella dà `ProtectedTarget`; le variabili che deviano uno strumento vengono puntate alla cartella del piano. Test `tests/service/test_executor_disk_fs.py::test_cache_outside_the_table_is_refused` | stessa garanzia di oggi su 5 voci, estesa a 17

## L4: motori container e strumenti riconosciuti (F9, F10)

- R16 | F9 | Podman non contato due volte e non terminabile per pid | i processi in `libpod-*.scope` sono esclusi dalla vista processi quando il motore container li vede; senza API restano un gruppo protetto "Container Podman" senza azioni sui pid. Test `tests/core/test_categorize.py::test_libpod_scope_*` | nessuna azione `process_terminate` su un pid di un container podman
- R17 | F9 | Endpoint Docker dal contesto | l'endpoint segue `DOCKER_HOST`, poi `DOCKER_CONTEXT`, poi `currentContext` di `~/.docker/config.json` (con l'endpoint letto da `~/.docker/contexts/meta/<sha256 del nome>/meta.json`), poi il socket podman `$XDG_RUNTIME_DIR/podman/podman.sock` se Docker manca, poi il default. Test `tests/core/test_docker_endpoint.py` con una riga per regola | con il contesto `desktop-linux` i container di Docker Desktop compaiono
- R18 | F9 | Metriche senza cgroup locale | per Docker Desktop (container in VM) e podman rootless senza scope leggibile la memoria viene dalla stats API (`MetricsSource.STATS_API`), con la durata del ciclo dentro RNF-03 | `tests/collectors/test_cgroups.py::test_locate_libpod_scope` e test del ripiego
- R19 | F10 | Strumenti riconosciuti (Q3) | qemu/KVM utente, VirtualBox, emulatore Android, daemon Gradle e Kotlin, language server (rust-analyzer, gopls, pyright, pylsp, typescript-language-server, jdtls, clangd), kind e minikube hanno un'etichetta e un motivo leggibili; rischio di terminazione: daemon Gradle/Kotlin SAFE, emulatore CAUTION, VM DANGER (stato del guest). Test `tests/core/test_tool_labels.py` con una cmdline reale per voce | i processi di libvirt di sistema restano SYSTEM

## L5: memoria non attribuita e pressione (F11, F12)

- R20 | F11 | Voci nuove nel dettaglio della RAM | il dettaglio aggiunge "Memoria condivisa e tmpfs" (min fra `Shmem` e i byte usati dei tmpfs leggibili), "Kernel non recuperabile" (`SUnreclaim` + `KernelStack` + `PageTables`), "zram" (`mem_used_total` di `/sys/block/zram*/mm_stat`), "zswap" (`Zswap` di meminfo); i campi assenti valgono zero; "Non attribuita" non è mai negativa e la somma delle voci è uguale a `MemTotal - MemFree`. Test `tests/core/test_memory.py::test_memory_summary_new_voices_sum_to_used` | "Non attribuita" scende sul sistema reale (numeri prima e dopo nel report)
- R21 | F11 | Memoria video a parte | la VRAM di NVIDIA (`nvidia-smi` con timeout, un campione ogni 5 cicli) e AMD (`mem_info_vram_used` in sysfs) compare come riga separata, mai sommata alla RAM; senza GPU dedicata la riga non c'è | `pidstat` conferma RNF-01 con `nvidia-smi` presente
- R22 | F12 | PSI nella pressione | lo stato di pressione è il peggiore fra la soglia di RAM/disco attuale e PSI (`/proc/pressure/memory`: `some avg60` >= 10 → warning, `full avg60` >= 5 → critical, costanti nominate); senza PSI resta la regola attuale. Test `tests/core/test_memory.py::test_pressure_uses_psi_when_present` (caso appaiato: PSI assente) | notifica di pressione con RAM libera al 30% ma PSI alto
- R23 | F12 | Notifica di OOM kill | se `oom_kill` di `memory.events` di `user@<uid>.service` cresce fra due cicli parte una notifica con i 3 gruppi più grandi, fuori dal limite orario come le notifiche di pressione (precedente in DEVIATIONS); al primo ciclo il contatore si legge senza notificare. Test `tests/core/test_notify_rules.py::test_oom_kill_increase_notifies_once` | un OOM provocato in un cgroup di test (`systemd-run --user -p MemoryMax=`) genera la notifica (verifica manuale M-*)

## L6: modelli ML e Android (F6, voci costose)

- R24 | F6 | Voci da riscaricare a caro prezzo (Q2) | huggingface hub (`HF_HUB_CACHE`, `HF_HOME/hub`, `XDG_CACHE_HOME/huggingface/hub`), modelli ollama (`OLLAMA_MODELS`, `~/.ollama/models`), Android AVD (`~/.android/avd`) e SDK (`ANDROID_HOME`, `ANDROID_SDK_ROOT`, `~/Android/Sdk`) sono misurati con il rischio deciso in Q2 (default: HF e SDK CAUTION, ollama e AVD DANGER); mai in "Libera spazio"; ollama in esecuzione blocca la pulizia dei suoi modelli. Test `tests/core/test_planning_disk_safe.py::test_disk_free_safe_never_includes_models` | la conferma DANGER chiede la digitazione come per i volumi

## L7: radici fuori dalla home (F2)

- R26 | F2 | Radici su un secondo disco | una radice è ammessa se è una directory reale (non symlink), di proprietà dell'utente, non è un percorso di sistema (`/`, `/usr`, `/etc`, `/var`, `/boot`, `/proc`, `/sys`, `/dev`, `/run`, `/opt`, `/snap`, `/root`, `/srv`, `/tmp`), non è un antenato della home e non è la home di un altro utente; esempio: `/mnt/data/code` di proprietà dell'utente → ammessa, `/mnt/data` di root → rifiutata. Decisione in ADR-007. Test `tests/core/test_root_policy.py` | messaggio di errore per ciascun motivo di rifiuto
- R27 | F2 | Stessa regola all'esecuzione | l'executor applica lo stesso predicato puro alla radice reale prima di cancellare, rileggendo `st_uid`; la rimozione non attraversa mount (safe_tree invariato). Test `tests/service/test_executor_disk_fs.py::test_devdir_under_a_root_no_longer_owned_is_refused` | nessun percorso di sistema raggiungibile anche con un piano costruito a mano (RNF-06)

## L8: sessioni remote e crescita (F5, F13)

- R28 | F5 | Sessioni SSH (Q1) | con la scelta di default di Q1 (opzione `remote_sessions_actionable`, spenta): spenta, i processi in `session-*.scope` restano SYSTEM come oggi (Q-12); accesa, i processi dell'utente in quelle scope seguono le regole normali, mentre `sshd`, la shell di login e `tmux` server restano protetti. Test `tests/core/test_categorize.py::test_remote_session_*` (spento e acceso) | lo switch è nelle Preferenze
- R29 | F13 | Indicatore di crescita | ogni gruppo ha un trend calcolato su un punto ogni 10 minuti per 3 ore in RAM (18 punti); "in crescita" se l'aumento è >= 256 MiB e >= 20% nella finestra; la riga del gruppo mostra "+620 MB in 2 h". Test `tests/core/test_growth.py` con serie crescente, piatta e a dente di sega | nessun grafico, nessuna persistenza su disco (N3)
- R30 | F13 | RNF-01 mantenuta | dopo L1, L3, L5 e L8 `pidstat -p <pid> 60 10` a regime resta sotto 1% di un core; la memoria della storia è limitata (1000 gruppi → meno di 2 MB). Righe in `docs/PERF.md` | misura prima e dopo con le stesse condizioni

## L9: stato senza finestra (F15)

- R31 | F15 | `wimm status [--json]` | senza display (`env -u DISPLAY -u WAYLAND_DISPLAY`) stampa lo snapshot (JSON di `serialize.py` con `--json`, riepilogo testuale nella lingua scelta senza) ed esce 0; con un'istanza attiva usa `GetSnapshot` via D-Bus (Q6), altrimenti un campionamento singolo con attività `unknown`; esce 3 se il campionamento fallisce. Test `tests/integration/test_status_cli.py` sotto `dbus-run-session` | `wimm status --json | python3 -m json.tool` funziona in SSH
- R32 | F15 | Nessun GTK caricato | `wimm status` non importa `gi.repository.Gtk` né `Adw`. Test `tests/test_cli.py::test_status_does_not_import_gtk` (caso appaiato: `create_main_window` lo importa) | avvio sotto 2 s senza istanza attiva

## L10: comando di riavvio dei processi (F14)

- R33 | F14 | Memoria dei processi fermati | per gli ultimi 8 piani si tiene in RAM argv, cwd ed etichetta dei processi terminati con esito DONE; nulla su disco, nulla nei log a INFO (RNF-08). Test `tests/service/test_restart_memory.py::test_records_stopped_process_commands` e `caplog` senza argv | dopo un riavvio di wimm la lista è vuota
- R34 | F14 | Copia o riavvia (Q7) | il toast "Processo fermato" offre "Copia comando di riavvio" (`cd <cwd> && <shlex.join(argv)>`) con l'avviso che il comando può contenere segreti; con Q7=B anche "Riavvia", azione CAUTION eseguita come lista argv con cwd, sessione nuova, senza shell. Test click-through del toast | il comando copiato riavvia `python3 -m http.server 8765` nella cartella giusta

## L11: Wayland (F4)

- R36 | F4 | Scelta in ADR-006 | l'architect propone, l'utente accetta: estensione GNOME Shell che espone il pid della finestra in primo piano via D-Bus, `org.gnome.Mutter.IdleMonitor` (solo inattività di sessione), o altro | ADR-006 con stato Accettata
- R37 | F4 | Segnale di attività su Wayland | secondo ADR-006: su sessione Wayland GNOME 46 `EntitySample.foreground` non è più sempre None (estensione) o l'inattività di sessione entra nel motivo (IdleMonitor); senza il componente l'app funziona come oggi. Test di collector con proxy D-Bus finto | verifica manuale M-* su sessione Wayland

## L12: distribuzione (F16)

- R38 | F16 | Formati oltre il .deb (Q5) | per ogni formato scelto: file di build nel repo, build e installazione provate in un container della distribuzione (come `make test-deb`), dipendenze di sistema mappate (psutil, docker, gi, GTK4, libadwaita) | `make test-<formato>` verde
- R39 | F16 | GNOME senza AppIndicator | il comportamento attuale (banner + finestra aperta, `tests/test_app_tray_missing.py`) resta; il banner indica il pacchetto o il link dell'estensione per la distribuzione rilevata da `/etc/os-release` | click-through del banner

## Sicurezza (dai rilievi sul piano)

- R44 | F2 | Radici esterne sicure (S3) | rifiutate radici di rete/FUSE/autofs, `ro`, di sistema, antenate della home o con 2 componenti o meno, sia in config sia nell'executor | test per ogni caso di rifiuto più `/mnt/data/code` ammessa
- R45 | F6 | Cache ridirette sicure (S5) | una cache indicata da variabile d'ambiente che coincide con la home, con una radice o con un antenato non si pulisce mai; senza sentinel solo misura | test con `GOCACHE=$HOME` e `HF_HOME=<radice>`
- R46 | F9 | Solo motori locali (S8) | endpoint ammessi solo `unix://` verso socket dell'utente o di sistema noti; `tcp://` e `ssh://` rifiutati con messaggio | test sui meta di contesto
- R47 | F15 | Output CLI redatto (S12) | `wimm status` (testo e JSON) non contiene segreti della cmdline né caratteri di controllo | test con `--token abc`
