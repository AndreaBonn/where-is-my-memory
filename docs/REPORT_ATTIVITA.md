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


## 2026-10-17/18 | Sessione #5 [FEATURE]

Progetto: where-is-my-memory (comando `wimm`). Il lavoro copre 12 commit, dal piano `812e47e` alla documentazione `9c21a3d`, e introduce l'interfaccia bilingue italiano e inglese.

### Richiesta

L'utente ha chiesto l'interfaccia in due lingue, italiano e inglese. Il piano `specs/i18n/plan.md` è stato approvato con queste scelte: gettext con l'italiano come msgid, selettore a bandiere nelle Preferenze, cambio lingua immediato con ricostruzione della finestra, lingua iniziale presa dal locale di sistema.

### Azioni Eseguite

**Piano** (`812e47e`)
- `specs/i18n/plan.md` con le sei fasi F1-F6.

**F1, infrastruttura gettext** (`fa0c1ef`)
- Infrastruttura gettext, campo `Config.language`, target `make po` e `make mo`. Il pacchetto `.deb` compila il catalogo.

**F2-F5, testi tradotti** (`30618a6`, `0873cad`, `282dfbc`, `c09f81f`, `cc13267`)
- F2: testi ed errori del core.
- F3: dialoghi, Preferenze e pulsanti delle azioni.
- F4a e F4b: finestra principale, pagina Disco, widget, pagine e struttura della finestra.
- F5: icona nella barra, notifiche, messaggi di configurazione e aiuto della riga di comando.

**F6, selettore e cambio immediato** (`357b669`)
- Selettore a bandiere nelle Preferenze e azione `win.set-language`, che ricostruisce la finestra senza riavvio. Le azioni esportate su D-Bus restano invariate.

**Controlli e correzioni** (`df35c43`, `bd9b317`, `834248e`)
- `scripts/check_i18n.py` è entrato in `make lint`: segnala testi non marcati e traduzioni mancanti.
- In inglese le date brevi mettono il mese per primo.
- I testi di GTK e libadwaita ora seguono la lingua scelta tramite `LANGUAGE`. Il difetto è emerso dal test che percorre l'app in inglese e controlla il testo reso a schermo.

**Documentazione** (`9c21a3d`)
- `docs/DEVIATIONS.md` e `CLAUDE.md` descrivono l'interfaccia bilingue e le sue convenzioni.

**Verifica**
- `make test-all`: da 2187 test passati (base di partenza) a 2420. Copertura del core 99,56%.
- Circa 530 msgid in `po/en.po`, nessuno senza traduzione; `check_i18n` non segnala problemi.

**Effetto collaterale sull'italiano**
- I plurali ora passano da `ngettext`: "1 giorni" e "1 volte" sono diventati "1 giorno" e "1 volta".

### Punti aperti

Limiti noti, annotati anche in `docs/DEVIATIONS.md`:
- I file `.desktop` e metainfo seguono il locale di sistema, non la lingua scelta nell'app.
- Se un'azione è in corso durante il cambio lingua, perde il messaggio di esito.
- Le modifiche alle Preferenze non applicate vengono scartate alla riapertura.
- Con un locale C/POSIX i testi propri di GTK restano in inglese.

Non verificato: l'app reale avviata con `make run` su uno schermo vero. Il test completo usa la finestra, le Preferenze e le azioni reali con un servizio finto.

Nessun push eseguito.

### Note per il Cliente (linguaggio NON tecnico)

L'app si può usare in italiano o in inglese. La lingua si sceglie dalle Preferenze toccando la bandiera e cambia subito, senza riavviare. Alla prima apertura l'app usa la lingua del computer. In italiano è stato corretto anche un dettaglio: ora si legge "1 giorno" e non più "1 giorni". Alcuni testi del sistema, come il nome mostrato nel menu delle applicazioni, seguono ancora la lingua del computer e non quella scelta nell'app. Non abbiamo ancora provato l'app aperta su uno schermo reale, solo con prove automatiche.

### Riepilogo

- **Complessità:** alta (12 commit)
- **Stato:** interfaccia bilingue completata e verificata con test automatici; avvio reale con `make run` non verificato.
- **Prossimo:** provare l'app con `make run` su uno schermo reale.


## 2026-10-18 | Sessione #6 [FEATURE]

Progetto: where-is-my-memory (comando `wimm`). Il lavoro copre 18 commit, dal piano `d40bd18` alla misura dell'apertura della finestra `0cc31ac`, con workflow RPI sul piano `specs/001-product-gaps`. Chiudono il lotto L1 e quasi tutto il lotto L2.

### Richiesta

L'utente ha chiesto un audit di prodotto e l'esecuzione del piano che ne deriva, con workflow Research, Plan, Implement.

### Azioni Eseguite

**Audit e piano** (`d40bd18`)
- Audit di prodotto con 17 proposte (F1-F17). Il piano `specs/001-product-gaps/plan.md` le raggruppa in 12 lotti (L1-L12).
- L'architect ha dato rilievi su tre punti: ADR-006 su Wayland, motori container, distribuzione. Il security-reviewer ha elencato 18 rilievi (S1-S18).
- Decisioni: le domande Q1-Q7 seguono il default proposto. La Q8 (URL della homepage e del bug tracker) è aperta, quindi il task T025 è sospeso.

