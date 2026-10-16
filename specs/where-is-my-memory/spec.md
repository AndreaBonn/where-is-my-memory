# where-is-my-memory: requisiti tracciabili

Fonte unica: `assets/SPECIFICHE.md` v1.0 (2026-10-16). Questo file non aggiunge requisiti: assegna
un id `R<n>` a ogni RF, RNF, voce di DoD (§17) e vincolo trasversale, con la condizione che lo
verifica. In caso di divergenza prevale la specifica. Gli id dei task sono quelli `T-x.y` della §16
(sotto-task `T-x.ya`, mai rinumerati); i task `T-0.3` e `T-6.x` sono aggiunte decise dall'utente.

Legenda verifica: `auto` = test pytest o comando; `manuale-utente` = richiede un'azione o
un'osservazione dell'utente (vedi `plan.md` § Checklist runtime manuale).

## Visione (RF-01..RF-08)

| R | Fonte | Requisito verificabile | Verifica | Task |
|---|---|---|---|---|
| R1 | RF-01 | Il riepilogo mostra RAM usata/totale, disponibile, swap, disco `/` usato/totale e "recuperabile ora" RAM e disco, calcolati sui soli gruppi `idle` con azione `safe` non ignorati | auto: test viewmodel su snapshot fixture con 1 gruppo idle safe da 1,1 GB e 1 active: totale = 1,1 GB | T-1.1b, T-1.9a |
| R2 | RF-02 | La scomposizione RAM ha le voci per categoria, `kernel_cache` e `unattributed` (>= 0, mai nascosta né ripartita) | auto: test `core/memory` con meminfo fixture; `unattributed` = MemTotal - MemFree - somma voci | T-1.1b |
| R3 | RF-03 | Gruppi ordinati per RAM recuperabile decrescente; filtri tutti / inattivi / categoria / rischio | auto: test viewmodel sui filtri; manuale-utente click sui filtri | T-1.9a, T-1.9c |
| R4 | RF-04 | Ogni riga gruppo ha nome, categoria, stato, durata, motivo, PSS e USS recuperabile, disco se rilevante, porte, rischio azione principale | auto: test viewmodel riga per riga | T-1.9a, T-1.9c |
| R5 | RF-05 | Il gruppo espanso mostra i membri con PID, comando, cwd, porte, utente, avvio, memoria; per i container immagine, stato, volumi, porte | auto: test smoke UI (marker `ui`) | T-1.9c |
| R6 | RF-06 | Vista Disco con immagini (in uso/inutilizzate/dangling/locali), container fermi, volumi (montati/orfani), build cache, cache uv/npm/pip, cestino, `node_modules`/`.venv` più vecchi di N giorni | auto: test `disk_rules` + smoke UI; manuale-utente confronto con `docker system df -v` | T-5.1a, T-5.1b, T-5.2b, T-5.4a |
| R7 | RF-07 | Vista Sistema in sola lettura, raggruppata (sessione GNOME, audio, servizi, altri utenti) con motivo di protezione | auto: test viewmodel; smoke UI senza pulsanti azione | T-1.9d |
| R8 | RF-08 | Ogni gruppo ha una spiegazione di categoria e classe costruita dai dati ("lanciato dal terminale nella cartella X, porta 8000") | auto: test `core/text` | T-1.6b, T-1.7b |

## Attività (RF-10..RF-12)

| R | Fonte | Requisito verificabile | Verifica | Task |
|---|---|---|---|---|
| R9 | RF-10 | Gruppo `idle` se nessun membro ha campioni attivi nella finestra (default 1800 s), criteri §5.4 | auto: test `core/activity` per tipo di entità | T-1.7a, T-1.7b |
| R10 | RF-11 | Entità non misurabili e storia corta danno `unknown` con motivo distinto ("in osservazione da 4 minuti" / "non misurabile per i browser") | auto: test `core/activity` | T-1.7b |
| R11 | RF-12 | `last_active_at` persistito per identità (pid+create_time, container id): dopo riavvio lo stato è subito `idle` con lo stesso `since` | auto: test persistenza; manuale-utente riavvio app | T-1.7b, T-4.3a |

## Azioni (RF-20..RF-28)

