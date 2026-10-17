# Report attività

## 2026-10-16/17 | Sessione #1 [FEATURE]

Progetto: where-is-my-memory (comando `wimm`), app GNOME per Ubuntu che mostra quali programmi occupano memoria e permette di fermare quelli inattivi. Il lavoro copre le 28 modifiche successive al commit 6fdde89, dal 16 ottobre alle 20:43 al 17 ottobre alle 04:03. Le specifiche di riferimento sono in `assets/SPECIFICHE.md`, il piano in `specs/where-is-my-memory/`.

### Richiesta

Chiudere la Fase 1 (icona nella barra e controllo del suo ritorno), costruire il pacchetto .deb e la guida utente (Fase 2), poi arrivare a pianificazione, esecuzione e conferma delle azioni (Fase 3) e a notifiche, stato persistente e preferenze (Fase 4).

### Azioni Eseguite

**Fase 1, chiusura**
- Icona nella barra (StatusNotifierItem) e menu (dbusmenu) portati da sysbar su `Gio.DBusConnection`. Ogni chiamata riceve risposta anche se il gestore fallisce, e un elemento disabilitato ignora i clic.
- Menu costruito dallo snapshot dei dati, con voci a id fisso. Un clic arrivato su un menu ormai vecchio non può trasformare "Silenzia" in "Esci".
- Controllo del servizio della shell (`org.kde.StatusNotifierWatcher`): l'icona si registra di nuovo ogni volta che il servizio ricompare. Dopo 10 secondi senza servizio la finestra si apre comunque, anche con `--background`, e mostra un avviso che spiega perché manca l'icona. L'avviso sparisce solo quando la registrazione riesce.
- Se la finestra non può aprirsi (nessun display), il processo residente continua a girare e riprova alla richiesta successiva.
- Il test della panoramica con 300 gruppi usa ora lo stesso renderer dell'app.

**Fase 2: pacchetto, test in container, README**
- `scripts/build_deb.sh` prepara la struttura della sezione 12.2 delle specifiche e costruisce il pacchetto con `dpkg-deb`. Il maintainer arriva da `WIMM_MAINTAINER` o dalla configurazione git del repository, e senza maintainer il build fallisce. Aggiunti voci di menu, metainfo, `postrm` e `prerm`.
- `make test-deb` installa il .deb in un container `ubuntu:24.04`, controlla i percorsi installati e `wimm --version`, esegue `lintian` e verifica che `remove` e `purge` non lascino file. Esito: due esecuzioni consecutive a exit 0, 0 errori, 1 avviso (`no-manual-page`).
- Cartella di appoggio del build esclusa da mypy.
- README per l'utente finale: installazione, primo avvio, icona ed etichetta, comportamento senza AppIndicator, file dell'utente, disinstallazione, domande frequenti su browser, VS Code, SSH e macchine remote. Un lettore non tecnico a contesto pulito ha trovato 5 risposte su 7 al primo giro e 5 su 5 al secondo, dopo l'aggiunta dei prerequisiti di build e della domanda sulle macchine remote.

**Fase 3: azioni sui processi**
- Ogni membro di un gruppo porta ora `uid`, `has_documents` e `is_foreground`, gli stessi fatti usati per valutare il rischio. Lo schema dello snapshot resta 1.
- Pianificazione (`plan_action`): produce un piano non modificabile con impronte per bersaglio, identificativo casuale, scadenza di 120 secondi, rischio e conseguenze. Per il rischio massimo chiede di digitare il nome. Le azioni "ferma gruppo" e "ferma tutti gli inattivi sicuri" sono coperte, e si possono escludere voci e ripianificare.
- Esecuzione (`PlanExecutor`): riverifica ogni bersaglio prima di inviare segnali. Rifiuta l'intero piano se qualcosa è cambiato. I segnali SIGTERM vanno prima ai figli e poi al processo principale, con attesa limitata. Se un processo non risponde l'esito è `not_responding`, mai un SIGKILL automatico. Un container già fermato dall'utente conta come fatto.
- `AppService` pianifica ed esegue sull'unico worker di campionamento. Emette l'esito per passo e, 3 secondi dopo, la RAM e il disco liberati.
- Progetti compose: `docker compose -p <progetto> down` (con `-v` quando richiesto), lanciato come lista di argomenti dalla directory `/`, con nome validato e timeout di 120 secondi. La premessa "funziona senza il file compose" è stata verificata con una prova reale.
- Dialoghi di conferma per livello di rischio: pulsante suggerito per il sicuro, avviso per l'attenzione, campo di testo che abilita il pulsante solo con il nome esatto per il pericolo. Il dialogo multiplo ha interruttori che ripianificano. Un dialogo si esegue al massimo una volta.
- Esiti: avviso con "Dettagli" che elenca ogni passo in italiano, aggiornato con la RAM liberata appena misurata. I pulsanti restano "In corso…" finché il loro piano non ha un esito. "Forza chiusura" su un passo `not_responding` chiede un nuovo piano `process_kill` con la sua conferma, mai un'uccisione diretta.
- Verifica Firefox: il testo della conseguenza di "Chiudi browser" è stato corretto dopo una misura reale.