**L1, primo avvio senza configurazione** (`670c590` ... `c3181fc`)
- Le radici dei progetti si rilevano in automatico sotto la home (`d09e8e3`, `f42d904`, `47e9021`, `e4b6244`) invece di usare il percorso personale dell'autore. Il riconoscimento dei progetti include Rust, Go, Java e Gradle (`afd05a1`).
- Una cartella di progetto mancante genera un avviso e uno stato vuoto con il pulsante "Scegli una cartella" (`bd7c20c`).
- Fuori dalle locali italiane l'interfaccia parte in inglese (`f031619`).
- Le cartelle di dipendenze ricostruibili sono classificate per ecosistema, con marker per Rust, Java, Gradle e Next (`cad1cca`, `35f9f5c`). Sulla home reale le cartelle trovate passano da 76 a 88, con un aumento di durata del 3% (`1e0d9ef`, `docs/PERF.md`).
- La conferma di pulizia mostra il comando di ricostruzione.
- `docs/DEVIATIONS.md` registra radici rilevate, inglese predefinito e nuove cartelle (`c3181fc`).

**L2, qualità e distribuzione** (`0581767`, `63afd9c`, `928d839`, `0cc31ac`)
- `make audit` esegue bandit e pip-audit ed è in CI.
- Il pacchetto `.deb` include la pagina di manuale di `wimm`.
- Misura dell'apertura della finestra: 236 ms alla prima apertura, 10 ms alla riapertura. Le voci M-17..M-23 dei controlli manuali sono elencate.
- T025 resta sospeso in attesa della Q8.

**Problemi trovati e corretti in corsa**
- pip-audit come dipendenza di sviluppo portava `requests` 2.34 nel venv e rompeva `python3-docker`: in sviluppo Docker risultava non disponibile. Bandit e pip-audit ora girano in ambienti `uvx` isolati, con un test di guardia (`928d839`).
- Nel click-through reale il pulsante "Scegli una cartella" selezionava tutto il testo, e il primo tasto premuto cancellava le cartelle salvate. Corretto.
- Il controllo delle radici mancanti faceva I/O sul thread della UI a ogni snapshot. Ora a ogni snapshot si confronta solo l'elenco salvato, senza toccare il disco; la verifica delle cartelle avviene solo dopo una scansione o un cambio delle preferenze.
- Dalla review di sicurezza di L1 (nessun P0 o P1): `user-dirs.dirs` letto senza seguire link e con un limite di dimensione, mount di rete esclusi prima di ogni accesso al disco, cartella documenti nascosta (per esempio `~/.cargo`) rifiutata come radice.

### Punti aperti

- Pre-esistente, fuori scope, non corretto: a 375 px il banner "L'icona nella barra richiede l'estensione AppIndicator" copre l'intestazione della vista Disco e il pulsante "Controlla ora".
- Q8 aperta: servono l'URL della homepage e quello del bug tracker per chiudere T025.

### Note per il Cliente (linguaggio NON tecnico)

Al primo avvio l'app trova da sola le cartelle dei progetti, senza bisogno di indicare un percorso. Se una cartella non esiste più lo segnala e propone di sceglierne un'altra. Fuori da un computer in italiano l'app si apre in inglese. Riconosce più tipi di progetto (Rust, Java, Gradle, Next) e li propone per la pulizia, mostrando anche il comando per ricostruire ciò che viene eliminato. L'app si apre in circa un quarto di secondo la prima volta e quasi subito le volte successive. Durante le prove è stato corretto un difetto che, scegliendo una cartella, poteva cancellare quelle già salvate. Resta da sistemare un banner che su schermi molto stretti copre un pulsante.

### Riepilogo

- **Complessità:** alta (18 commit)
- **Stato:** L1 completato; L2 completato tranne T025 (sospeso per la Q8).
- **Prossimo:** lotto L3 (cache degli sviluppatori), poi L4-L12.


## 2026-10-18 | Sessione #7 [FEATURE]

Progetto: where-is-my-memory (comando `wimm`). Il lavoro copre i 38 commit da `ecfc4f0` a `2fcc84a` e prosegue il piano `specs/001-product-gaps` (workflow RPI) dal lotto L5 al lotto L12. Il registro dei task chiusi è nel blocco "Avanzamento" di `specs/001-product-gaps/tasks.md`.

### Richiesta

Continuare l'esecuzione del piano dei gap di prodotto: dopo L1-L4, portare a termine i lotti L5-L12 con commit atomici, review a ogni blocco e click-through reale per le parti con interfaccia.

### Azioni Eseguite

**L5, memoria del kernel, memoria video, PSI e OOM** (`ecfc4f0` ... `73a174f`)
- Il dettaglio della RAM mostra le voci di memoria del kernel. La quota "Non attribuita" sul computer di prova scende da 1,30 a 0,32 GiB.
- Memoria video letta da GPU NVIDIA e AMD. Regola di pressione basata su PSI. Il contatore `oom_kill` genera una notifica quando il kernel chiude programmi per mancanza di memoria; l'aumento è stato provato dal vivo (da 6 a 7).
- Schema dello snapshot portato a 3 (`memory.video`). Il ciclo di campionamento passa da 0,52 a 0,56 s, nel rumore.

**L6, cache degli strumenti di intelligenza artificiale e Android** (`3711b4d`, `cdd104d`)
- Misura e pulizia delle cache di HuggingFace, ollama, emulatori e SDK Android.
- La pulizia dei modelli ollama è bloccata finché `ollama serve` è in esecuzione. Se gli argomenti del processo non si leggono, il blocco resta.