| R | Fonte | Requisito verificabile | Verifica | Task |
|---|---|---|---|---|
| R12 | RF-20 | Termina = SIGTERM a figli poi radice, attesa `terminate_timeout_s`; SIGKILL solo come nuovo piano offerto se il processo è vivo | auto: fake `ProcessControl` registra l'ordine; nessun SIGKILL nel percorso terminate | T-3.3a, T-3.3b, T-3.7b |
| R13 | RF-21 | Container: stop, remove (solo fermo, `v=False`), stop progetto, `down`, `down -v` (`danger`) | auto: integrazione su container `wimm.test=1` | T-3.4, T-3.6 |
| R14 | RF-22 | Azioni disco: immagine, dangling, inutilizzate, build cache, container fermi, volume orfano, cache uv/npm/pip, cestino, devdir | auto: fake + HOME temporanea; manuale-utente prune reali | T-5.3a, T-5.3b, T-5.3c |
| R15 | RF-23 | "Ferma tutto il gruppo" compone in un piano: prima processi, poi container in parallelo; successo parziale con esito per step | auto: test planning + executor con fake | T-3.2b, T-3.5 |
| R16 | RF-24 | "Ferma tutti gli inattivi sicuri" include solo gruppi `idle` con azioni `safe` | auto: test planning con un gruppo caution e uno active esclusi | T-3.2b |
| R17 | RF-25 | Nessuna esecuzione senza piano mostrato; conferme crescono col rischio (§8.3) | auto: `execute` senza `plan_id` valido solleva `PlanNotFound`; manuale-utente dialoghi | T-3.5, T-3.7a |
| R18 | RF-26 | Esito per bersaglio e liberato misurato (delta MemAvailable / spazio libero dopo 3 s) | auto: test servizio con collector finto; manuale-utente toast | T-3.5, T-3.7b |
| R19 | RF-27 | Ignora (fuori da notifiche e recuperabile) e silenzia 1 h / 24 h / 7 g | auto: test `notify_rules` + viewmodel | T-4.3b |
| R20 | RF-28 | Su entità `protected` il pulsante azione non esiste (assente, non disabilitato) e la riga dice perché | auto: smoke UI conta i pulsanti di una riga protetta = 0 e di una actionable = 1 | T-1.9c, T-1.9d |

## Notifiche (RF-30..RF-33)

| R | Fonte | Requisito verificabile | Verifica | Task |
|---|---|---|---|---|
| R21 | RF-30 | Notifica idle se gruppo actionable idle >= `notify_after_s` e recuperabile >= `notify_min_bytes`, categoria abilitata | auto: test `notify_rules` | T-4.1 |
| R22 | RF-31 | Notifica di pressione (RAM disponibile o disco libero sotto soglia) con i 3 gruppi che liberano di più, max 1/h per tipo | auto: test `notify_rules` | T-4.1 |
| R23 | RF-32 | Azioni notifica solo "Apri" e "Silenzia 24 h", nessuna azione su risorse | auto: test che le azioni registrate sono `app.open-group` e `app.snooze-group`; manuale-utente click | T-4.2a, T-4.2b |
| R24 | RF-33 | Una notifica per episodio (`group_id+since`), max 3 in 60 min, eccesso aggregato | auto: test `notify_rules` | T-4.1 |

## Barra e avvio (RF-40..RF-44)

| R | Fonte | Requisito verificabile | Verifica | Task |
|---|---|---|---|---|
| R25 | RF-40 | Etichetta "4,2 GB inattivi" sotto l'icona, assente sotto 100 MB; `XAyatanaLabelGuide` = "88,8 GB inattivi" | auto: test `menu_model`/label + D-Bus Get della proprietà | T-1.10a, T-1.10b |
| R26 | RF-41 | Icona normale / avviso (< `pressure_warning_pct`) / critico (< `pressure_critical_pct`) | auto: test puro della scelta icona | T-1.10b |
| R27 | RF-42 | Clic sinistro apre o porta in primo piano; clic destro: riepilogo, fino a 5 inattivi, "Silenzia 1 h", "Esci" | auto: test `build_menu`; manuale-utente clic | T-1.10a, T-1.10b |
| R28 | RF-43 | Autostart al login con icona visibile e finestra nascosta | manuale-utente logout/login | T-2.1, T-2.2 |
| R29 | RF-44 | Chiudere la finestra la nasconde e il campionamento continua; solo "Esci" termina | auto: test UI `close-request` restituisce True; manuale-utente | T-1.9b |

## Impostazioni (RF-50)

