# Delivery Report: where-is-my-memory (comando `wimm`)

Data: 2026-10-17. Destinatario: chi ha commissionato l'applicazione.

`wimm` è un'applicazione per Ubuntu 24.04 con GNOME su X11. Vive nella barra in alto, mostra quali programmi, container e cartelle occupano memoria e disco, dice quali sono inattivi e da quanto, e permette di fermarli o pulirli dopo un'anteprima e una conferma proporzionata al rischio. Non agisce mai da sola e non usa privilegi di root.

Questo documento dice che cosa è dimostrato, che cosa resta da provare a mano sul vostro computer e che cosa chiede una vostra decisione. Il riferimento è `assets/SPECIFICHE.md`, che prevale su ogni altro documento. Gli ID `T-x.y` sono i task della specifica, gli ID `M-n` sono i controlli manuali della sezione 3.

## Esito in breve

- Delle 14 voci della Definition of Done (§17): 6 fatte con evidenza automatica, 0 fatte con deviazione, 8 da verificare a mano, 0 non fatte.
- Misure RNF: RNF-02 e RNF-03 rispettati. RNF-01 misurato a 1,32-1,60% di un core con l'intervallo di 30 s; dopo le ottimizzazioni del ciclo (0,33-0,34 s di CPU) e la vostra decisione di portare l'intervallo predefinito a 60 s, la misura di conferma dà 0,53-0,63% di un core a regime (minuti 8-15, 391 processi): RNF-01 rispettato, salvo il minuto della prima scansione del disco (14%), che si ripete ogni 6 ore. La misura sull'installato resta M-15.
- Le misure sono state fatte sul build del repository e non sul pacchetto installato, perché l'installazione richiede `sudo`: la ripetizione sull'installato è M-15.
- La sicurezza (RNF-05) è verificata: nessun finding P0 o P1, cinque note P2 ancora aperte e sotto la soglia di sfruttabilità.
- Per chiudere il lavoro servono da voi: l'installazione del pacchetto (M-5), un logout con nuovo login (M-6) e gli altri controlli della sezione 3. Il push su GitHub, e quindi il primo giro della CI remota, lo fate voi.

## 1. Definition of Done (§17)

Stati: fatto, fatto con deviazione, da verificare a mano, non fatto. Una voce è "fatto" solo se esiste un test o un comando eseguito che la dimostra. Dove la specifica chiede una prova sul computer reale e quella prova richiede un'azione dell'utente, la voce resta "da verificare a mano".