**L7, cartelle di progetto fuori dalla home** (`63e3387` ... `d059b23`)
- ADR-007 accettato dall'utente: la home resta ammessa per intero come radice. Una regola pura decide quali radici esterne sono ammesse, e la stessa regola vale per la scansione e per la cancellazione.
- Le radici rifiutate restano visibili nelle Preferenze con il motivo. `/` non è mai un progetto.

**L8, sessioni SSH e crescita della memoria** (`7a59042`, `f14c47a`, `047b095`)
- I programmi avviati via SSH si possono gestire solo con un'opzione, spenta in origine.
- Storico di 3 ore per gruppo e rilevazione della crescita sostenuta, con soglia di rumore a 32 MiB. Nello snapshot (schema 4) compare il campo `growth`, mostrato come "+620 MB in 2 h".

**L9, stato da riga di comando** (`84fe29c`, `e2b6eeb`, `029365c`)
- `wimm status` mostra lo stato senza finestra, provato senza display contro un'istanza reale.
- Correzione della redazione nell'Inspector D-Bus: nomi, percorsi e alias di password sono oscurati.

**L10, comando di riavvio** (`30d2c73`)
- Dopo l'arresto di programmi l'interfaccia offre "Copia comando di riavvio".

**L11, Wayland con estensione GNOME** (`8dc45e1`, `316191c`, `1437c32`, `2fcc84a`)
- ADR-006: un adattatore per compositor per il programma in primo piano. L'estensione GNOME è facoltativa, supporta solo la shell 46 e pubblica il pid della finestra attiva. Il collector Wayland verifica il proprietario del dato. L'estensione è inclusa nel .deb.

**L12, pacchetti Arch e Fedora** (`2098ee4`, `5d033a6`, `eb76bfa`)
- PKGBUILD per Arch e spec RPM per Fedora, provati in container. Il banner sull'icona nella barra spiega i passi per la distribuzione in uso (Fedora, Arch, Debian) e ripiega su `/usr/lib/os-release`.

**Difetti reali trovati dalle review o dai click-through, e corretti**
- **Collegamenti simbolici nelle cache:** un link messo sul percorso predefinito rendeva pulibile una destinazione imprevista. Ora è rifiutato.
- **Progetti Cordova pulibili:** i marcatori dell'SDK Android erano troppo generici e `ANDROID_SDK_ROOT` poteva far trattare come SDK la cartella di un progetto Cordova. Marcatori più stretti.
- **Pagina avanzata non riaperta:** "Scegli una cartella" non riapriva la pagina se arrivava durante l'animazione di chiusura. Il test passava su Xvfb e falliva sul display reale (3 su 6); ora 6 su 6 anche sotto carico.
- **Avviso di riavvio troppo breve:** il messaggio con il comando spariva prima di poterlo usare. Corretta la durata.
- **Legenda che chiudeva l'aiuto:** la legenda si ricostruiva a ogni campione e chiudeva l'aiuto aperto. Ora non si ricostruisce.
- **`nvidia-smi` bloccato:** un driver bloccato fermava il ciclo oltre il timeout. La lettura gira ora in un thread a parte.

### File Modificati

| File | Tipo | Descrizione |
|---|---|---|
| `src/wimm/collectors/` | nuovo/modifica | memoria del kernel e video, PSI, `oom_kill`, cache AI e Android, adattatore Wayland |
| `src/wimm/core/` | nuovo/modifica | regola PSI, regola delle radici esterne, crescita sostenuta, testi dei comandi di riavvio |
| `src/wimm/service/` | modifica | storico di 3 h, blocco su `ollama serve`, radici ammesse in scansione e cancellazione, sessioni SSH |
| `src/wimm/ui/` | modifica | riepilogo RAM, radici rifiutate nelle Preferenze, banner per distribuzione, "Copia comando di riavvio" |
| `src/wimm/cli/`, Inspector D-Bus | nuovo/modifica | `wimm status`, redazione dei dati sensibili |
| `data/gnome-shell-extension/`, `packaging/` | nuovo | estensione GNOME, PKGBUILD, spec RPM, inclusione nel .deb |
| `docs/` | modifica | ADR-006 e ADR-007, `DEVIATIONS.md`, `PERF.md` |
| `specs/001-product-gaps/tasks.md` | modifica | blocco "Avanzamento" |
| `tests/` | nuovo/modifica | test per ogni punto sopra (suite finale: 3576 test passati) |

### Punti aperti

- **RNF-01 sopra il limite su questa macchina:** 1,0-1,6% di un core con circa 930 processi da censire (`docs/PERF.md`). L5-L8 stanno nel rumore rispetto a L4: il superamento dipende dal numero di processi.
- **F-PERF e F-RST:** il test del budget del censimento è fallito due volte sotto carico, il test del toast di riavvio una volta nella suite intera. Sono instabili, non indagati a fondo.
- **T025 sospeso:** mancano l'URL della homepage e quello del bug tracker (Q8).
- **README:** il testo di installazione per Arch e Fedora è stato proposto all'utente e non è stato scritto, in attesa dell'ok.
- **Pubblicazione AUR e COPR non fatta.** L'indirizzo email nel changelog RPM da rivedere.
- **Controlli manuali M-25..M-29:** richiedono la macchina reale (M-29 una sessione Wayland). Zram, AMD e `nvidia-smi` bloccato non sono provati su hardware reale. Podman e Docker Desktop non provati su macchina reale (M-24).
- **Finding parked** (vedi `tasks.md`): ollama rinominato non riconosciuto; `ANDROID_AVD_HOME` non onorato; "Puoi liberare fino a" conta anche le voci in "Attenzione"; lettura dei fatti sul thread UI non misurata; cartella con fatti illeggibili mostrata ma non scansionata; storia persa per un gruppo assente un ciclo; riga lunga del gruppo a 375 px non osservata; un'APU AMD può comparire come memoria video; euristiche PipeWire/CPU, KWin e wlroots non coperti; un motore che risponde a `info()` ma blocca `list()` costa ancora il timeout.
- Nessun push eseguito.