| R | Fonte | Requisito verificabile | Verifica | Task |
|---|---|---|---|---|
| R30 | RF-50 | Preferenze §11 modificabili; valore fuori intervallo rifiutato con messaggio sul campo, valido applicato al ciclo successivo | auto: test `parse_config`; manuale-utente dialogo | T-4.4a, T-4.4b |

## Requisiti non funzionali (RNF-01..RNF-11)

| R | Fonte | Requisito verificabile | Verifica | Task |
|---|---|---|---|---|
| R31 | RNF-01 | CPU media < 1% di un core a finestra nascosta con 800+ processi utente | `pidstat -p <pid> 60 10` | T-6.5 |
| R32 | RNF-02 | RSS < 120 MB a finestra mai aperta, < 200 MB dopo apertura e chiusura | `ps -o rss` dopo 1 h | T-6.5 |
| R33 | RNF-03 | Ciclo < 1,5 s (900 processi, 10 container); main loop mai bloccato > 50 ms | log DEBUG durata ciclo | T-1.8a, T-6.5 |
| R34 | RNF-04 | Finestra con dati in < 1 s dal clic | manuale-utente cronometro | T-1.9b, T-6.5 |
| R35 | RNF-05 | Nessun `sudo`, `pkexec`, capability, setuid | `grep -rnE "sudo\|pkexec\|setcap" src packaging scripts` vuoto + caso positivo su fixture | T-6.1 |
| R36 | RNF-06 | Executor rifiuta processi protetti o di altri utenti anche con piano costruito a mano | auto: test executor con caso positivo appaiato | T-3.3a |
| R37 | RNF-07 | Nessun `shell=True`, argomenti a lista, sempre `timeout` | `ruff` con S602/S604 attivi; test che ogni `subprocess.run` ha timeout | T-0.1a, T-6.1 |
| R38 | RNF-08 | Log su stderr e file rotante 1 MB x 3; `WIMM_LOG_LEVEL`; mai cmdline a `INFO` | auto: test del formatter | T-1.8b |
| R39 | RNF-09 | Funziona senza Docker o senza permessi Docker | auto: collector Docker finto che solleva | T-1.5b |
| R40 | RNF-10 | Un'eccezione di collector o regola non ferma il ciclo successivo | auto: test sampler con collector che solleva | T-1.8a |
| R41 | RNF-11 | Riavvio o logout non perdono i tempi di inattività | auto: test persistenza | T-4.3a |

## Definition of Done della specifica (§17)

| R | Voce | Condizione | Verifica | Task |
|---|---|---|---|---|
| R42 | DoD 1 | Dopo logout/login icona visibile e `pgrep -f /usr/bin/wimm` trova un processo | manuale-utente | T-2.2, T-6.6 |
| R43 | DoD 2 | Clic sinistro apre in < 1 s; RAM, swap, disco entro 2% di `free -b`/`df -B1 /`; chiudi nasconde, Esci termina | Inspector `GetSnapshot` vs `free -b` (auto) + manuale-utente | T-1.1a, T-1.8c, T-1.9b |
| R44 | DoD 3 | Container `whitebox` e `luve-agent` raggruppati per progetto, memoria entro 5% di `docker stats` | comando di confronto (auto, sola lettura) | T-1.5b, T-1.6a |
| R45 | DoD 4 | `python3 -m http.server 8765` in cartella progetto: DEV_SERVER del progetto, `active` con curl ogni 10 s, `idle` dopo la finestra, motivo coi numeri | integrazione con finestra 20 s (auto) + manuale-utente su installato | T-1.7b, T-1.8c |
| R46 | DoD 5 | Firefox gruppo `BROWSER`, PSS (non RSS), rischio "Attenzione", attività misurata col primo piano (T-5.5 incluso) | Inspector + jq (auto) | T-1.4b, T-5.5b |
| R47 | DoD 6 | Sessione GNOME, dockerd, altri utenti solo in vista Sistema senza azioni | Inspector: nessun gruppo protetto in `groups`; smoke UI | T-1.4a, T-1.9d |
| R48 | DoD 7 | Fermare un gruppo idle mostra anteprima, esegue, riporta liberato misurato; bersagli fermi | manuale-utente su bersagli di test | T-3.7b |
| R49 | DoD 8 | Rimozione volume richiede il nome digitato e rifiuta un nome diverso | auto: `ConfirmationMismatch`; manuale-utente dialogo | T-3.5, T-3.7a |
| R50 | DoD 9 | Piano a mano su processo protetto o di altro utente rifiutato con `ProtectedTarget` | auto | T-3.3a |
| R51 | DoD 10 | Una sola notifica per gruppo idle; "Silenzia 24 h" la sopprime; inattività conservata al riavvio | auto + manuale-utente | T-4.1, T-4.2b, T-4.3a |
| R52 | DoD 11 | Vista Disco coerente con `docker system df`; pulizia build cache libera lo spazio indicato (scarto < 10%) | manuale-utente (prune reale non filtrabile) | T-5.1b, T-5.4b |
| R53 | DoD 12 | Dopo riavvio di GNOME Shell l'icona ricompare senza riavviare l'app | auto con watcher finto + manuale-utente Alt+F2 r | T-1.11 |
| R54 | DoD 13 | `make lint`, `make test` verdi, copertura core >= 90%, integrazione e D-Bus verdi | `make lint && make test && make test-all` | ogni fase, T-6.4 |
| R55 | DoD 14 | RNF-01/02/03 misurati e riportati coi numeri in `docs/REPORT_ATTIVITA.md` | lettura del report | T-6.5 |