| N. | Voce (sintesi) | Stato | Evidenza |
|---|---|---|---|
| 1 | Dopo logout e login l'icona compare e `pgrep -f "/usr/bin/wimm"` trova un processo | da verificare a mano (M-6) | Il pacchetto installa l'autostart `wimm --background` (commit `85ac472`), verificato in container Ubuntu 24.04 da `make test-deb` (`2bca376`; vedi REPORT_ATTIVITA, sessione #1). `tests/integration/test_background.py` prova l'avvio in background su bus privato. Il pacchetto non è installato sull'host: logout e login li fate voi |
| 2 | Il clic apre la finestra in meno di 1 s; RAM, swap e disco coerenti con `free -b` e `df -B1 /` (scarto < 2%); chiudere nasconde, "Esci" termina | da verificare a mano (M-2) | Coerenza con `free -b`: `tests/collectors/test_meminfo.py::test_meminfo_matches_free`, tolleranza 2% (`464a024`). Chiusura che nasconde: `tests/ui/test_window_clickthrough.py::test_closing_hides_the_window_without_destroying_it`. Il tempo di apertura è misurato solo su Xvfb (docs/PERF.md): la finestra si crea alla prima apertura (docs/DEVIATIONS.md, "Processo residente senza GTK"), quindi la prima apertura va cronometrata a mano |
| 3 | I container compose raggruppati per progetto, memoria coerente con `docker stats` (scarto < 5%) | fatto | `tests/collectors/test_docker_source.py::test_real_total_container_memory_matches_docker_stats` confronta con `docker stats` sui container in esecuzione (`4e4f4b1`, `20a7b84`). Raggruppamento: `tests/core/test_grouping.py` con la fixture `tests/fixtures/snapshot_whitebox.json` (`28ef679`). I nomi `whitebox` e `luve-agent` compaiono solo nella fixture: i progetti reali si guardano nel percorso di M-16. Il test di confronto è risultato instabile una volta (sezione 6) |
| 4 | `python3 -m http.server 8765` compare come dev server del progetto, `active` con `curl` ogni 10 s, `idle` dopo la finestra, con i numeri nel motivo | da verificare a mano (M-16) | La regola e il motivo con i numeri sono provati sui dati: `tests/core/test_activity_state.py` ("nessuna connessione in ingresso e CPU media 0,0% negli ultimi 30 minuti"), `tests/core/test_text.py`, `tests/collectors/test_sockets.py` (server avviato dal test). Non esiste un test end to end con il `curl` periodico e la finestra di 20 s previsto dal piano: va provato sull'installato |
| 5 | Firefox gruppo `BROWSER` con PSS, rischio "Attenzione", attività misurata col primo piano | da verificare a mano (M-16) | Categoria: `tests/core/test_categorize.py` (scope `snap.firefox...` e `app-gnome-firefox-...` danno `BROWSER`). Memoria PSS: `tests/core/test_memory.py::test_process_memory_pss_uss_swap`. Primo piano su X11: `tests/core/test_activity_foreground.py`, `tests/integration/test_foreground_real.py` (`ffec336`, `c0e8c5c`). Il comportamento alla chiusura è stato misurato su Firefox snap 158.0 (docs/DEVIATIONS.md, "Firefox e SIGTERM"). La lettura sul vostro Firefox reale non è registrata |
| 6 | Sessione GNOME, dockerd e processi di altri utenti solo nella vista Sistema, senza pulsanti di azione | fatto | `tests/ui/test_viewmodel.py::test_protected_groups_never_appear_in_the_overview` e `::test_system_rows_are_read_only_and_largest_first`; classificazione in `tests/core/test_categorize.py` e `tests/core/test_assemble_system.py` (`1b740c9`, `58c2f71`) |
| 7 | Fermare un gruppo `idle` mostra l'anteprima, esegue, riporta il liberato misurato; processo e container risultano fermi | da verificare a mano (M-8) | Piano e impronte: `tests/core/test_planning.py` (`78f6b99`). Esecuzione: `tests/service/test_executor_processes.py`, `tests/service/test_executor_containers.py`, `tests/integration/test_terminate.py` (server creato dal test, `09e3697`). Esiti e dialoghi: `tests/ui/test_window_outcome.py`, `tests/ui/test_confirm_dialog.py` (`303c334`, `259a244`). L'anteprima e il liberato vanno visti su bersagli di prova, come prevede la specifica |
| 8 | La rimozione di un volume chiede il nome digitato e rifiuta un nome diverso | fatto | `tests/service/test_plan_registry.py::test_wrong_phrase_raises_mismatch_without_consuming_the_plan`; `tests/ui/test_confirm_dialog.py::test_danger_dialog_enables_the_button_only_for_the_exact_phrase`; piano con frase in `tests/core/test_planning.py` e `tests/core/test_planning_disk.py`. Il clic reale sul dialogo è comunque nel percorso di M-8 |
| 9 | Un piano costruito a mano su un processo protetto o di altro utente è rifiutato con `ProtectedTarget` | fatto | `tests/service/test_executor_processes.py::test_execute_protected_process_is_rejected_without_signals` e `::test_execute_process_of_another_uid_is_rejected_even_if_fingerprint_matches`, ciascuno con il caso positivo appaiato (`::test_execute_terminates_unprotected_process_of_the_user`) |
| 10 | Una sola notifica per gruppo inattivo; "Silenzia 24 h" la sopprime; dopo un riavvio il tempo di inattività resta | da verificare a mano (M-10, M-11) | Una sola notifica: `tests/core/test_notify_rules.py::test_same_episode_over_two_cycles_notifies_once` (`bbb790e`). Silenzio: `tests/service/test_notifications.py::test_a_group_snoozed_in_the_snapshot_is_silent_and_others_are_not`. Persistenza: `tests/service/test_last_active.py`, `tests/service/test_state_store.py`, `tests/integration/test_state_persistence.py` (`281f88d`, `f37d3c0`). I clic sulla notifica reale e il riavvio dell'app sono M-10 e M-11 |
| 11 | La vista Disco è coerente con `docker system df` e la pulizia della build cache libera lo spazio indicato (scarto < 10%) | da verificare a mano (M-13) | Il conteggio del recuperabile segue `docker system df` (`0b9a3f9`, `tests/core/test_disk_df_reclaimable.py`, `tests/core/test_disk_reclaim_parity.py`). Sul computer di prova il dato è passato da 22,4 GB a circa 16 GB (REPORT_ATTIVITA, sessione #2). La pulizia della build cache è provata solo su finti (`tests/service/test_executor_disk_docker.py::test_builder_prune_returns_the_space_the_daemon_reports`), mai su dati reali: la specifica stessa la dà come prova manuale |
| 12 | Dopo un riavvio di GNOME Shell l'icona ricompare senza riavviare l'app | da verificare a mano (M-3) | Ri-registrazione a ogni ricomparsa del servizio della barra, con un servizio finto che sparisce e ricompare: `tests/tray/test_watcher.py`, `tests/tray/test_tray_watcher.py` (`ea86766`). Il riavvio vero della shell (`Alt+F2`, `r`) lo fate voi |
| 13 | `make lint` e `make test` verdi, copertura >= 90% su `src/wimm/core`, test di integrazione e D-Bus verdi | fatto | Clone pulito (T-6.4): `make setup`, `make lint`, `make test`, `make test-all` verdi, 2029 test. La soglia del 90% è imposta da `make test` con `--cov=src/wimm/core --cov-fail-under=90` (Makefile): sotto soglia il comando fallisce. Il valore esatto della copertura non è riportato in questo documento |
| 14 | RNF-01, RNF-02 e RNF-03 misurati e riportati in `docs/REPORT_ATTIVITA.md` con i numeri | fatto | Misure del 2026-10-17 nella sezione 2, in `docs/REPORT_ATTIVITA.md` (sessione #3) e in `docs/PERF.md`. La voce chiede la misura, non l'esito: RNF-01 era sopra il limite con 30 s ed è rispettato con l'intervallo a 60 s (0,53-0,63% a regime) |

Conteggio: fatto 6 (voci 3, 6, 8, 9, 13, 14), fatto con deviazione 0, da verificare a mano 8 (voci 1, 2, 4, 5, 7, 10, 11, 12), non fatto 0.

## 2. Requisiti non funzionali RNF-01..RNF-05

### Metodo delle misure RNF-01, RNF-02, RNF-03

Installare il `.deb` richiede `sudo`, che gli agent di sviluppo non usano. Le misure si fanno quindi sulla build del repository, avviata con `wimm --background` per 1 ora, su un bus D-Bus privato e un display Xvfb, con cartelle XDG temporanee, così il processo non tocca le vostre impostazioni reali. Sul bus privato gira un servizio della barra finto: senza, l'app apre la finestra con l'avviso dell'icona mancante (come prevede §6.2) e la misura a finestra mai aperta non sarebbe valida; un primo tentativo senza quel servizio è stato fermato per questo motivo. Le grandezze sono quelle di §13: uso medio di CPU a finestra nascosta, RSS dopo 1 ora, durata del ciclo di campionamento dal log `DEBUG`.

Condizioni della misura (2026-10-17, 07:02-08:02): 393 processi utente, 8 container, load average 5,4-6,4. La specifica chiede 800 o più processi utente e una macchina quieta: le condizioni sono quindi diverse. Il numero di processi è più basso, il che favorisce il risultato; il carico è più alto, il che lo sfavorisce. Il verdetto va letto con questa riserva. La misura sull'installato e a macchina quieta resta in M-15.

| Requisito | Soglia (§13) | Valore misurato |
|---|---|---|
| RNF-01 | media sotto l'1% di un core a finestra nascosta | **non rispettato**: 1,32-1,60% di un core a regime, media 2,30% sui 10 minuti di `pidstat -p <pid> 60 10` con il picco del 10,15% della prima scansione del disco (build del repository, 1 h, 393 processi utente, 8 container, load average 5,4-6,4). Causa: il ciclo costa 0,47 s di CPU ogni 30 s, dominato dalla lettura di `smaps_rollup` per processo (docs/PERF.md). Con 800+ processi il valore sale. Dopo questa misura: ciclo ottimizzato a 0,33-0,34 s e intervallo predefinito a 60 s per vostra decisione, misura di conferma: 0,53-0,63% a regime, media 0,75% sui minuti 4-13 (sezione 6, docs/PERF.md) |
| RNF-02 | sotto 120 MB RSS a finestra mai aperta, sotto 200 MB dopo aver aperto e nascosto la finestra, dopo 1 h | rispettato: 63 MB di RSS dopo 55 minuti a finestra mai aperta (limite 120); 136 MB con la finestra aperta (limite 200), valore che vale come limite superiore per la finestra nascosta perché nasconderla non restituisce memoria (build del repository, 1 h, 393 processi utente, 8 container, load average 5,4-6,4). La chiusura con Ctrl+W su Xvfb senza window manager non è riuscita |
| RNF-03 | ciclo sotto 1,5 s con 900 processi e 10 container; main loop mai bloccato oltre 50 ms | rispettato alle condizioni misurate: 122 cicli, mediana 0,47 s, massimo 0,61 s, nessuno sopra 1,5 s (build del repository, 1 h, 393 processi utente, 8 container, load average 5,4-6,4); con 1300 processi la misura precedente era 1,25-1,55 s (sotto). Main loop: sotto 50 ms (misure precedenti, sotto). Le condizioni della specifica (900 processi, 10 container) non sono state riprodotte |

### Misure precedenti (docs/PERF.md)

Misurate il 2026-10-16 e 2026-10-17 sulla macchina di sviluppo, con circa 1300-1340 processi utente, 41 gruppi e Docker attivo.

- RNF-01: nessuna misura precedente.
- RNF-02, finestra mai aperta: 54,6 MB di RSS (40,6 MB di PSS) dopo 3 cicli. Con GTK 4 caricato all'avvio il processo sarebbe a 124 MB, sopra il limite: per questo GTK si carica alla prima apertura (docs/DEVIATIONS.md).
- RNF-02, finestra aperta e poi nascosta: 227 MB con il renderer di default, 130 MB con `GSK_RENDERER=cairo` e GL disattivato, 126 MB come default dell'app. Limite 200 MB.
- RNF-03, ciclo di campionamento: da 7,67 s (profilato) a 1,25-1,28 s su 5 cicli, 1,31-1,34 s nel processo `wimm --background`. Con load average 7,5 il ciclo ha misurato 1,40, 1,47 e 1,55 s: una misura ha superato il limite di 1,5 s. È la ragione per cui la misura di T-6.5 va fatta anche a macchina quieta e sotto carico. Ripiego già previsto se serve: R3 di §18.
- RNF-03, main loop: aggiornamento della panoramica con 300 gruppi 15-45 ms e costruzione 25-46 ms, sotto 50 ms; `plan_action` su 900 processi 22,0 ms al massimo; apertura della finestra senza display da 25,1 s di blocco a meno di 1 s.
- Ciclo reale con lo stato persistente: 0,41 s di mediana (REPORT_ATTIVITA, sessione #1).

### RNF-04

Il tempo di apertura è misurato con `scripts/measure_open_time.py` (docs/PERF.md, RNF-04): mediana 236 ms alla prima apertura e 10 ms alle riaperture, su Xvfb. La prova sul display reale resta nel controllo manuale M-2.

### RNF-05: nessun privilegio elevato

Fonte: `docs/security/T-6.1-security-baseline.md` (2026-10-17). Esito: soddisfatto.

- `grep -rnE "sudo|pkexec|setcap|shell=True" src packaging scripts data` non trova nulla (rc=1). Il controllo è stato provato con un file di prova che contiene quelle parole, e lì il grep le trova: la ricerca funziona.
- `ruff check --select S src` passa senza eccezioni `noqa` nel codice.
- Nel codice ci sono solo tre punti che lanciano comandi esterni (`src/wimm/service/fs_controls.py`, `src/wimm/service/compose.py`, `src/wimm/collectors/foreground.py`): argomenti sempre in lista, timeout sempre presente, mai una shell.
- Percorsi distruttivi: rimozione tramite descrittori di directory e `O_NOFOLLOW`, mount saltati, SIGTERM solo tramite il processo ricordato, frase di conferma imposta dal servizio.
- Superficie D-Bus: l'Inspector espone solo `GetSnapshot`, `GetDiskReport` e la proprietà `Version`; le azioni dell'applicazione sono solo `quit`, `open-group` e `snooze-group`, e un test fissa l'insieme esatto.
- File dell'utente: cartella 0700 e file 0600, verificato anche sulla macchina reale.
- Conteggio: P0 0, P1 0, P2 6 (uno corretto dopo la revisione), Info 3.
- Limiti della verifica: `bandit` e `pip-audit` non sono stati eseguiti (offline, non installati) e la suite di test non è stata eseguita dal revisore. La suite è stata poi eseguita in T-6.4.

## 3. Controlli manuali M-1..M-29

Spuntate la casella quando il controllo è fatto. Tutti i controlli richiedono il vostro computer: sessione grafica reale, logout, `sudo`, clic veri o azioni su risorse vostre. Nessuno è stato eseguito da chi ha sviluppato l'applicazione.

| Fatto | Id | Quando | Cosa fare | Esito atteso |
|---|---|---|---|---|
| [ ] | M-1 | Scheletro | Dal repository: `make setup && make lint && make test` | I tre comandi finiscono senza errori. Nel piano il checkpoint umano è decaduto (autonomia fino alla fine); il controllo resta come conferma |
| [ ] | M-2 | Sola visione | `make run`; clic sinistro sull'icona, clic destro, scelta di un gruppo dal menu, chiusura della finestra, uso dei filtri. Cronometrate la prima apertura | La finestra si apre o torna in primo piano, il menu ha le voci previste, il gruppo scelto si apre espanso, chiudere non termina il processo, la finestra si apre in meno di 1 s |
| [ ] | M-3 | Sola visione | Con l'app in esecuzione: `Alt+F2`, scrivere `r`, Invio (riavvio di GNOME Shell su X11) | L'icona ricompare senza riavviare l'app |
| [ ] | M-4 | Sola visione | Navigare da tastiera (Tab, `Ctrl+F`, `F5`, `Ctrl+,`) e stringere la finestra a 360 px | Ogni comando è raggiungibile, nessun elemento si sovrappone |
| [ ] | M-5 | Pacchetto e fine di ogni fase | `sudo apt install ./dist/where-is-my-memory_<versione>_all.deb` (dopo `make deb`) | Il pacchetto si installa |
| [ ] | M-6 | Pacchetto | Logout e nuovo login | L'icona è nella barra, `pgrep -f /usr/bin/wimm` trova il processo, la finestra è nascosta |
| [ ] | M-7 | Pacchetto | Seguire solo il README su un computer o un utente che non conosce il progetto | Il pannello si trova e si apre senza altre istruzioni |
| [ ] | M-8 | Azioni | Provare i dialoghi di rischio basso, medio e alto su un `http.server` di prova e su un progetto compose di prova, compresa "Forza chiusura" su un processo che ignora SIGTERM | Anteprima, esito e memoria liberata corretti; il pulsante di rischio alto resta disabilitato finché il nome non coincide |
| [ ] | M-9 | Azioni | Solo se si vuole ripetere a mano la prova su Firefox: chiudere il proprio Firefox da wimm e riaprirlo | Annotare se la sessione torna. La prova automatica su un profilo di test ha già dato esito positivo (docs/DEVIATIONS.md), quindi è facoltativa |
| [ ] | M-10 | Notifiche | Con `notify_after_s=60` e un server di prova inattivo: clic su "Apri" nella notifica, poi su "Silenzia 24 h" | La finestra si apre sul gruppo; non arrivano nuove notifiche per quel gruppo |
| [ ] | M-11 | Notifiche | "Esci" dal menu e rilancio dell'app | "Inattivo da" resta invariato |
| [ ] | M-12 | Notifiche | Nelle Preferenze: prima un valore fuori intervallo, poi uno valido | Errore sul campo; il valore valido ha effetto al ciclo successivo |
| [ ] | M-13 | Disco | Percorrere la vista Disco; eseguire "Svuota build cache" con la conferma | Lo spazio liberato è entro il 10% di quello indicato |
| [ ] | M-14 | Disco | Tenere Slack o un'app di prova in background oltre la finestra di osservazione | L'app risulta inattiva |
| [ ] | M-15 | Hardening | Clone pulito in un'altra cartella e misure RNF sull'installato per 1 ora, a macchina quieta | Comandi verdi; numeri riportati nel report attività |
| [ ] | M-16 | Hardening | Percorrere la Definition of Done della sezione 1 sull'installato | Le 14 voci risultano spuntate. Le voci 4 e 5 vanno provate qui per intero: server di prova con `curl` ogni 10 s e poi fermo, Firefox in lista con PSS |
| [ ] | M-17 | Radici | Con un utente di prova senza configurazione (`sudo adduser --disabled-password prova`, poi sessione grafica come `prova`, oppure `HOME=$(mktemp -d) XDG_CONFIG_HOME=$HOME/.config make run`) creare `~/Progetti/x/node_modules` e avviare wimm | Le radici rilevate compaiono in Preferenze e in Disco, la cartella di prova è trovata |
| [ ] | M-18 | Radici | Rinominare una radice configurata (`mv ~/Progetti ~/Progetti.old`), riaprire Disco e poi Preferenze | Disco e Preferenze mostrano l'avviso di cartella mancante, la radice non viene cancellata dalla configurazione; `mv ~/Progetti.old ~/Progetti` fa sparire l'avviso |
| [ ] | M-19 | Disco | Sul proprio disco, in una radice con progetti Rust, Gradle e Next: `ls -d ~/Progetti/*/target ~/Progetti/*/.gradle ~/Progetti/*/.next`, poi in Disco aprire la conferma di pulizia di una di queste cartelle | Le tre famiglie sono elencate e la conferma riporta il comando di ricostruzione (`cargo build`, `./gradlew build`, `npm run build`); annullare la conferma non cancella nulla |
| [ ] | M-20 | Lingua | `LANG=de_DE.UTF-8 LANGUAGE= make run` con configurazione vuota (`XDG_CONFIG_HOME=$(mktemp -d)`) | L'interfaccia è in inglese; in Preferenze la lingua si può cambiare in italiano e la finestra si ricostruisce subito |
| [ ] | M-21 | Hardening | `make audit` dal clone | `bandit` e `pip-audit` finiscono senza segnalazioni non giustificate (serve rete per `pip-audit`) |
| [ ] | M-22 | Hardening | Dopo il primo push (lo fate voi): `gh run list --limit 3` e `gh run watch` | La CI remota è verde, compreso il passo `make audit` |
| [ ] | M-23 | Futuro | Podman, sessione Wayland, radici su dischi esterni, comportamento con poca memoria (OOM) | Nessun comando ancora: sono ambiti dichiarati ma non provati, da definire quando servono |
| [ ] | M-24 | Podman | Con Podman installato e il socket utente attivo (`systemctl --user enable --now podman.socket`): `podman run -d --name wimm-podman-test docker.io/library/alpine:3 sleep 600`. In Panoramica cercare `wimm-podman-test`, premere "Ferma" e confermare. Pulizia: `podman rm -f wimm-podman-test` | Il contenitore compare come container e non come processo sciolto; "Ferma" lo ferma (`podman ps -a` lo mostra `Exited`) e l'esito è positivo. L'esecuzione su un client finto è già provata in `tests/service/test_executor_podman.py` |
| [ ] | M-25 | Notifica OOM | Con l'app in esecuzione: `systemd-run --user --scope -p MemoryMax=50M -p MemorySwapMax=0 python3 -c "b = bytearray(300 * 1024 * 1024)"` | Il comando esce con codice 137; entro un ciclo di campionamento arriva la notifica "Il sistema ha chiuso 1 programma per mancanza di memoria" con i gruppi più grandi. Il contatore è già provato dal vivo (da 6 a 7), la notifica sul desktop no |
| [ ] | M-26 | zram | Su una macchina con zram attivo (`zramctl` mostra un dispositivo in uso): aprire la Panoramica | La legenda della RAM mostra "Swap compresso in RAM (zram)" con un valore vicino alla colonna `TOTAL` di `zramctl`; il "?" accanto apre l'aiuto |
| [ ] | M-27 | GPU AMD | Su una macchina con una scheda AMD dedicata: aprire la Panoramica | Il blocco "Memoria video" mostra "AMD <usata> di <totale>", vicino a quanto riporta `amdgpu_top` o `radeontop`. Con una APU può comparire la memoria riservata alla grafica (vedi DEVIATIONS) |
| [ ] | M-28 | Secondo disco | Con un secondo disco ext4 montato (per esempio in `/mnt/data`) e una cartella vostra `/mnt/data/code` con un progetto vecchio che ha `node_modules`: in Preferenze, Impostazioni avanzate, aggiungere `/mnt/data/code` a "Cartelle in cui cercare" e applicare; poi aggiungere `/mnt/data` e applicare | `/mnt/data/code` è accettata e la scheda Disco propone il suo `node_modules`, che si cancella con la conferma; `/mnt/data` compare con il motivo "troppo vicina alla radice" e non viene percorsa |
| [ ] | M-29 | Primo piano su Wayland | Su GNOME 46 o successivo in sessione Wayland: `cp -r data/gnome-shell-extension/wimm-focus@wimm.github.io ~/.local/share/gnome-shell/extensions/`, uscire e rientrare dalla sessione, `gnome-extensions enable wimm-focus@wimm.github.io`; poi `gdbus call --session --dest io.github.wimm.Focus --object-path /io/github/wimm/Focus --method org.freedesktop.DBus.Properties.Get io.github.wimm.Focus1 FocusedPid` con una finestra in primo piano e `ps -p <pid>` sul risultato. Pulizia: `gnome-extensions disable wimm-focus@wimm.github.io` e `rm -r ~/.local/share/gnome-shell/extensions/wimm-focus@wimm.github.io` | Il comando restituisce `(<<uint32 N>>,)` con `N` uguale al pid del programma in primo piano (`ps` lo conferma); cambiando finestra il valore cambia, senza finestra a fuoco vale 0. Dopo `disable` il nome `io.github.wimm.Focus` sparisce dal bus e `journalctl --user -b` non mostra errori di wimm-focus. Non provato su 47 e 48 |

## 4. Premesse chiuse

Le domande aperte del piano (`specs/where-is-my-memory/plan.md`) sono state chiuse il 2026-10-16. Tre sono state delegate a chi coordinava il lavoro (Q-1, Q-4, Q-7), per le altre è stato accettato il default.

- **Q-1.** Il gruppo `TERMINAL` vale solo per il processo del terminale; l'eredità per antenato resta solo per `BROWSER` e `DESKTOP_APP`, altrimenti ogni dev server lanciato da terminale sparirebbe come tale.
- **Q-2.** Un dev server lanciato nel terminale di VS Code risulta parte di `DESKTOP_APP`, come dice la specifica; il limite è documentato nelle domande frequenti del README.
- **Q-3.** Le shell del terminale vanno nel gruppo `TERMINAL` senza azioni proprie.
- **Q-4.** Il calcolo del rischio (T-3.1a, T-3.1b) è stato anticipato in Fase 1, perché la sola visione già mostra il rischio.
- **Q-5.** Le voci si escludono dal dialogo multiplo con `excluded_ids` nella richiesta; ogni interruttore chiede un nuovo piano.
- **Q-6.** Il recuperabile su disco è la somma delle voci sicure dell'ultimo report, zero prima della prima scansione.
- **Q-7.** Il checkpoint dopo la Fase 0 è `make setup && make lint && make test` verdi più `wimm --version` eseguibile; il checkpoint umano è decaduto.
- **Q-8.** Le pulizie reali (prune di immagini e container, cache uv e npm, cestino) non si eseguono nei test: test con finti e cartelle temporanee, esecuzione reale solo a mano (M-13).
- **Q-9.** La prova su Firefox si fa con un'istanza separata e un profilo di test, mai col Firefox dell'utente; esito: con SIGTERM la sessione si recupera, quindi "Chiudi browser" resta a rischio medio senza frase di conferma.
- **Q-10.** La notifica di pressione usa la soglia configurabile `pressure_critical_pct`, non un 10% fisso.
- **Q-11.** Le miniature in `~/.cache/thumbnails` hanno un'azione di pulizia, non sono solo mostrate.
- **Q-12.** I processi dell'utente fuori da `user@1000.service` (SSH, tmux avviato lì) restano trattati come sistema e protetti; è documentato nelle domande frequenti.
- **Q-13.** Le pulizie di massa di immagini e container diventano rimozioni per id lette al piano e rivalidate una per una; la build cache resta un prune unico (docs/DEVIATIONS.md, "Azioni di massa su immagini e container").
- **Q-14.** Le righe di comando con `--token`, `--password`, `--secret`, `*KEY=`, `*TOKEN=` sono oscurate nel JSON del bus e nei log; la finestra mostra la riga completa solo espandendo il membro.

Le quattro premesse da verificare della specifica sono chiuse in `docs/DEVIATIONS.md`:

- Type stubs (§14.1): smentita, applicato il ripiego (sezione "Type stubs").
- Nomi dei pacchetti (§12.1): in parte smentita, il pacchetto `gnome-shell-extension-ubuntu-appindicators` non esiste ed è tolto dai `Recommends` (sezione "Nomi dei pacchetti e Recommends").
- `docker compose -p <nome> down` senza file compose (§7.3): regge, provato con un progetto di prova (sezione "Premessa compose senza file").
- Firefox con SIGTERM (§8.4): le schede si recuperano (sezione "Firefox e SIGTERM").

## 5. Deviazioni dalla specifica

Elenco delle 28 sezioni di `docs/DEVIATIONS.md`, nell'ordine del file. Ogni sezione riporta la scelta, il motivo e l'evidenza.

1. Type stubs (T-0.1a): premessa smentita, ripiego applicato.
2. CI (T-0.3).
3. `stop_group` / `group_stop` (T-0.2a).
4. Ordine di `categorize_process`: esclusione Docker prima di SYSTEM (T-1.4a).
5. Ereditarietà di `TERMINAL` (Q-1, T-1.4b).
6. Radice di progetto: la home non è una radice (T-1.2b).
7. Container in rete `host` (T-1.5b).
8. Categorie: servizi utente e app con documenti lanciate dal terminale (T-1.4b).
9. Nomi delle unit systemd con escape (T-1.4b).
10. Attività: CPU mai misurabile nella finestra (T-1.7b).
11. Conseguenza per la categoria `OTHER` (T-3.1a).
12. Id stabile dei gruppi: classe della chiave al posto della categoria (T-1.6b).
13. Vista Sistema: gruppi per etichetta (T-1.6b).
14. Processo residente senza GTK: `Gio.Application` con finestra caricata a richiesta (T-1.8c).
15. Rendering senza GL (T-1.9b).
16. Nomi dei pacchetti e Recommends (T-2.1).
17. Script del pacchetto: `postrm` e pulizia del bytecode (T-2.2).
18. Verifica del pacchetto in container: conffile e changelog (T-2.3).
19. Premessa compose senza file (T-3.6).
20. Compose: costi accettati dell'esecuzione (T-3.6).
21. Firefox e SIGTERM: la sessione si recupera, la conseguenza cambia (T-3.8b, R8).
22. Notifiche di pressione fuori dal limite orario (T-4.1).
23. Preferenze aggiornate dalla finestra: un campo invalido tiene il valore precedente (T-4.4a).
24. Silenzio globale solo per la sessione; una notifica che non parte non si ritenta (T-4.3b, T-4.2b).
25. Azioni di massa su immagini e container: rimozioni per id lette al piano (T-5.3a, Q-13).
26. Esecuzione Docker del disco: build cache con `all=true`, "in uso" come nel report (T-5.3b).
27. Cartelle, cache e cestino: rimozione senza attraversare mount (T-5.3c).
28. Attività dal primo piano: limiti noti (T-5.5b).

Una conseguenza visibile della sezione 18: `apt remove` lascia il file di avvio automatico in `/etc/xdg/autostart/`, e solo `apt purge` lo toglie.

## 6. Punti aperti

### RNF-01: decisione presa

Il ciclo è stato ottimizzato senza cambiare il comportamento (da 0,41-0,43 a 0,33-0,34 s di CPU, docs/PERF.md) e l'intervallo predefinito è passato da 30 a 60 s per vostra scelta del 2026-10-17 (docs/DEVIATIONS.md). Misura di conferma del 2026-10-17 (12:31-12:45, 391 processi): 0,53-0,63% di un core a regime, media 0,75% sui minuti 4-13; il minuto della prima scansione del disco arriva al 14%, e su 13 minuti porta la media all'1,72%. La ripetizione sull'installato e a macchina quieta resta M-15.

### Note di sicurezza P2 ancora aperte

Dalla baseline di sicurezza (P2-1 è stato corretto: i comandi di pulizia delle cache girano da `/`). Nessuna raggiunge la soglia di sfruttabilità; la baseline chiedeva di riconsiderarle in questo report.

- **P2-2.** Il controllo dell'insieme dei container di un progetto compose e il `down` non sono atomici: un container avviato in quei pochi millisecondi verrebbe fermato con gli altri. Possibile solo per una corsa con un altro strumento dello stesso utente. Nessuna correzione economica; accettato o da risolvere passando gli id dei container.
- **P2-3.** L'azione `snooze-group` accetta qualunque stringa non vuota da qualunque processo dello stesso utente, e le voci restano in `state.json` fino alla scadenza senza un tetto al numero. Rimedio: un tetto o la validazione contro gli id dei gruppi dello snapshot.
- **P2-4.** L'oscuramento delle righe di comando non copre le forme brevi (`-p segreto`, `-psegreto`, `curl -u utente:password`) nell'output dell'Inspector. Chi legge è lo stesso utente, che può già leggere `/proc/<pid>/cmdline`: nessun confine superato.
- **P2-5.** L'esecutore dei comandi di cache raccoglie stdout e stderr senza limite in memoria. Sono strumenti locali e fidati.
- **P2-6.** Nessun tetto a numero e profondità delle radici di ricerca cartelle oltre agli intervalli di configurazione (profondità 1-12). Il danno possibile è solo CPU propria.

### Limiti noti

- **Primo piano.** Un browser che riproduce un video o un'app musicale mai portata in primo piano diventa inattivo dopo la finestra di osservazione. Le loro azioni sono a rischio medio, quindi restano fuori da "ferma tutti gli inattivi sicuri" e dalle notifiche di default. Per le app Flatpak il processo della finestra attiva non è attribuibile e lo stato resta sconosciuto, mai inattivo. Il comportamento reale con Flatpak non è stato provato.
- **Pulizia della build cache.** Non misurata su dati reali: M-13. La specifica la dà come prova manuale perché il prune non si può limitare alle risorse di test.
- **Bind mount.** Il comportamento con un bind mount reale non è stato provato: i test usano bersagli creati dal test.
- **Test di confronto con `docker stats`.** È risultato instabile una volta in un'esecuzione parallela e non è stato riprodotto. Va osservato nelle esecuzioni future.
- **Disco quasi pieno.** Durante la misura è stato osservato che il vostro disco ha meno del 10% di spazio libero. Non è stato verificato come l'applicazione si comporta con quel livello di spazio libero (le notifiche di pressione usano la soglia `pressure_critical_pct`, Q-10). Il dato non dipende dall'applicazione.
- **CI remota.** Non è mai stata eseguita: parte al primo push, che fate voi. Il primo giro potrebbe essere rosso per differenze di versione dei pacchetti Ubuntu; i pin alle versioni di Noble sono verificati da un test con messaggio esplicito (docs/DEVIATIONS.md, "CI").
- **Pacchetto e controlli.** `lintian` dà un avviso `no-manual-page` su `/usr/bin/wimm`; `appstreamcli` dà `url-homepage-missing` perché il progetto non ha ancora un indirizzo pubblico. Nessun errore. `bandit` e `pip-audit` non sono stati eseguiti.
- **Limiti per l'utente documentati nel README.** La misura per singola scheda del browser è fuori dal perimetro (N5 del piano); un dev server nel terminale di VS Code non compare come dev server (Q-2); i processi in sessioni SSH risultano di sistema (Q-12).

### Rilievi delle revisioni lasciati come minori

- La riga Disco resta cliccabile fino alla nuova scansione, anche dopo un'azione che l'ha già svuotata.
- Lo spazio liberato per immagini e volumi arriva solo con la misura del recupero dopo la nuova scansione: l'esito subito dopo l'azione dice `freed_bytes=unknown` nel log per questi tipi (docs/DEVIATIONS.md, "Esecuzione Docker del disco").
- `src/wimm/ui/window.py` è a 299 righe su 300: il prossimo intervento su quel file richiede di scomporlo.

## 7. Controlli eseguiti

CHECKS: code-reviewer ESEGUITO (su ogni lotto di task) | security-reviewer ESEGUITO (T-6.1, nessun P0 o P1) | reader-test ESEGUITO (README, lettore a contesto pulito: 9 domande, tutte trovate dopo il secondo giro) | clone pulito ESEGUITO (T-6.4: `make setup`, `make lint`, `make test`, `make test-all` verdi, 2029 test) | a11y-gate N/A (interfaccia GTK, non HTML; sostituito da test sui nomi accessibili, render a 360 e 1280 px e controllo M-4) | misure RNF-01..03 ESEGUITE (RNF-01 non rispettato)