### Note per il Cliente (linguaggio NON tecnico)

L'app ora dà un quadro più completo: mostra anche la memoria usata dal sistema e dalla scheda video, avvisa quando il sistema chiude da solo dei programmi per mancanza di memoria e segnala quelli che crescono nel tempo. Riconosce più cartelle da pulire, comprese quelle dei modelli di intelligenza artificiale e degli strumenti Android, e rifiuta di toccarle mentre il programma che le usa è acceso. Dalla riga di comando si può leggere lo stato senza aprire la finestra. Dopo aver fermato dei programmi si può copiare il comando per riavviarli.

Sono pronti i pacchetti per Arch Linux e Fedora e un componente facoltativo per il desktop GNOME su Wayland. Non sono ancora pubblicati e non sono stati provati su computer reali con quei sistemi.

Una misura non rispetta ancora l'obiettivo: su un computer con circa 930 programmi attivi l'app usa tra l'1,0% e l'1,6% di un processore, invece di meno dell'1%. Servono i controlli a mano elencati sopra e una vostra decisione sul testo di installazione del README.

### Riepilogo

- **Complessità:** alta (38 commit, 8 lotti)
- **Stato:** lotti L5-L12 implementati e verificati in automatico (3576 test passati). RNF-01 non rispettato su questa macchina; T025 sospeso; pubblicazione AUR/COPR non fatta.
- **Prossimo:** ok dell'utente sul testo del README, controlli manuali M-25..M-29, URL della Q8.

## 2026-10-17/18 | Sessione #8 [TEST]

Progetto: where-is-my-memory (comando `wimm`). Audit di copertura e qualità dei test, seguito da rinforzo dei test, correzione dei difetti di produzione trovati e allineamento della specifica. Tutti i commit sono su main, senza push.

### Richiesta

Audit completo di copertura e qualità dei test: ogni test classificato BUONO, DEBOLE o DA_RISCRIVERE, gap analysis e piano di rimedio. Poi: rinforzare i test deboli, correggere i difetti di produzione emersi e allineare la specifica dove il codice è sensato, oppure implementare il comportamento migliore che la specifica descrive. Commit atomici su main, nessun push.

### Metodo

- Coverage di riga e di ramo.
- Worker di audit in sola lettura, uno per area.
- Mutation testing con mutanti scelti a mano, eseguiti in una copia del repository e mai nel working tree.
- Test di rimedio scritti per area e visti fallire sotto il mutante del finding che li ha motivati.
- `code-reviewer` su ogni lotto prima del commit.

### Risultati

| Misura | Prima | Dopo |
|---|---|---|
| Copertura di riga | 97,4% | 99,25% (13336 istruzioni, 100 scoperte) |
| Copertura di ramo | 94,8% | 98,6% (2750 rami, 38 scoperti) |

Suite finale: 3875 test passati, 6 deselezionati (performance e simili). `make lint` pulito (ruff, mypy su `src` e `tests`, `check_i18n`).

### Difetti di produzione corretti (un commit ciascuno)

- La nuova configurazione arriva all'esecutore anche quando il sampler fallisce.
- `--version` è riconosciuto in qualunque posizione, tranne dopo `status`.
- Una cartella `.desktop` illeggibile viene saltata, invece di far perdere l'intero indice.
- Gli id delle voci di gruppo nel menu della tray restano stabili fra un aggiornamento e l'altro (crc32 del group id, con probing sulle collisioni).
- `GetLayout` con id sconosciuto risponde con l'errore D-Bus `InvalidMenuItemId`.
- La guida dell'etichetta della tray si traduce al momento dell'invio e segue il cambio di lingua.
- Una risposta `df` malformata di Docker produce il messaggio "Docker ha risposto in un formato inatteso".
- Nel dialogo di conferma la cartella di riavvio compare solo se tutti i processi fermati la condividono.
- Lo stato vuoto della conferma compare solo se tutte le voci sono escluse.
- Il toast dell'esito nomina il soggetto e i conteggi, per esempio "whitebox: arresto completato" o "3 su 4 fermati, 1 non risponde".

### Specifica e codice morto

- `assets/SPECIFICHE.md` allineata dove il codice era corretto e la specifica indietro: §5.2, §5.5, §7.6, §8.2, §8.4, §10.1-10.3, tabella dei rischi, elenco `ActionKind`.
- Codice morto rimosso in un commit separato, dopo verifica con grep sui chiamanti.

### Test rinforzati

Aree: core, service, collectors, model, ui, tray, app/config/cli, integrazione X11.

- Il test X11 è ora marcato `integration`, quindi `make test` non legge più il display dello sviluppatore.
- Gli sleep temporizzati sono sostituiti da attese su condizione.
- Ogni asserzione negativa ha il suo caso positivo.
- Gli oracoli sono calcolati a mano. Esempio: il "4,3 GB" della pagina Disco è documentato nel test.

### Limiti noti, non risolti