## Vincoli trasversali

| R | Fonte | Requisito verificabile | Verifica | Task |
|---|---|---|---|---|
| R56 | §0.5 | Nessuna azione distruttiva reale durante lo sviluppo: i test agiscono solo su bersagli creati dal test (http.server, container `wimm.test=1`, HOME temporanea) | review dei test di integrazione; `grep` di `prune`/`kill` nei test con bersaglio creato nello stesso test | tutti, T-6.1 |
| R57 | §0.7 | File <= 300 righe, funzioni <= 30, parametri <= 4, costanti nominate | auto: `tests/test_source_limits.py` | T-0.1b |
| R58 | §5.1 | `categorize_process` segue l'ordine 1-9; container e PROJECT assegnati in `grouping.py` | auto: una riga di test per regola, cgroup reali | T-1.4a, T-1.4b |
| R59 | §5.3 | `assess_risk(entity, action)` copre ogni riga della tabella con conseguenza in italiano; rischio gruppo = massimo dei membri | auto: test parametrico 1 riga = 1 caso | T-3.1a, T-3.1b |
| R60 | §5.4 | Nuova connessione (quadrupla nuova, stato != LISTEN) o CPU processo+figli; connessione persistente non conta (HMR) | auto | T-1.7a, T-1.7b |
| R61 | §8.2 | Impronte e rivalidazione all'esecuzione: `TargetChanged` se cambiato, "già fatto" se sparito | auto | T-3.2a, T-3.3a |
| R62 | §6.2 | Istanza unica, `hold()`, `--background`/`--group`/`--version`, banner senza watcher dopo 10 s, ri-registrazione su `name-appeared` | auto (dbus) + manuale-utente | T-1.8c, T-1.11 |
| R63 | §6.3 | Inspector D-Bus in sola lettura (`GetSnapshot`, `GetDiskReport`, `Version`), nessuna azione esposta | auto: introspezione elenca solo questi membri | T-1.8c, T-5.2c |
| R64 | §12 | `.deb` con Depends/Recommends verificati, file di §12.2, postinst/prerm, Maintainer non inventato | `dpkg-deb --info/--contents`; `scripts/test_deb.sh` | T-2.1, T-2.2, T-2.3 |
| R65 | §14.1 | Venv con `--system-site-packages`: `psutil.__version__ == "5.9.8"`, `docker.__version__ == "5.0.3"` | auto | T-0.1a |
| R66 | D-U3 | CI GitHub Actions ubuntu-24.04: apt dei pacchetti di sistema + uv, `make lint` e `make test`; action pinnate a SHA, `permissions` minime, `persist-credentials: false` | `yamllint` + grep SHA 40 hex; primo run verde dopo push dell'utente | T-0.3 |
| R67 | Fase 6 | Security baseline, README rifinito, ADR in `docs/adr/`, setup da clean clone, Delivery Report | artefatti presenti; clean clone verde | T-6.1..T-6.6 |
| R68 | §0.6, §0.8 | Ogni premessa [DA VERIFICARE] chiusa con esito in `docs/DEVIATIONS.md` (confermata o smentita + ripiego §18) | lettura di `docs/DEVIATIONS.md`: 4 voci | T-0.1a, T-2.1, T-3.6, T-3.8b |