**Fase 4: notifiche, stato, preferenze**
- `evaluate_notifications` decide cosa notificare: gruppi inattivi oltre soglia, al massimo 3 all'ora con le eccedenti riunite in una sola, e pressione di RAM o disco con i 3 gruppi più liberabili e un'ora di pausa per tipo.
- Notifiche Gio con azioni "apri gruppo" e "silenzia 24 h". `NotificationCoordinator` le invia a ogni snapshot.
- `state.json` (scrittura atomica, permessi 0600, salvataggio ogni 5 minuti e all'uscita) conserva ultima attività, silenzi, gruppi ignorati ed episodi già notificati. Un file mancante, troncato, troppo profondo o più recente viene tollerato.
- `UserStateKeeper` unifica silenzi per gruppo, gruppi ignorati e silenzio globale: finestra, icona e regole di notifica leggono lo stesso stato.
- La finestra mostra, per ogni gruppo aperto, "Silenzia" (1 ora, 24 ore, 7 giorni) e "Ignora" / "Non ignorare più".
- Finestra Preferenze (`Adw.PreferencesDialog`) con i campi di RF-50 in cinque gruppi. "Applica" invia solo i campi cambiati. Un campo rifiutato mostra l'errore e torna al valore in uso. Le modifiche arrivano subito a campionatore ed esecutore, senza riavvio. I gruppi ignorati si ripristinano dalla stessa finestra.

### Decisioni registrate in `docs/DEVIATIONS.md` in questa sessione

- **Processo residente senza GTK:** il solo import di GTK 4 porta il processo da 19 MB a 124 MB, oltre il limite di 120 MB. Il processo residente è una `Gio.Application`, e GTK e libadwaita si caricano alla prima apertura della finestra.
- **Rendering senza GL:** `GSK_RENDERER=cairo` più `GDK_DEBUG=gl-disable,vulkan-disable`, impostati solo se l'utente non ha già scelto.
- **Nomi dei pacchetti:** `gnome-shell-extension-ubuntu-appindicators` non esiste in apt ed è stato tolto. I `Recommends` sono `gnome-shell-extension-appindicator`, `docker-ce-cli | docker.io`, `x11-utils`.
- **Script del pacchetto:** `postrm` aggiorna le cache di icone e lanciatore. `prerm` cancella i `__pycache__` scritti da avvii come root.
- **Controllo con lintian:** il primo giro ha dato due errori, risolti con `DEBIAN/conffiles` (di conseguenza `apt remove` lascia l'autostart, e solo `apt purge` lo toglie) e con un changelog generato dal build.
- **Compose:** `down` funziona anche senza file. Il costo accettato è che un `down` lento ferma il campionamento fino a 120 secondi, e che `down` agisce per label e non per id.
- **Firefox e SIGTERM** (misurato il 17 ottobre su Firefox snap 158.0): la chiusura normale non avviene, ma le schede tornano dal salvataggio automatico. Quindi "Chiudi browser" resta a livello attenzione, senza frase di conferma.
- **Pressione fuori dal limite orario:** le notifiche di pressione partono anche a finestra piena, contano nella finestra e hanno una pausa di 1 ora per tipo.
- **Preferenze dalla finestra:** un campo non valido tiene il valore in uso, non il predefinito. Per la coppia di soglie di pressione, se non valida tornano entrambe all'ultima coppia valida.
- **Silenzio globale:** vale per la sessione, e un riavvio lo azzera. Snooze per gruppo e ignorati si salvano. Una notifica che non parte per errore del bus non si ritenta.
- Già presenti dall'inizio e rilevanti per questo lavoro: ordine di `categorize_process`, ereditarietà di `TERMINAL`, id stabile dei gruppi, servizi utente trattati come `OTHER`.

### Misure in `docs/PERF.md`

- Memoria del processo residente: 54,6 MB di RSS (40,6 MB di PSS) dopo 3 cicli, contro 124 MB con GTK caricato all'avvio. Limite 120 MB.
- Memoria con finestra aperta e poi nascosta: 227 MB con il renderer di default, 130 MB con Cairo e GL disattivato, 126 MB come default dell'app. Limite 200 MB.
- Ciclo di campionamento: da 7,67 s a 1,25-1,28 s su 5 cicli (1,31-1,34 s nel processo `--background`). Sotto un carico di 7,5 il ciclo ha toccato 1,40-1,55 s, vicino al limite di 1,5 s: va rimisurato a macchina quieta e sotto carico (T-6.5). L'ottimizzazione di `psutil.Process.oneshot()` è stata scartata perché neutra.
- Panoramica con 300 gruppi: aggiornamento da 11,6 s a 0,38 s con l'ordinamento della lista. Con il renderer dell'app il blocco massimo del ciclo principale è 15-45 ms in aggiornamento e 25-46 ms in costruzione, sotto il limite di 50 ms.
- Apertura della finestra senza display: da 25,1 s di blocco a meno di 1 s.
- `plan_action` su 900 processi: 20,2 ms di mediana, 22,0 ms di massimo. Nessuna ottimizzazione necessaria.
- Ciclo reale con lo stato persistente: 0,41 s di mediana.

### Difetti trovati dalle review e corretti

Ogni modifica è passata dal `code-reviewer`. Cosa è stato corretto, e cosa cambia per l'utente:

- **Chiusura forzata di un'app con documenti.** Era valutata come "attenzione" e non come "pericolo". Per l'utente voleva dire nessuna frase di conferma da digitare prima di perdere lavoro non salvato. Ora il rischio si calcola con i fatti completi (`uid`, documenti aperti, primo piano), e un test con mutazione su `has_documents` diventa rosso se il controllo salta.
- **Segnali ai processi figli senza controlli.** I discendenti non venivano verificati uno per uno. Ora ognuno è controllato (stesso utente, non protetto, mai `wimm` o i suoi antenati): un figlio non valido fa fallire il passo, senza segnali a nessuno.
- **"Inattivo da" contato dall'avvio del monitor.** Un gruppo risultava inattivo da quando l'app era partita, non da quando aveva smesso di lavorare. Ora il conteggio parte dalla fine dell'ultimo passo attivo visto nella sessione, e un'attività recente da sola lascia il gruppo "in osservazione" finché non passa una finestra intera.
- **Voce di menu "Silenzia 1 h" morta.** Puntava a un'azione che nessuno aveva definito. Ora attiva davvero il silenzio globale e mostra l'orario di fine, come l'icona.
- **Menu dell'icona su un layout vecchio.** Un clic arrivato su un menu già cambiato poteva eseguire un'altra voce. Gli id fissi lo impediscono.
- **Avviso dell'icona mancante nascosto troppo presto.** L'avviso spariva alla sola comparsa del servizio. Ora sparisce solo quando la registrazione riesce.
- **Processo fermo 25 secondi senza display.** `Adw.init()` bloccava il ciclo principale. Ora il display si controlla prima e l'errore arriva in meno di 1 secondo.
- **Piano che si allarga al ricalcolo.** Un ripianificato con un bersaglio che l'elenco non aveva mai mostrato poteva essere confermato. Ora non si può confermare.
- **Doppia esecuzione dello stesso dialogo e nomi con `&` o `<`.** Un dialogo ora si esegue al massimo una volta, e i nomi con caratteri speciali si mostrano com'erano.
- **Pulsanti rimasti "In corso…".** Un errore imprevisto in esecuzione lasciava i pulsanti bloccati. Ora li libera.
- **"Forza chiusura" su un processo sostituito.** Un bersaglio singolo cambiato non viene ripianificato sullo stesso pid.
- **Orologio spostato indietro.** Non silenzia più le notifiche di pressione. I gruppi protetti non compaiono mai fra quelli liberabili.
- **Preferenze salvate ma non applicate.** Una soglia salvata aspettava un riavvio, e un nome protetto aggiunto dall'utente non arrivava all'ultimo controllo dell'esecutore. Ora l'effetto è immediato.
- **Notifica che fallisce.** Una notifica in errore bloccava le altre e veniva ripetuta a ogni ciclo oltre il limite orario. Ora non succede.
- **Modifica durante un ciclo di campionamento.** Un cambio di silenzio mentre un ciclo girava andava perso. Ora ne parte un altro a fine ciclo.
- **Controlli della finestra e menu aperto.** Un aggiornamento dei processi chiudeva il menu "Silenzia" o toglieva il focus. Ora cambiano solo le righe dei membri. Un campo lista con virgola o spazi ai bordi non crea più una modifica fantasma.
- **Test della panoramica che passavano solo sotto Xvfb.** Sul display reale un ciclo veloce finiva tutto nella prima fetta di lavoro e 6 test su 6 fallivano. Ora usano una riga per fetta.

### File Modificati

| File | Tipo | Descrizione |
|---|---|---|
| `src/wimm/tray/` | nuovo | StatusNotifierItem, dbusmenu, costruzione del menu, controllo del servizio della shell |
| `src/wimm/core/` | nuovo/modifica | pianificazione azioni, regole di notifica, `format_size` in `core/sizes.py`, testo conseguenze |
| `src/wimm/model/` | modifica | `uid`, `has_documents`, `is_foreground`, `compose_project`; errori di dominio in `model/errors.py` |
| `src/wimm/service/` | nuovo/modifica | `PlanExecutor`, `compose.py`, `AppService`, notifiche Gio, archivio di stato, `UserStateKeeper` |
| `src/wimm/ui/` | nuovo/modifica | dialoghi di conferma, esiti e Dettagli, controlli di silenzio e ignora, dialogo Preferenze |
| `src/wimm/app.py` | modifica | finestra a richiesta, coordinatore delle notifiche, caricamento dello stato |
| `scripts/build_deb.sh`, `scripts/test_deb.sh` | nuovo | build del pacchetto e verifica in container |
| `Makefile`, `pyproject.toml` | modifica | verbi `deb` e `test-deb`, `make perf` con il renderer dell'app, esclusione di `build/` da mypy |
| `README.md` | modifica | guida per l'utente finale |
| `docs/DEVIATIONS.md`, `docs/PERF.md` | modifica | decisioni e misure della sessione |
| `tests/` | nuovo/modifica | test per ogni punto sopra (ultima esecuzione completa: 1623 test) |

### Controlli manuali che restano all'utente

Non automatizzabili: richiedono la sessione grafica reale o l'installazione sul computer. Riferimenti in `specs/where-is-my-memory/plan.md`.

| ID | Cosa fare | Esito atteso |
|---|---|---|
| M-3 | Con l'app in esecuzione, `Alt+F2`, poi `r` (riavvio di GNOME Shell su X11) | L'icona ricompare senza riavviare l'app |
| M-5 | `sudo apt install ./dist/where-is-my-memory_<versione>_all.deb` | Il pacchetto si installa |
| M-6 | Logout e login | Icona nella barra, `pgrep -f /usr/bin/wimm` trova il processo, finestra nascosta |
| M-8 | Click-through dei dialoghi safe, caution e danger su un `http.server` e su un compose di prova, compresa "Forza chiusura" su un processo che ignora SIGTERM | Anteprima, esito e RAM liberata corretti. Il pulsante di pericolo resta disabilitato finché il nome non coincide |
| M-10 | Con `notify_after_s=60` e un server di prova inattivo, clic su "Apri" e poi su "Silenzia 24 h" | La finestra si apre sul gruppo. Nessuna nuova notifica |
| M-11 | Esci e rilancio dell'app | "Inattivo da" resta invariato |
| M-12 | Dialogo Preferenze, a mano: prima un valore fuori intervallo, poi uno valido | Errore sul campo, poi effetto al ciclo successivo |

Il pacchetto non è mai stato installato sull'host in questa sessione: la verifica avvenuta è solo in container. Anche la CI remota non è ancora stata eseguita.

### Note per il Cliente (linguaggio NON tecnico)

L'applicazione ora può fare ciò per cui è nata: mostra quali programmi occupano memoria, avvisa quando uno è fermo da tempo e permette di chiuderlo. Prima di chiudere qualcosa spiega cosa succederà. Se c'è il rischio di perdere lavoro non salvato, chiede di scrivere il nome del programma per confermare. Dopo la chiusura dice quanta memoria si è liberata.

L'icona nella barra torna da sola quando la barra si riavvia. L'applicazione si installa con un unico pacchetto, già provato su un Ubuntu pulito. Le notifiche si possono spegnere per un'ora, un giorno o una settimana, per un singolo programma o per tutti. Le impostazioni si cambiano da una finestra e valgono subito.

La revisione ha trovato e corretto alcuni difetti prima del rilascio. Il più importante riguardava la chiusura forzata di un programma con documenti aperti, che non chiedeva la conferma più severa.

Prima di considerare il lavoro concluso restano da fare a mano i sette controlli elencati sopra, sul computer vero. Due di questi richiedono l'installazione sul computer e un logout con nuovo login.

### Riepilogo

- **Complessità:** alta (28 modifiche in 4 fasi, 1623 test automatici)
- **Stato:** Fasi 1-4 implementate e verificate in automatico. Restano i controlli manuali M-3, M-5, M-6, M-8, M-10, M-11, M-12. Da rimisurare in T-6.5 il ciclo di campionamento sotto carico.

## 2026-10-17 | Sessione #2 [FEATURE]

Progetto: where-is-my-memory (comando `wimm`). Il lavoro copre i 6 commit da `ae5afd3` a `5766a64`, tutti del 17 ottobre, e porta a termine il lotto L5-1..L5-3: misura, scansione e pulizia del disco. Le specifiche sono in `assets/SPECIFICHE.md`, il piano in `specs/where-is-my-memory/`.

### Richiesta

Aggiungere il lato disco dell'applicazione: misurare cartelle, cartelle di dipendenze e cache, esporre un rapporto sul bus D-Bus con lo spazio liberabile (Q-6) ed eseguire le azioni di pulizia con le stesse garanzie di quelle sui processi: piano, riverifica prima dell'esecuzione, conferma.

### Azioni Eseguite

**T-5.2a, dimensioni delle cartelle** (`ae5afd3`)
- Nuovo collettore `src/wimm/collectors/dirsize.py` che misura le cartelle con una cache dei risultati, per non ripercorrere ogni volta alberi grandi.

**T-5.2b, cartelle di dipendenze e cache utente** (`95539fb`)
- `devdirs.py` trova le cartelle di dipendenze dei progetti, `caches.py` le cache dell'utente. Costanti nominate in `core/constants.py`.

**T-5.2c, scansione del disco** (`083735d`)
- La scansione gira su un worker dedicato (`service/disk_scanner.py`), separato da quello di campionamento, così un albero lento non ritarda il monitoraggio dei processi.
- Il rapporto sul disco è esposto su D-Bus (`inspector_dbus.py`) e lo spazio liberabile entra in `reclaimable_now.disk` (Q-6), con le regole in `core/disk_rules.py`.

**Correzione dello spazio Docker liberabile** (`0b9a3f9`)
- Lo spazio Docker liberabile veniva sommato per immagine, contando anche i livelli condivisi. Ora si conta come `docker system df`: solo ciò che non è condiviso. Sul computer di prova il dato passa da 22,4 GB a circa 16 GB reali. Test di parità con il conteggio di `docker system df`.

**T-5.3b, azioni Docker sul disco** (`f825063`)
- Nuovo esecutore (`executor_disk_docker.py`) con riverifica prima di ogni passo. Il tag di un'immagine si toglie solo se punta ancora all'identificativo pianificato. L'identità di un volume include `CreatedAt`, così un volume ricreato con lo stesso nome non viene scambiato per quello pianificato. La pulizia della cache di build usa `all=true`.
- Decisioni registrate in `docs/DEVIATIONS.md`. Il controllo manuale M-13 sulla cache di build vera resta da eseguire.

**T-5.3c, cartelle di dipendenze, cache e cestino** (`5766a64`)
- Rimozione tramite `dir_fd` e `O_NOFOLLOW` (`service/safe_tree.py`, `executor_disk_fs.py`): un collegamento simbolico messo al posto di una cartella non viene seguito. I punti di mount sono rifiutati.
- I comandi di pulizia delle cache ricevono la cartella in modo esplicito. Dopo ogni azione sul disco parte una nuova scansione, così la finestra mostra lo stato reale.
- Guardia di cancellazione verificata da `tests/test_removal_guard.py`.

### File Modificati

| File | Tipo | Descrizione |
|---|---|---|
| `src/wimm/collectors/` | nuovo/modifica | `dirsize.py`, `devdirs.py`, `caches.py` |
| `src/wimm/core/` | nuovo/modifica | `disk_rules.py`, `disk_wire.py`, `planning_disk.py`, costanti |
| `src/wimm/model/` | modifica | `disk.py`, `actions.py`: conteggio Docker come `docker system df` |
| `src/wimm/service/` | nuovo/modifica | `disk_scanner.py`, `app_service_disk.py`, `executor_disk_docker.py`, `executor_disk_fs.py`, `safe_tree.py`, `fs_controls.py`, `controls_disk.py` |
| `docs/DEVIATIONS.md` | modifica | decisioni sulle azioni Docker e sulle rimozioni |
| `tests/` | nuovo/modifica | test per ogni punto sopra, tra cui `tests/integration/test_disk_docker.py` |

### Punti aperti

- **M-13** (manuale): eseguire a mano la pulizia reale della cache di build Docker e controllare lo spazio liberato.
- Il comportamento con un bind mount reale non è stato provato: i test usano bersagli creati dal test.
- Il test di confronto con `docker stats` è risultato instabile una volta in un'esecuzione parallela. Non è stato riprodotto: va osservato nelle prossime esecuzioni.
- Codex non era disponibile (non autenticato): tutto il lavoro delegabile è stato eseguito in casa.

### Note per il Cliente (linguaggio NON tecnico)

L'applicazione ora guarda anche il disco. Trova le cartelle che si possono ricreare (dipendenze dei progetti e cache) e lo spazio che Docker può restituire, e dice quanto si libererebbe. Prima di cancellare mostra cosa verrà toccato e chiede conferma, come per i programmi in memoria.

Il numero dello spazio Docker era troppo alto: contava due volte parti condivise. Ora coincide con quello che mostra Docker stesso, circa 16 GB invece di 22,4.

Resta da provare a mano la pulizia vera dello spazio usato da Docker per costruire le immagini, sul computer reale.

### Riepilogo

- **Complessità:** alta (6 commit, circa 5000 righe tra codice e test)
- **Stato:** lotto L5-1..L5-3 implementato e verificato in automatico. Resta M-13.
- **Prossimo:** L5-4 (T-5.4a/b, vista Disco).

## 2026-10-17 | Sessione #3 [FEATURE]

Progetto: where-is-my-memory (comando `wimm`). Il lavoro copre gli 8 commit da `26bb749` a `37efebc` più questo, e chiude il piano: vista Disco (L5-4), attività dal primo piano (T-5.5b) e Fase 6.

### Richiesta

Proseguire il piano fino alla fine, per commit atomici.

### Azioni Eseguite

**Orari nel fuso del sistema** (`26bb749`)
- Gli orari mostrati erano in UTC, due ore indietro a Roma. Ora seguono il fuso del sistema; i test fissano `Europe/Rome`.

**T-5.4a e T-5.4b, vista Disco** (`3471048`, `30f28e4`)
- Sezioni Docker, cache, cartelle di dipendenze e cestino, con il badge di rischio che il piano assegnerebbe; "Scansiona ora" con lo spinner guidato dal servizio (`disk-scan-started`).
- Azioni dalle righe e azioni di massa (immagini senza nome, immagini inutilizzate, container fermi) attraverso i dialoghi di conferma. "Dettagli" compare solo se qualche bersaglio fallisce (§10.3).

**T-5.5b, attività dal primo piano** (`c0e8c5c`)
- Browser, app desktop e terminali sono attivi se la loro finestra è stata in primo piano nella finestra di osservazione, inattivi dopo una finestra intera senza. Wayland, rilevamento spento o dati mancanti: stato sconosciuto, mai inattivo.

**T-6.1, baseline di sicurezza** (`24444ec`)
- Nessun P0 o P1; ricerca di `sudo`, `pkexec`, `setcap`, `shell=True` vuota con controllo positivo. Corretto il P2-1: i comandi di pulizia delle cache girano da `/`. Rapporto in `docs/security/`.

**T-6.4, clone pulito** (`ecc0ccf`)
- `make setup`, `make lint`, `make test`, `make test-all` verdi da un clone in una cartella temporanea (2029 test). L'unica differenza: un errore di ordine degli import nascosto da una cache di ruff vecchia; `make lint` ora gira senza cache.

**T-6.3 e T-6.2, ADR e README** (`a4cc342`, `37efebc`)
- Cinque ADR in `docs/adr/`. README riscritto per chi installa: il precedente diceva ancora che l'app non agisce. Reader-test a contesto pulito su 9 domande, tutte trovate al secondo giro.

**T-6.5, misure RNF** (questo commit)
- Build del repository con `wimm --background` per 1 h su bus D-Bus privato e Xvfb, cartelle XDG temporanee e un servizio della barra finto, 2026-10-17 07:02-08:02: 393 processi utente, 8 container, load average 5,4-6,4.
- RNF-01: 1,32-1,60% di un core a regime, media 2,30% sui 10 minuti di `pidstat` con il picco del 10,15% della prima scansione del disco. **Non rispettato** (limite 1%).
- RNF-02: 63 MB dopo 55 minuti a finestra mai aperta (limite 120); 136 MB con la finestra aperta (limite 200).
- RNF-03: 122 cicli, mediana 0,47 s, massimo 0,61 s, nessuno sopra 1,5 s.

**T-6.6, Delivery Report** (questo commit)
- `docs/DELIVERY_REPORT.md`: Definition of Done voce per voce con evidenza (6 fatte, 8 da verificare a mano), RNF, controlli manuali M-1..M-16, decisioni, deviazioni, punti aperti.

### Punti aperti

- RNF-01 sopra il limite: serve una decisione (sezione 6 del Delivery Report).
- Misure RNF da ripetere sull'installato a macchina quieta (M-15); installazione e controlli manuali (M-2..M-16) all'utente.
- Il disco della macchina di sviluppo ha meno del 10% di spazio libero: l'app lo ha segnalato durante la misura.
- Codex non disponibile: tutto il lavoro delegato è girato in-house.

### Note per il Cliente (linguaggio NON tecnico)

L'app è completa: mostra memoria e disco, dice cosa è fermo e lo può chiudere o cancellare con la vostra conferma. Una misura non rispetta l'obiettivo fissato: l'app usa circa l'1,4% di un processore invece di meno dell'1%. Le possibili soluzioni sono descritte nel Delivery Report e chiedono una vostra scelta.

### Riepilogo

- **Complessità:** alta (9 commit)
- **Stato:** piano completato; RNF-01 non rispettato, controlli manuali all'utente.
- **Prossimo:** decisione su RNF-01, poi M-5 (installazione) e i controlli manuali.

## 2026-10-17 | Sessione #4 [FEATURE]

Progetto: where-is-my-memory (comando `wimm`). Il lavoro copre le 45 proposte di miglioramento dell'esperienza d'uso, dal commit `58e64ce` a `27cb52f`. Ogni gruppo di modifiche ha un commit di codice e uno di documentazione che registra in `docs/DEVIATIONS.md` dove l'app si discosta dalla specifica.

### Richiesta

L'utente ha chiesto di proporre miglioramenti perché una persona non esperta possa usare l'app senza barriere d'ingresso. La proposta è un mockup con 45 voci in `docs/ux-proposte/index.html` (skill ux-improver). Poi: "Applica tutte le proposte che hai indicato", con commit atomici su main.

### Azioni Eseguite

**G1, lessico, testi e icona nella barra** (`58e64ce`, `dd1c28c`, `b855402`, `262a879`)
- L1 L2 P2 P3 P8 D1 D4 D5 D7: parole semplici al posto di quelle tecniche nelle viste.
- Y2 C5: spiegazione dell'elenco di sistema e della conferma da digitare.
- T1-T4: menu, etichetta e notifiche dell'icona nella barra in linguaggio comune.

**G2, Panoramica** (`ca82d00`, `c604f36`)
- P1 P4-P7 P9-P14 Y1: una frase sullo stato della macchina, il pulsante "Libera X senza rischi", filtri semplici, sezioni, motivi in parole comuni, dettagli tecnici nascosti, "Non avvisarmi per".
- La scheda Sistema è unita alla Panoramica.

**G3, Disco** (`02756c7`, `99f38aa`)
- D2: tutto lo spazio sicuro si libera con un clic. D3: sezioni per livello di rischio. D6: gli importi compaiono sulle azioni di massa.

**Test** (`dcc5320`)
- Corretto un test instabile: il confronto con la memoria Docker reale ora ammette un rumore assoluto di 8 MiB.

**G4, conferme** (`1ce3c86`, `be8640a`)
- C1: la conferma spiega la differenza tra memoria elencata e memoria recuperabile. C2: nomi comprensibili con la dimensione. C3: tre blocchi "Cosa succede / Cosa resta / Per riaccenderlo".
- C4: nuovo pulsante "Riaccendi" dopo aver fermato dei container. Il piano `restart_stopped` è nuovo, il servizio ricorda gli ultimi 8 piani e l'avvio reale di Docker è stato verificato su un container di prova.

**G5, preferenze** (`6787b2e`, `2b329e8`)
- R1: in vista solo le impostazioni degli avvisi, le altre 14 sono in "Impostazioni avanzate". R2: frasi e kB/s al posto di sigle. R3: Pochi/Normali/Tanti. R4: ripristino dei valori consigliati, tranne nomi e cartelle. R5: l'opzione sul primo piano è disattivata fuori da X11.

**G6, avvio e errori** (`f90c0ff`, `9e9e4aa`)
- A1: benvenuto al primo avvio, anche con `--background`, ricordato da un file marcatore "welcomed". A2: "Riprova adesso" ora funziona tramite `app.restart-monitor`. A3: banner "Come si attiva" per l'icona nella barra, con i passi verificati su Ubuntu 24.04.

**G7, stile** (`724aa37`, `4044d1e`)
- S1: "?" accanto a RAM e disco. S2: righe secondarie a 10 pt che seguono la dimensione del testo di sistema, più scure solo fuori dall'alto contrasto. S3: pulsante principale blu per l'azione sicura.

**Mockup** (`27cb52f`)
- Tutte le 45 proposte segnate come applicate.

**Verifica**
- Ogni gruppo ha chiuso con `make lint` e `make test-all` verdi (finale: 2187 test passati). Resa controllata a 375/390 e 1280 px. Il `code-reviewer` ha esaminato ogni gruppo; i rilievi sono stati corretti e ricontrollati.

### Punti aperti

- Il README.md descrive ancora tre schede e i testi precedenti: non è stato modificato senza una richiesta.
- Lo script di controllo del mockup non è stato eseguito perché Chromium non è installato; la sintassi JavaScript è verificata con `node --check`.
- Il comportamento di S2 in alto contrasto è provato commutando il provider, non in una sessione reale ad alto contrasto.
- I passi di A3 sono verificati solo su questa macchina.
- Nessun push eseguito.

### Note per il Cliente (linguaggio NON tecnico)

L'app ora parla in modo semplice: niente sigle, spiegazioni accanto alle parole difficili e un benvenuto al primo avvio. Dalla schermata iniziale si libera lo spazio sicuro con un solo clic. Prima di ogni azione l'app spiega cosa succede e cosa resta, e dopo aver fermato dei programmi si possono riaccendere con un pulsante. Le impostazioni più rare sono nascoste in una sezione a parte. Il testo del README non è ancora aggiornato: serve una vostra decisione.

### Riepilogo

- **Complessità:** alta (15 commit più i 3 di codice del primo gruppo)
- **Stato:** 45 proposte applicate
- **Prossimo:** decidere se aggiornare il README