- Il probing degli id del menu, in caso di collisione crc32, dipende dall'ordine dei gruppi.
- Alcune guardie di narrowing per mypy in `executor.py` e `sampler.py` restano: non sono raggiungibili a runtime ma servono al type checker.
- Alcuni file di test superavano già le 300 righe prima della sessione (`test_executor_disk_fs.py`, `test_planning.py` e altri).
- Il test di `dirsize_faults` ricava dall'esecuzione sana quale chiamata `lstat` far fallire.
- Alcuni match di errore in `test_config` e `test_cgroups` dipendono dal testo della libreria standard.

### Note per il Cliente

I controlli automatici dell'applicazione ora coprono quasi tutto il codice (dal 97,4% al 99,25%) e sono stati messi alla prova introducendo di proposito errori nel programma, per verificare che i controlli li rilevino. Nel farlo sono emersi dieci difetti reali, ora corretti. Per chi usa l'applicazione cambia questo: i messaggi di esito dopo uno stop dicono quali programmi sono stati fermati e quanti; il menu nella barra non si confonde più fra un aggiornamento e l'altro; un errore di Docker viene spiegato in modo chiaro; la lingua dell'interfaccia si applica anche alla guida dell'etichetta. La documentazione tecnica è stata allineata a come il programma si comporta davvero.

### Prossimo passo

Push di main, da fare solo su richiesta dell'utente.

---

## 2026-10-18/19 | Sessione #9 [FIX]

Progetto: where-is-my-memory (comando `wimm`). Audit della schermata iniziale rispetto allo scopo dell'app, poi correzione dei finding uno alla volta. Tutti i commit sono su main, senza push.

### Richiesta

L'utente ha chiesto se, ad app aperta, si capisce facilmente quanto spazio si libera davvero senza perdere dati e cosa si sta chiudendo ("il mio vero scopo è esattamente questo"). L'audit ha prodotto i finding F1-F12; l'utente ha chiesto di correggerli uno alla volta.

### Azioni Eseguite

**Panoramica**
- `7311ef7` (feat, ui): in cima alla Panoramica compare la frase "Puoi liberare X senza perdere niente", che somma memoria e disco sicuro. Sotto ci sono un pulsante "Libera X di memoria", un pulsante per il disco sicuro, un collegamento alla pagina Disco e la riga "Altri Y se accetti di riscaricare o ricostruire". Prima del primo controllo del disco la frase dice che conta solo la memoria. Soluzione scelta dall'utente tra le proposte, con l'opzione "Due pulsanti".

**Pagina Disco e Docker**
- `d3f75ec` (F1): le immagini Docker costruite in locale venivano trattate come scaricate, perché con lo store containerd anche le build locali hanno un digest. La provenienza ora si legge da `Identity.Pull` di `GET /images/{id}/json` (API Docker 1.53 o successiva). Un'ispezione fallita conta come build locale. Budget di 30 s.
- `59bd992` (F4 e resto di F7): ogni riga della pagina Disco sta nella fascia del suo rischio. Maven e SDK Android vanno in "Da guardare prima", i modelli ollama e gli emulatori in "Attenzione: cancella dati", le immagini scaricate in "Si libera senza pensarci". I pulsanti cumulativi seguono le righe. Le immagini fissate per digest mostrano il nome. Le cartelle di dipendenze si leggono "progetto · node_modules". Specifica aggiornata (§5.3, §10.2).
- `bb3e8f8` (docker): un container rimosso mentre l'app legge l'elenco faceva risultare Docker "non raggiungibile" per un intero ciclo, perché docker-py solleva `NotFound`. Ora il container viene saltato (`ignore_removed=True`), anche nell'elenco dei progetti compose. Trovato dal controllo di fine turno, con un container rimosso da un'altra suite in parallelo.

**Nomi e testi dei dialoghi**
- `f738da3` (F8): nei dialoghi le cache hanno lo stesso nome della pagina Disco, non il nome della cartella.
- `a72ed02` (F7): i programmi noti si chiamano col nome d'uso, per esempio "Stato git del terminale (gitstatusd-linux-x86_64)", anche quando il gruppo ha più copie. Il dialogo di un programma di sviluppo che non è un server dice "Il programma si ferma." invece di "Il server si ferma.". Un progetto che si chiama come un programma noto tiene il suo nome.
- `21bd2ef` (F9): il finding come scritto era un errore di lettura. I processi gitstatusd sono 24, per 12 MB in tutto, coerenti ovunque; nel dialogo erano visibili solo 4 righe di un elenco a scorrimento. Il difetto vero era un altro: il dialogo non diceva quante voci contiene. Ora mostra "N voci nell'elenco" sopra la lista, da 2 voci in su.
- `e5f183a` (F10): per gitstatusd il dialogo diceva di riaccenderlo "con lo stesso comando, nella cartella /". Misurato in una zsh privata: dopo lo stop la shell non lo riavvia (nemmeno dopo 4 prompt), mentre un terminale nuovo ne avvia uno suo. Il dialogo ora dice "Lo stato git del terminale: riparte da solo nei terminali che apri dopo; in quelli già aperti torna quando li riapri." La frase compare una volta, per quanti processi si fermino.

**Elenco "Da liberare" e inattività**
- `f3c67f1` (F5a): "Da liberare" elenca solo i gruppi inattivi che hanno un'azione disponibile; conteggi e ordinamento sono coerenti.
- `1bf64c2` (F5b): un container con data di creazione sconosciuta conserva il tempo di inattività salvato dopo un riavvio dell'app.

**Test**
- `71e7387`: i test del riavvio e degli appunti non dipendono più dai tempi.
- `81af4ba` (F12): un `uv run pytest` senza opzioni, quello del controllo di fine turno, apriva finestre GTK sul desktop dell'utente, scriveva nei suoi appunti e si registrava sul suo bus di sessione. Ora ogni esecuzione crea un display Xvfb e un dbus-daemon privati, avviati al caricamento di `tests/conftest.py` e non in `pytest_configure`, che arriva dopo l'import di GTK nei test dell'interfaccia (un test ha mostrato GTK aprire ":1"). I due server terminano con pytest anche se viene ucciso con SIGKILL (`PR_SET_PDEATHSIG`). Il bus riceve display, home e cartelle XDG private, così anche il servizio di accessibilità che attiva resta isolato. `make test-all` e `make perf` non usano più `xvfb-run` e `dbus-run-session`.

### Verifica

- `uv run pytest -x`: 3941 test passati.
- `make test-all`: 3941 passati.
- `make test`: 3504 passati, copertura core 99,96%.
- `make lint`: pulito.
- Ogni correzione è passata dal `code-reviewer`.
- Le modifiche all'interfaccia sono state osservate sull'app vera, con i dati reali, a 1280 e 375 px.

### Limiti noti / Aperti

- **F11 (bassa), aperto:** all'arrivo del report del disco GTK scrive circa 90 avvisi sulle altezze minime dei widget. Erano già presenti a inizio sessione. A schermo la pagina è composta bene.
- Dopo aver spento alcune voci nel dialogo, la riga "N voci nell'elenco" conta le righe, non quelle selezionate.
- Il testo di gitstatusd non dice esplicitamente che nei terminali già aperti il prompt resta senza stato git.
- Ogni esecuzione di pytest paga circa 0,3 s per avviare display e bus.

### Note per il Cliente

L'obiettivo della sessione era far capire, appena si apre l'applicazione, quanto spazio si può liberare senza perdere nulla e che cosa verrebbe chiuso. Ora la prima schermata lo dice con una frase e due pulsanti: uno libera la memoria, l'altro il disco che si può svuotare senza rischi. Sotto indica anche quanto si potrebbe recuperare in più accettando di riscaricare o ricostruire qualcosa. Le voci del disco sono ordinate in base al rischio reale (per esempio i modelli ollama e gli emulatori sono ora segnalati come cancellazione di dati), i programmi hanno nomi comprensibili e i messaggi di conferma spiegano che cosa succede dopo, per esempio che lo stato git di un terminale torna da solo nei terminali nuovi. Sono stati corretti anche alcuni errori: un'immagine creata in locale veniva scambiata per una scaricata, e un container Docker rimosso al momento sbagliato faceva credere che Docker fosse irraggiungibile. Infine, i controlli automatici non disturbano più il computer di chi sviluppa: prima aprivano finestre e toccavano gli appunti, ora lavorano in un ambiente isolato. Resta aperto un difetto minore, che non si vede a schermo.

### Prossimo passo

Push di main, da fare solo su richiesta dell'utente.

---

## 2026-10-19 | Sessione #10 [FEATURE]

Progetto: where-is-my-memory (comando `wimm`). Chiusura del lotto L1 del piano `specs/002-disk-granular` (T-6.3..T-6.9), poi correzione dei finding della sua review. Tutti i commit sono su main, senza push.

### Richiesta

Chiudere il lotto L1: ogni riga della pagina Disco mostra in riga la conseguenza dell'azione (RF-29, decisione O1), senza dover aprire il dialogo di conferma. Poi correggere i finding della review di L1.

### Azioni Eseguite

**Lotto L1**
- Le righe Disco portano la conseguenza in riga (T-6.3..T-6.9, RF-29, decisione O1).

**Fix della review di L1**
- R1 `d8d1cea`: la riga "Immagine senza nome" non mostrava nessuna conseguenza.
- R2 `975cf63`: riga e dialogo compongono le conseguenze con una sola funzione, `join_consequences`, quindi i due testi non possono più divergere.
- R3 `28a80fc`: il test sulla conseguenza della riga passa dal percorso reale `plan_action`, non da un piano costruito a mano.
- R4 `79eae02` e `bc84658`: il sottotitolo della riga non ha più un limite di righe. Misurato a 360 px: con il tetto a 4 righe, 6 conseguenze uscivano troncate. Decisione dell'utente del 2026-10-19. Corretti `assets/SPECIFICHE.md` (RF-29), la spec (S4), il piano e i task.

**Test**
- `91cbc09`: il test del nome accessibile della riga chiede a GTK se `LABEL` è impostato, perché GTK 4.14 non ha un getter del valore.
- `4f61832`: ogni tipo di cache è confrontato riga contro piano (22 test in più, tutti verdi). I testi di HuggingFace e `node_modules` sono fissati come letterali.

### Verifica

- Click-through sull'app reale con HOME isolata: "Scegli una cartella" apre Impostazioni avanzate su "Cartelle di sviluppo", con il focus sul campo, a 360 e 1280 px. Il click-through precedente era inconcludente perché la scansione Disco non era ancora partita.
- Render della pagina Disco a 360 e 1280 px osservato: nessuna sovrapposizione, conseguenze intere.
- `make lint`: pulito.
- `make test-all`: 4039 passati, 1 saltato (misura precedente a `4f61832`, che aggiunge 22 test).
- `make deb`: ok. `make test-deb`: OK (1.0.0), lintian senza errori.

CHECKS L1: code-reviewer ESEGUITO (nessun CRITICAL né HIGH; 2 MEDIUM sui test, risolti in `4f61832`; 3 LOW aperti) | verify ESEGUITO (click-through e render a 360 e 1280 px) | a11y-gate N/A (app GTK, non HTML) | type-design-analyzer N/A (nessun tipo nuovo in L1) | /analyze ESEGUITO (1 CRITICAL: tre file di test oltre 300 righe, A1; MEDIUM A2 drift di T-6.3; LOW A3 dedup; remediation approvata dall'utente).

### Limiti noti / Aperti

- LOW: `planning.py` elimina i duplicati nelle conseguenze, `join_consequences` no. Riga e piano possono quindi differire se il piano ne produce di ripetute.
- LOW: il test del ritorno a capo dipende dal font in uso.
- LOW: il nome accessibile è verificato solo come presenza, non nel contenuto.
- Difetto preesistente, fuori da L1: a 360 px il dialogo delle preferenze spezza le etichette sillaba per sillaba ("tocc-are", "Cart-elle").
- `/analyze`: A1 (test oltre 300 righe), A2 (T-6.3 cita la sola prima conseguenza) e A3 (dedup) approvati per la correzione prima di L2.

### Note per il Cliente

Nella pagina Disco ogni voce ora dice subito che cosa succede se la si cancella, per esempio che cosa andrà riscaricato o ricostruito, senza dover aprire la finestra di conferma. La stessa frase compare nella finestra di conferma, quindi i due testi coincidono sempre. Anche sullo schermo stretto le frasi si leggono per intero. In revisione sono emersi alcuni difetti, ora corretti: una voce senza nome non mostrava nessuna spiegazione, e su schermo stretto alcune spiegazioni lunghe venivano tagliate. Restano aperti tre difetti minori, che riguardano solo i controlli automatici o un caso raro di testo ripetuto, e uno già presente prima di questo lavoro: sullo schermo più stretto le etichette della finestra delle preferenze vanno a capo spezzando le parole.

### Prossimo passo

Remediation A1-A3 di `/analyze`, poi lotto L2 (T-6.10).

---

## 2026-10-19 | Sessione #11 [FEATURE]

Progetto: where-is-my-memory (comando `wimm`). Remediation dei finding di `/analyze` su L1, poi lotto L2 del piano `specs/002-disk-granular` (elementi delle cache in sola lettura, decisione O3, T-6.10..T-6.17) con la sua review di chiusura. Tutti i commit sono su main; il repository non ha un remote.

### Richiesta

Applicare la remediation approvata di `/analyze` (A1-A3), poi realizzare il lotto L2: la pagina Disco mostra gli elementi contenuti in una cache, per ora senza poterli cancellare uno per uno, e il bottone "Pulisci tutta la cache" resta l'unica azione.

### Azioni Eseguite

**Remediation di `/analyze` su L1**
- A2 e A3 in `bbe4db6`.
- A1: i 33 file di test oltre 300 righe sono stati divisi in 9 commit (`99da857`..`481401b`). I test raccolti restano identici (4063) e i corpi delle funzioni sono identici secondo il confronto via `ast` (815 su 815).
- `ab24c96`: il gate dei limiti dimensionali ora controlla anche `tests/`. Prova di efficacia: con un file di prova da 377 righe il gate diventa rosso.

**Lotto L2 (O3)**
- T-6.10 `d914a9e`: tipi `CacheItem` e `CacheRest`, schema 5.
- T-6.11 e T-6.12 `61644e3`: attribuzione dei byte di HuggingFace tramite i collegamenti simbolici (symlink) che puntano ai blob del magazzino.
- T-6.13 `819f317`: collector degli elementi.
- T-6.14 `6aa360f`: misura dei tempi. Mediana 2,26 s di baseline contro 2,23 s con la modifica: dentro il rumore, entro il budget del +15%.
- T-6.15 `7a3a7d0`: sotto-righe pure (senza dipendenze da GTK).
- T-6.16 `d58d220`: riga espandibile e bottone "Pulisci tutta la cache".
- T-6.17 `3f685d0`: schema 5 documentato in DEVIATIONS.

**Review di chiusura L2**
- `code-reviewer`: 1 HIGH e 3 MEDIUM. Il HIGH (F1): una cartella chiamata `models-- ` faceva fallire l'intera scansione Disco.
- `type-design-analyzer`: 3 MEDIUM.
- F1-F10 corretti in `691c043`, `01ea891`, `2f3a845`.
- Seconda review delle correzioni: nessun CRITICAL né HIGH, 4 finding minori (F11-F14) corretti in `320a631`.

### Verifica

- Scansione reale sulla home (sola lettura): 5 modelli HuggingFace, XTTS-v2 con 2,09 GB comprensivi dei blob del magazzino, condiviso 0, non attribuito 0,3 MB. La dimensione ricavata dalla lettura dell'albero coincide al byte con `measure_dir_size` (19.222.589.440).
- Click-through sull'app reale con un hub finto in una HOME isolata: la riga HuggingFace si apre e si chiude a 360 e 1280 px, le sotto-righe non hanno bottoni. Render osservati.
- `make lint`: pulito.
- `make test-all`: 4208 passati, 1 saltato.

CHECKS L2: code-reviewer ESEGUITO (due giri: 1 HIGH + 3 MEDIUM, poi 4 LOW, tutti corretti) | type-design-analyzer ESEGUITO (3 MEDIUM corretti) | verify ESEGUITO (scansione reale e click-through a 360 e 1280 px) | a11y-gate N/A (UI GTK, non HTML) | /analyze N/A (eseguito su L1, in L2 nessun cambio a spec o piano salvo DEVIATIONS).

### Limiti noti / Aperti

- Nessun finding aperto.
- Codex: il login è attivo ma il broker non è pronto (`ready:false`), quindi tutti gli agent hanno lavorato in-house.

### Note per il Cliente

Nella pagina Disco la riga di una cache, per esempio quella dei modelli HuggingFace, ora si apre e mostra i singoli elementi che la compongono con la loro dimensione, così si capisce che cosa occupa lo spazio. Per ora gli elementi si possono solo guardare: l'unica azione resta "Pulisci tutta la cache". Sul computer di prova i conti tornano al byte con la misura precedente e la scansione non è diventata più lenta in modo percepibile. Durante la revisione è emerso un difetto serio: una cartella con un nome insolito poteva far fallire l'intera scansione del disco. È stato corretto insieme a una serie di difetti minori, e una seconda revisione non ne ha trovati di gravi. In parallelo sono stati divisi i file di test troppo lunghi, senza cambiare cosa verificano, e il controllo automatico sulla lunghezza dei file ora copre anche i test.

### Prossimo passo

Lotto L3: rimozione del singolo modello HuggingFace (T-6.19..T-6.25).

---

## 2026-10-19 | Sessione #12 [FEATURE]

Progetto: where-is-my-memory (comando `wimm`). Lotto L3 del piano `specs/002-disk-granular`: rimozione del singolo modello HuggingFace dalla pagina Disco (T-6.19..T-6.25), con la review di chiusura. Tutti i commit sono su main; il repository non ha un remote.

### Richiesta

Realizzare il lotto L3: dalla sotto-riga di un modello HuggingFace si può rimuovere quel solo modello, dopo conferma, senza toccare gli altri e senza cancellare i file che un altro modello usa ancora.

### Azioni Eseguite

**Lotto L3**
- T-6.19 e T-6.20 `0965acf`: azione `CACHE_ITEM_REMOVE`, impronta dell'azione con i blob esclusivi del modello e relativo planner. Verifica con context7: l'API di `huggingface_hub` conosce solo i blob dentro la cartella del modello, quindi la deviazione dal piano è confermata.
- T-6.21 e T-6.22 `6e48744`: executor con i controlli rifatti al momento dell'esecuzione e rimozione tramite `safe_tree`.
- T-6.23 `77ce167`: nuova misura del disco subito dopo la rimozione, così la pagina si aggiorna.
- T-6.24 `6b10855`: bottone "Rimuovi" sulle sotto-righe dei modelli.

**Review di chiusura (T-6.25)**
- `security-reviewer` e `code-reviewer`: nessun CRITICAL né HIGH.
- F16-F22 corretti in `b0e253a`: un blob si cancella solo se nessun modello rimasto lo raggiunge dopo la rimozione della cartella; gestito il lock sparito; l'esito parziale riporta i byte liberati; solo i file di `blobs/` contano come blob; la condizione S1 è provata per ogni tipo di elemento; `remove_file` spostata in `safe_file.py`.
- Secondo giro di sicurezza: F23 (MEDIUM, una lettura incompleta dell'albero poteva cancellare un blob ancora usato) e F26 corretti in `c95e133`. Con una lettura incompleta nessun blob viene cancellato.

### Verifica

- Click-through sull'app reale con un hub finto in una HOME isolata: "Rimuovi" su coqui/XTTS-v2 apre il dialogo con la stessa conseguenza mostrata nella riga; la conferma rimuove la cartella e il blob esclusivo; il blob condiviso resta; il toast dice 6 MB liberati; la nuova misura toglie la riga. Render controllati a 360 e 1280 px.
- `make lint`: pulito.
- `make test-all`: 4306 passati, 1 saltato.

CHECKS L3: security-reviewer ESEGUITO (due giri; F24 e F25 parked) | code-reviewer ESEGUITO (1 MEDIUM + 4 LOW, corretti) | verify ESEGUITO (click-through della rimozione, render 360 e 1280 px) | a11y-gate N/A (UI GTK, non HTML) | /analyze N/A (nessun cambio a spec o piano in L3).

### Limiti noti / Aperti

- F15 MEDIUM: alcuni test a tempo sono instabili sotto carico pesante (budget CPU della scansione dei processi, `spin_until` con timeout). Passano se rilanciati da soli. La decisione sulla soglia è lasciata all'utente.
- F24 LOW (parked): resta una finestra stretta fra la lettura e la cancellazione; si cancella comunque solo l'inode pianificato.
- F25 LOW (parked): un link con target assoluto scritto in modo diverso dalla radice non viene contato. HuggingFace usa link relativi, quindi il caso non si presenta con la cache normale.
- Codex: il login è attivo ma il broker non è pronto, quindi tutti gli agent hanno lavorato in-house.

### Note per il Cliente

Nella pagina Disco ogni modello HuggingFace ha ora il bottone "Rimuovi". La finestra di conferma dice che cosa verrà liberato, e dopo la conferma il modello sparisce dall'elenco con lo spazio recuperato indicato. I file condivisi con altri modelli non vengono toccati. Nella prova su una cartella di test, la rimozione di un modello ha liberato 6 MB e ha lasciato intatto il file in comune. Le revisioni non hanno trovato difetti gravi; un difetto di media gravità, che in un caso raro poteva cancellare un file ancora in uso, è stato corretto: se l'elenco dei file non si legge per intero, l'app non cancella nulla. Restano aperti due casi minori molto rari e alcuni controlli automatici che a volte falliscono quando il computer è molto occupato, senza effetto sull'uso dell'app.

### Prossimo passo

Lotto L6 (selezione multipla), poi L4 e L5.

---
