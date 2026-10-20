# where-is-my-memory: specifica tecnica e funzionale

Versione 1.0 - 2026-10-16

Documento di riferimento per lo sviluppo autonomo dell'intero sistema. Contiene il perché, il cosa e il come. Dove una scelta è già stata presa dall'utente è marcata **[DECISO]** e non va ridiscussa. Dove un fatto è stato misurato sulla macchina di destinazione è marcato **[MISURATO]**. Dove un comportamento va ancora verificato in fase di implementazione è marcato **[DA VERIFICARE]**, con il task che lo verifica.

---

## 0. Istruzioni per chi sviluppa (Claude Code)

1. Leggi l'intero documento prima di scrivere codice. Le sezioni 5 (modello di classificazione) e 8 (azioni) sono le più delicate: un errore lì chiude processi che l'utente non voleva chiudere.
2. Sviluppa per fasi (sezione 16), nell'ordine. Ogni fase lascia il sistema usabile. Non iniziare la fase N+1 finché la fase N non supera i propri `verify:`.
3. Test-first sulla logica pura (`src/wimm/core/`): nessuna funzione di classificazione, raggruppamento, inattività o pianificazione delle azioni senza un test che la specifica.
4. Il codice, i commenti, i nomi di file, i log e i commit sono in **inglese**. Le stringhe mostrate all'utente sono in **italiano**.
5. Lo sviluppo non deve mai eseguire azioni distruttive reali sulla macchina dell'utente: niente kill di processi altrui, niente `docker rm`, `prune` o cancellazioni durante i test. I test usano fake e fixture (sezione 15). L'esecuzione reale delle azioni si verifica solo su bersagli creati apposta dal test (un `python3 -m http.server` lanciato dal test, un container `alpine` etichettato `wimm.test=1`).
6. Se una premessa di questo documento si rivela falsa durante l'implementazione (un'API che non si comporta come descritto), fermati, documenta l'evidenza in `docs/DEVIATIONS.md` e scegli la via indicata nella sezione 18 per quel rischio. Se non è prevista, scegli l'opzione più conservativa (meno azioni possibili, più conferme) e annotala.
7. Rispetta i limiti di codice: file al massimo 300 righe, funzioni al massimo 30 righe, al massimo 4 parametri, niente magic number (costanti nominate in `src/wimm/core/constants.py` o in configurazione).
8. Esistono anche `specs/where-is-my-memory/plan.md` e `tasks.md` (piano derivato con una numerazione propria, T001-T062). Se contraddicono questo documento, **prevale questo documento**, e gli ID validi sono quelli `T-x.y` della sezione 16. Le premesse marcate **[DA VERIFICARE]** si chiudono nel task indicato, e l'esito, confermato o smentito, si annota in `docs/DEVIATIONS.md`.
9. Il codice dell'icona nella barra (StatusNotifierItem + dbusmenu) si porta dal progetto `sysbar` dello stesso autore, `/home/bonn/Documenti/00_Lavoro/ProgettiPersonali/sysbar/src/sysbar/app/tray/` (`status_notifier.py`, `dbus_menu.py`, `menu_builder.py`, `menu_model.py`, `tray.py`), già funzionante su questa macchina **[MISURATO: processo `/opt/sysbar/bin/sysbar` attivo]**. `sysbar` è GPL-3.0-or-later, quindi anche questo progetto lo è.

---

## 1. Contesto e problema

L'utente sviluppa su Ubuntu e resta spesso senza RAM e senza spazio disco anche quando pensa di non avere molto aperto. La causa ricorrente è dimenticare risorse accese: container Docker di progetti chiusi giorni prima, dev server (Flask, uvicorn, vite, npm, jupyter), port-forward di `kubectl`, sessioni di CLI e app desktop pesanti.

Stato della macchina al 2026-10-16 **[MISURATO]**:

| Risorsa | Valore | Note |
|---|---|---|
| RAM | 38 GB totali, 30 GB usati, 8,2 GB disponibili | |
| Firefox (snap) | ~18 GB RSS sommato (processi `Isolated Web Co`, `MainThread`) | l'RSS sommato sovrastima: memoria condivisa fra processi |
| `npm` / `python` / `uv` | 4,3 / 3,4 / 2,1 GB | dev server e watcher lanciati da terminale |
| `codex` + `claude` | ~2,8 GB | CLI di agenti AI |
| Container Docker | 8 attivi, ~0,9 GB in tutto | progetti compose `whitebox`, `luve-agent` |
| Disco `/` | 350 GB, 93% pieno, 26 GB liberi | |
| Docker su disco | 3,9 GB immagini inutilizzate, 3,4 GB build cache recuperabili | |
| Porte TCP in ascolto | ~20 su localhost | 8000, 8001 (kubectl), 4000, 5433, 8080, 11434 (ollama)... |

Conclusione che guida il prodotto: la RAM non è occupata soprattutto dai container ma da processi di sviluppo e app desktop, mentre i container pesano sul disco. Lo strumento deve quindi coprire **tutto**, non solo Docker e Flask.

---

## 2. Obiettivi e non obiettivi

### Obiettivi

- O1. Mostrare in ogni momento cosa sta occupando RAM e disco, raggruppato per progetto e per tipologia.
- O2. Distinguere ciò che è **in uso** da ciò che è **acceso ma inattivo**, con il motivo della classificazione e da quanto tempo.
- O3. Dire per ogni elemento quanto si libera chiudendolo e quanto è rischioso chiuderlo.
- O4. Permettere di fermare, chiudere o cancellare con un'anteprima di cosa succede e di quanto si libera.
- O5. Avvisare con notifiche quando qualcosa resta inattivo a lungo o quando RAM o disco stanno finendo.
- O6. Stare nella barra in alto di GNOME, partire al login, installarsi con un pacchetto `.deb`.

### Non obiettivi

- N1. Nessuna azione automatica: lo strumento non ferma niente da solo **[DECISO]**.
- N2. Nessun privilegio di root: lo strumento agisce solo su risorse dell'utente. Le risorse di sistema si mostrano ma non si toccano.
- N3. Non è un task manager generico: non mostra grafici storici lunghi, non gestisce priorità o affinità dei processi.
- N4. Nessun supporto Wayland nella versione 1.0 per le funzioni che dipendono da X11 (sezione 7.8); il resto deve funzionare anche su Wayland.
- N5. Nessuna gestione per singola scheda del browser: non è accessibile dall'esterno (sezione 7.7).

---

## 3. Glossario

| Termine | Significato |
|---|---|
| **Entità** | Un singolo elemento osservato: un processo, un container, un'immagine Docker, un volume, una cartella su disco. |
| **Gruppo** | Insieme di entità che l'utente pensa come una cosa sola: un progetto (container + dev server dello stesso repo), un'app desktop con i suoi processi figli, una scheda di terminale. |
| **Categoria** | Tipologia di un gruppo: dev server, container, app desktop, browser, CLI interattiva, sistema... (sezione 5.1). |
| **Classe di protezione** | `actionable` (si può agire) o `protected` (si mostra, nessuna azione). |
| **Rischio di un'azione** | `safe`, `caution`, `danger`: dipende dall'azione **e** dall'entità (sezione 5.3). |
| **Attività** | Stato calcolato: `active`, `idle`, `unknown` (non determinabile). |
| **Recuperabile** | Stima dei byte liberati eseguendo un'azione. |
| **USS** | Unique Set Size: memoria privata di un processo, quella che si libera davvero chiudendolo. |
| **PSS** | Proportional Set Size: memoria privata più la quota proporzionale di quella condivisa. La somma dei PSS è la memoria realmente usata dal gruppo. |
| **Snapshot** | Fotografia completa dello stato prodotta a ogni ciclo di campionamento. |
| **Piano** | Descrizione di un'azione prima della sua esecuzione: bersagli, conseguenze, rischio, recupero stimato. Si esegue solo un piano già mostrato. |

---

## 4. Requisiti funzionali

Ogni requisito ha un ID citabile nei test e nei commit.

### Visione

- **RF-01** Il pannello mostra un riepilogo in alto: RAM usata/totale, RAM disponibile, swap usato, disco `/` usato/totale, e i due totali "recuperabile ora" (RAM e disco) calcolati sui gruppi inattivi con azione `safe`.
- **RF-02** Il riepilogo scompone la RAM usata per categoria (container, dev server, browser, app desktop, CLI, sistema, cache del kernel, non attribuita). La voce "non attribuita" esiste e si mostra, anche quando è grande: non va nascosta né ripartita a stima.
- **RF-03** Il pannello elenca i gruppi ordinati per RAM recuperabile decrescente, con filtri: tutti / solo inattivi / per categoria / per classe di rischio.
- **RF-04** Ogni gruppo mostra: nome, categoria, stato di attività, da quanto tempo è in quello stato, motivo dello stato in linguaggio piano, RAM (PSS e recuperabile USS), disco se rilevante, porte in ascolto, rischio dell'azione principale.
- **RF-05** Espandendo un gruppo si vedono le entità che lo compongono: PID, comando, directory di lavoro, porte, utente, avvio, memoria; per i container immagine, stato, volumi montati, porte pubblicate.
- **RF-06** Una vista "Disco" elenca: immagini Docker (in uso / inutilizzate / dangling / costruite in locale), container fermi, volumi (montati / orfani), build cache Docker, cache utente note (uv, npm, pip), cestino, le cartelle di dipendenze ricostruibili della §7.6 di progetti non modificati da più di N giorni (default 90) nelle radici configurate.
- **RF-07** Una vista "Sistema" mostra in sola lettura i processi e i servizi protetti con la loro memoria, raggruppati (sessione GNOME, audio, servizi di sistema, altri utenti), con il motivo della protezione.
- **RF-08** La classificazione di ogni gruppo è spiegata: un tooltip o una riga secondaria dice perché è in quella categoria e in quella classe ("lanciato dal terminale nella cartella `whitebox`, in ascolto sulla porta 8000").

### Attività

- **RF-10** Un gruppo è `idle` se nessuna sua entità ha mostrato attività nella finestra di osservazione (default 30 minuti). I criteri per tipo di entità sono nella sezione 5.4.
- **RF-11** Per le entità di cui non si può misurare l'attività (browser, molte app desktop) lo stato è `unknown` e lo si dice, invece di indovinare.
- **RF-12** Il tempo di inattività sopravvive al riavvio dell'applicazione e al logout (persistenza dell'ultimo istante di attività per entità).

### Azioni

- **RF-20** Azioni su processi: termina (SIGTERM all'albero del processo), forza chiusura (SIGKILL) offerta solo se dopo il timeout il processo è ancora vivo.
- **RF-21** Azioni su container: ferma, rimuovi (solo se fermo, senza volumi), ferma progetto compose, rimuovi progetto compose senza volumi, rimuovi progetto compose con volumi (rischio `danger`).
- **RF-22** Azioni su disco: rimuovi immagine inutilizzata, rimuovi immagini dangling, rimuovi tutte le immagini inutilizzate, svuota build cache, rimuovi container fermi, rimuovi volume orfano, pulisci cache uv/npm/pip, svuota cestino, elimina le cartelle di dipendenze ricostruibili della §7.6 di un progetto inattivo. Azione `cache_item_remove` (RF-51): rimuovi un singolo elemento di una cache (un modello HuggingFace, un pacchetto dell'Android SDK, un dispositivo AVD, un browser di Playwright, un prodotto JetBrains, un modello ollama), con il comando del tool quando esiste e con una cancellazione controllata altrimenti.
- **RF-23** Azione di gruppo: "Ferma tutto il gruppo", che compone le azioni dei membri in un solo piano.
- **RF-24** Azione multipla: "Ferma tutti i gruppi inattivi sicuri", che include solo gruppi `idle` e azioni `safe`.
- **RF-25** Nessuna azione parte senza un'anteprima che mostra bersagli, conseguenze, rischio e recupero stimato. Le conferme crescono col rischio (sezione 8.3).
- **RF-26** Dopo l'esecuzione il pannello mostra l'esito per bersaglio e la memoria o il disco effettivamente liberati (differenza misurata, non stima).
- **RF-27** Un gruppo si può "ignorare" (escluso da notifiche e da "recuperabile ora") o "silenziare" per un tempo (1 h, 24 h, 7 giorni).
- **RF-28** Nessuna azione è disponibile su entità `protected`. Il pulsante non esiste: non è disabilitato, è assente, e la riga dice perché.
- **RF-29** Spiegazione in riga (decisione O1, 2026-10-19). Ogni riga della vista Disco che ha un'azione mostra come sottotitolo il percorso o la descrizione e, su una riga sotto, la conseguenza dell'azione: il testo è identico al "Cosa succede" del dialogo di conferma della stessa riga (lo produce una sola funzione pura, usata da riga e da piano). Il badge è corto: Sicuro, Attenzione, Pericolo. Vale per cache, cestino, immagini, container fermi, volumi, build cache, cartelle di dipendenze e sotto-elementi di RF-51. Una riga senza azione non ha la seconda riga, con un'eccezione (decisione D1, 2026-10-20): un modello ollama che il server attivo non può rimuovere mostra al suo posto il motivo, per esempio "Il server ollama attivo è quello di sistema e non vede questi modelli". Il sottotitolo non ha un limite di righe e non viene mai troncato: a 360 px va a capo per intero e non si sovrappone a titolo, dimensione, badge e bottone (correzione del 2026-10-19: con 4 righe le conseguenze più lunghe uscivano troncate).

### Notifiche

- **RF-30** Notifica quando un gruppo `actionable` resta `idle` oltre una soglia (default 2 ore) e il suo recuperabile supera una soglia (default 200 MB) **[DECISO: solo notifiche]**.
- **RF-31** Notifica di pressione quando la RAM disponibile scende sotto il 10% o il disco `/` libero sotto il 10%, con i tre gruppi che libererebbero di più.
- **RF-32** Le notifiche hanno due azioni: "Apri" (apre il pannello sul gruppo) e "Silenzia 24 h". Nessuna notifica esegue direttamente un'azione sulle risorse.
- **RF-33** Una sola notifica per gruppo per episodio di inattività; al massimo 3 notifiche all'ora, oltre si aggrega ("4 gruppi inattivi, 3,8 GB").

### Barra in alto e avvio

- **RF-40** Un'icona nella barra in alto mostra a fianco un'etichetta corta con il recuperabile ("4,2 GB inattivi"), o niente se è sotto 100 MB.
- **RF-41** L'icona cambia stato: normale, avviso (RAM disponibile < 15% o disco libero < 15%), critico (< 10%).
- **RF-42** Il **clic sinistro** sull'icona apre il pannello (o lo porta in primo piano se è già aperto). Il **clic destro** apre un menu con: riepilogo RAM e disco, fino a 5 gruppi inattivi con il loro recuperabile (cliccarli apre il pannello su quel gruppo), "Silenzia notifiche per 1 h", "Esci".
- **RF-43** All'accesso l'applicazione parte automaticamente, con l'icona visibile e la finestra nascosta.
- **RF-44** Chiudere la finestra la nasconde: il monitoraggio e le notifiche continuano. Solo "Esci" dal menu termina l'applicazione.

### Impostazioni

- **RF-50** Preferenze modificabili dal pannello: finestra di osservazione, soglia di notifica, soglia minima di recuperabile, soglie di pressione, intervallo di campionamento, radici da scansionare per le cartelle di dipendenze, età minima delle cartelle, notifiche attive per categoria, lista dei gruppi ignorati.

### Disco granulare

- **RF-51** Elementi delle cache (decisione O3, 2026-10-19). La riga di una cache con contenuti distinguibili si espande e mostra un sotto-elemento per elemento, ordinato per dimensione decrescente, con titolo, dimensione, conseguenza, badge e azione "Rimuovi"; al massimo 50 sotto-righe più "e altre N". La pulizia della cache intera resta, con il bottone "Pulisci tutta la cache". L'elemento di HuggingFace (`models--*`, `datasets--*`, `spaces--*`) vale la somma dei suoi file più i blob del magazzino `blobs/` raggiunti **solo** dai suoi symlink; un symlink il cui bersaglio esce dalla cache non conta. Gli elementi per cache sono questi, le altre cache restano righe semplici:

  | Cache | Elemento | Rimozione | Rischio |
  |---|---|---|---|
  | huggingface | repo `models--*`, `datasets--*`, `spaces--*` e blob esclusivi | cancellazione controllata della cartella e dei blob esclusivi, ricalcolati all'esecuzione (Q1=A) | caution |
  | ollama (home e servizio di sistema) | modello, `<nome>:<tag>` | `ollama rm`, richiede il server attivo (Q2=A) | danger |
  | android_sdk | pacchetto (`platforms;android-35`, `build-tools;35.0.0`, ...) | `sdkmanager --sdk_root=<cache> --uninstall <id>`, solo con il tool; mai `cmdline-tools` né `licenses` | caution |
  | android_avd | dispositivo (`<nome>.avd` e `<nome>.ini`) | `avdmanager delete avd -n <nome>`, rifiutato se l'emulatore è in esecuzione | danger |
  | playwright | browser (`chromium-<rev>`, `firefox-<rev>`, `webkit-<rev>`, `ffmpeg-<rev>`) | cancellazione controllata della cartella | safe |
  | jetbrains | cartella prodotto-versione (`PyCharm2025.1`) | cancellazione controllata della cartella | caution |

  Nessun elemento per Maven (Q4=A), Gradle, uv, pip, npm, pnpm, yarn, bun, conda, cargo, go, miniature e cestino. Il report disco passa a `SCHEMA_VERSION` 5: ogni cache porta `items` e `rest`.
- **RF-52** "Condiviso fra più modelli" e "Non attribuito". I blob del magazzino raggiunti da symlink di due o più elementi compaiono nella sotto-riga "Condiviso fra più modelli" e non nella dimensione di nessun elemento. I byte fuori da ogni elemento (blob senza riferimenti, `.locks`, file alla radice) compaiono nella sotto-riga "Non attribuito", con una frase che dice cosa contiene e che si libera solo con "Pulisci tutta la cache"; le due sotto-righe non hanno azione propria. La somma di elementi, condiviso e non attribuito è uguale alla dimensione della cache.
- **RF-53** Selezione multipla ("Libera i selezionati"). La modalità "Seleziona" mette una casella su ogni riga e sotto-riga con azione; il bottone "Libera i selezionati (N, X GB)" apre **un** dialogo con le voci raggruppate per rischio, il totale stimato, la conseguenza di ciascuna e la possibilità di togliere singole voci (§8.3). Il livello di conferma è quello della voce più rischiosa. Le voci `danger` non hanno la casella (Q3=A): si rimuovono una per volta con la frase digitata. Selezionare una cache intera toglie la selezione dei suoi elementi e viceversa. La selezione non sopravvive a un nuovo report; un elemento sparito o cambiato è segnalato nel dialogo invece di essere confermato. "Libera spazio" resta il massivo senza perdite: prende solo voci `safe`.

---

## 5. Modello di classificazione

Questo è il cuore del prodotto. Tutta la logica sta in `src/wimm/core/` come funzioni pure su dataclass, senza import di `psutil`, `docker` o `gi`.

### 5.1 Categorie

| Categoria (`Category`) | Come si riconosce (in ordine di priorità) | Esempi | Classe |
|---|---|---|---|
| `SYSTEM` | processo di un altro utente (uid reale diverso), oppure cgroup fuori da `user@<uid>.service`, oppure nome nella lista protetta (5.2) | dockerd, ollama come servizio di sistema, tailscaled, Xorg, gnome-shell, pipewire | `protected` |
| `CONTAINER` | entità Docker; i processi host il cui cgroup è sotto `system.slice/docker-<id>.scope` **non** sono processi dell'utente e vanno esclusi dal censimento processi (anche se girano con uid 1000) | whitebox-keycloak, luve-agent-db | `actionable` |
| `DEV_SERVER` | processo dell'utente con almeno un socket TCP in `LISTEN`, non figlio di un'app desktop o del browser | flask, uvicorn, gunicorn, vite, next dev, `npm run dev`, jupyter, `python -m http.server`, `kubectl port-forward` | `actionable` |
| `DEV_PROCESS` | processo dell'utente lanciato da terminale (cgroup `vte-spawn-*.scope` o figlio di una shell), senza socket in ascolto, che non sia la shell stessa | watcher, `pytest -f`, `tsc --watch`, script lunghi | `actionable` |
| `AI_CLI` | nome o cmdline che corrisponde a `claude`, `codex`, `gemini`, `agy`, `aider`, `ollama run` lanciati da terminale | sessioni Claude Code, Codex | `actionable` (sempre `caution`) |
| `BROWSER` | cgroup `snap.firefox.*`, `app-gnome-firefox*`, `app-gnome-google-chrome*`, `*chromium*`, `*brave*`, oppure eseguibile del browser; i processi figli appartengono allo stesso gruppo | Firefox snap | `actionable` (sempre `caution`) |
| `DESKTOP_APP` | cgroup `app-gnome-<appid>-<pid>.scope`, `snap.<nome>.*.scope`, `app-flatpak-*.scope`; nome del gruppo dal file `.desktop` corrispondente | VS Code, Slack, Spotify, Postman | `actionable` (`caution` per editor, IDE e app di office/chat) |
| `TERMINAL` | `gnome-terminal-server`, emulatori di terminale | | `actionable` (`caution`: chiude tutte le schede) |
| `SESSION` | cgroup `session.slice`, `app.slice/*.service` di GNOME (gsd-*, evolution-*, tracker-*, gvfs*, xdg-desktop-portal*, at-spi*, ibus*), `dbus-*`, `systemd --user` | | `protected` |
| `SELF` | il processo di where-is-my-memory (`pid == os.getpid()`) | | `protected` |
| `OTHER` | processo dell'utente che non rientra nelle regole precedenti | | `actionable` (`caution`) |
| `PROJECT` | categoria **di gruppo**, non di processo: un gruppo che dopo la fusione (5.5 punto 4) contiene sia container sia processi. Un progetto compose di soli container resta `CONTAINER` | whitebox (6 container + uvicorn) | `actionable` |


**Ordine di valutazione** di `categorize_process`, la prima regola che corrisponde vince: 1) `SELF`; 2) `SYSTEM` (altro uid o cgroup fuori da `user@<uid>.service`); 3) escluso dal censimento se il cgroup è uno scope Docker (lo rappresenta il container); 4) `SESSION` e lista protetta (5.2); 5) `BROWSER`, `DESKTOP_APP`, `TERMINAL` per scope del cgroup o per antenato con una di queste categorie (qui ricadono gli helper degli editor); 6) `AI_CLI`; 7) `DEV_SERVER`; 8) `DEV_PROCESS`; 9) `OTHER`. Le categorie dei container e di `PROJECT` si assegnano in `grouping.py`, non qui.

Il cgroup di ogni processo si legge da `/proc/<pid>/cgroup` (riga `0::<path>`, cgroup v2) **[MISURATO]**. Esempi reali:

```
firefox:  0::/user.slice/user-1000.slice/user@1000.service/app.slice/snap.firefox.firefox-<uuid>.scope
claude:   0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-org.gnome.Terminal.slice/vte-spawn-<uuid>.scope
terminal: 0::/user.slice/user-1000.slice/user@1000.service/app.slice/app-org.gnome.Terminal.slice/gnome-terminal-server.service
docker:   /sys/fs/cgroup/system.slice/docker-<container_id>.scope
```

Le shell (`bash`, `zsh`, `fish`, `sh`) in un `vte-spawn` non si propongono mai da sole: chiuderle chiude la scheda del terminale. Fanno parte del gruppo della scheda ma non hanno azioni proprie.

I processi helper di un editor (language server come `pyright`, `tsserver`, `rust-analyzer`, i processi `node` di estensioni VS Code) seguono il processo padre: appartengono al gruppo `DESKTOP_APP` dell'editor, anche se aprono socket in ascolto.

### 5.2 Lista protetta

Costante `PROTECTED_PROCESS_NAMES` in `core/constants.py`, estendibile da configurazione ma **non riducibile** (le voci di default non si possono rimuovere):

`gnome-shell`, `gnome-session-binary`, `gnome-session-ctl`, `Xorg`, `Xwayland`, `systemd`, `dbus-daemon`, `dbus-broker`, `pipewire`, `pipewire-pulse`, `wireplumber`, `pulseaudio`, `gsd-*`, `gvfsd*`, `gvfs-*`, `xdg-desktop-portal*`, `xdg-document-portal`, `xdg-permission-store`, `at-spi*`, `ibus-*`, `tracker-miner-*`, `evolution-*`, `goa-*`, `gnome-keyring-daemon`, `ssh-agent`, `gpg-agent`, `mosh-server*`, `snapd*`. `mosh-server*` protegge il lato server delle sessioni mosh come `sshd` protegge quelle SSH (docs/DEVIATIONS.md, sessioni SSH). Il processo di where-is-my-memory stesso si riconosce per PID (`os.getpid()`), non per nome, ed è `SELF`.

`gnome-terminal-server` non è protetto, è `TERMINAL` con rischio `caution`.

### 5.3 Rischio per azione

Il rischio non è una proprietà dell'entità ma della coppia (entità, azione). Fermare un container Postgres con un volume è sicuro, perché i dati restano nel volume. Rimuovere il volume distrugge i dati.

| Livello | Definizione | Conferma richiesta |
|---|---|---|
| `safe` | Reversibile, nessuna perdita di dati o di lavoro: si riavvia con lo stesso comando. | Dialogo con anteprima, un clic su "Conferma". |
| `caution` | Possibile perdita di stato non salvato, di sessione o di lavoro di ricostruzione (re-download, rebuild, re-install). | Dialogo con le conseguenze elencate in evidenza, pulsante di conferma con stile `destructive-action`. |
| `danger` | Perdita di dati irreversibile. | Dialogo che chiede di digitare il nome del bersaglio (nome del volume o del progetto) prima di abilitare la conferma. |

Tabella completa, implementata come funzione pura `assess_risk(entity, action) -> RiskAssessment` dove `RiskAssessment` contiene livello e lista di conseguenze in italiano:

| Entità | Azione | Rischio | Conseguenza mostrata |
|---|---|---|---|
| DEV_SERVER `idle` | termina | `safe` | "Il server si ferma." (come riavviarlo sta nella riga "Per riaccenderlo" del dialogo) |
| DEV_PROCESS `idle` | termina | `safe` | "Il programma si ferma." (non è un server: un watcher, `gitstatusd`) |
| DEV_SERVER / DEV_PROCESS `active` o `unknown` | termina | `caution` | "È in uso adesso: chi lo sta usando perde la connessione." |
| processo in primo piano su un terminale (ha un TTY ed è il foreground process group, `tpgid`) | termina | `caution` | "È in esecuzione in primo piano in un terminale: potresti interrompere un lavoro in corso." |
| AI_CLI | termina | `caution` | "La sessione dell'agente si chiude: il lavoro non salvato nella conversazione si perde." |
| BROWSER | chiudi | `caution` | "Il browser si chiude. Le schede si recuperano solo se il ripristino della sessione è attivo." |
| DESKTOP_APP "con documenti" (definizione sotto la tabella) | chiudi | `caution` | "Eventuali file non salvati possono andare persi." |
| DESKTOP_APP altre | chiudi | `caution` | "L'applicazione si chiude." |
| TERMINAL | chiudi | `caution` | "Si chiudono tutte le finestre e le schede del terminale e i programmi al loro interno." |
| qualsiasi processo | forza chiusura (SIGKILL) | `caution`; `danger` se il processo è un'app "con documenti" o un database locale (nome in `postgres`, `mysqld`, `mariadbd`, `mongod`, `redis-server`) | "Chiusura immediata senza salvataggio." |
| CONTAINER | ferma | `safe` | "Il container si ferma; dati e configurazione restano. Si riavvia con `docker start` o `docker compose up`." |
| CONTAINER fermo | rimuovi | `caution` | "Le modifiche fatte dentro il container fuori dai volumi si perdono." |
| progetto compose | ferma progetto | `safe` | come sopra, per N container |
| progetto compose | rimuovi senza volumi (`down`) | `caution` | "I container vengono rimossi; i volumi con i dati restano." |
| progetto compose | rimuovi con volumi (`down -v`) | `danger` | "I dati dei volumi X, Y vengono cancellati in modo definitivo." |
| immagine inutilizzata con `RepoDigests` | rimuovi | `safe` | "Si riscarica dal registry quando serve." |
| immagine inutilizzata senza `RepoDigests` (costruita in locale) | rimuovi | `caution` | "Immagine costruita in locale, non è su un registry: per riaverla serve ricostruirla." |
| immagini dangling | rimuovi | `safe` | |
| build cache | svuota | `safe` | "Le prossime build saranno più lente." |
| volume orfano | rimuovi | `danger` | "I dati del volume vengono cancellati in modo definitivo." |
| cache uv / npm / pip | pulisci | `safe` | "I pacchetti si riscaricano quando servono." |
| cestino | svuota | `danger` | "I file nel cestino vengono eliminati in modo definitivo." |
| cartella di dipendenze (§7.6) di progetto inattivo | elimina | `caution` | "Per usare di nuovo il progetto serve ricostruire la cartella con {comando}.", dove il comando è quello del suo ecosistema (`npm install`, `uv sync`, `cargo build`, `mvn package`, `gradle build`, `npm run build`, `composer install`); senza comando noto "Serve reinstallare le dipendenze (npm install o uv sync) prima di usare il progetto." |

Un'app è **"con documenti"** se il campo `Categories` del suo `.desktop` contiene almeno uno fra `TextEditor`, `IDE`, `Development`, `Office`, `WordProcessor`, `Spreadsheet`, `Presentation`, `Graphics`, `Email`, `Chat`, `InstantMessaging`; in mancanza del `.desktop`, se il nome del processo è in `DOCUMENT_APP_NAMES` (`code`, `codium`, `cursor`, `idea`, `pycharm`, `gedit`, `gnome-text-editor`, `soffice.bin`, `slack`, `discord`, `telegram-desktop`, `thunderbird`, `obsidian`). Entrambe le liste sono costanti in `core/constants.py`.

Un gruppo prende come "rischio dell'azione principale" il massimo dei rischi delle azioni dei membri.

### 5.4 Regole di attività

Funzione pura `assess_activity(history: EntityHistory, now: datetime, config: ActivityConfig) -> ActivityAssessment` con stato, `since` e motivo in italiano. La storia è un ring buffer di campioni (sezione 6.4).

Perché `TIME_WAIT` e non solo `ESTABLISHED` **[MISURATO]**: una richiesta HTTP breve (`curl`, browser) apre e chiude la connessione in pochi millisecondi, fra due campioni. La connessione chiusa però resta visibile in `TIME_WAIT` per 60 s, più dell'intervallo di campionamento, con la porta del server in `laddr`, e `psutil.net_connections("tcp")` la restituisce senza root. Verificato su un `python3 -m http.server`: dopo una richiesta compaiono gli stati `LISTEN` e `TIME_WAIT`. I contatori `/proc/<pid>/io` invece non sono un segnale affidabile (61 byte per una richiesta, nessuna distinzione fra socket e file) e non si usano. Limite noto: un client remoto che chiude per primo lascia il `TIME_WAIT` sulla sua macchina e non sul server; per i dev server su localhost il caso non si presenta.

Un campione è "attivo" se, rispetto al campione precedente:

| Tipo di entità | Segnale di attività in un intervallo | Soglie di default |
|---|---|---|
| DEV_SERVER | almeno una **nuova** connessione TCP sulla porta del server, cioè una quadrupla `laddr`+`raddr` non presente nel campione precedente, con porta locale (o remota, per i client locali) uguale a una porta in `LISTEN` del processo o dei suoi figli, in **qualsiasi** stato diverso da `LISTEN` (`ESTABLISHED`, `TIME_WAIT`, `CLOSE_WAIT`, `FIN_WAIT*`); **oppure** CPU media del processo **più i suoi figli** sopra soglia. Una connessione che resta aperta da un campione all'altro non conta come attività | CPU 1,0% di un core |
| DEV_PROCESS | CPU media nell'intervallo sopra soglia | 1,0% |
| AI_CLI | CPU media sopra soglia | 1,0% |
| CONTAINER | CPU sopra soglia **oppure** traffico di rete (rx+tx su tutte le interfacce tranne `lo`) sopra soglia; la soglia di rete è un **tasso**, quindi non dipende dall'intervallo di campionamento | CPU 1,0%; rete 700 byte/s (~20 KB in 30 s) |
| BROWSER, DESKTOP_APP, TERMINAL | senza tracciamento X11: non misurabile, stato `unknown`. Con il tracciamento X11 attivo (7.8): il campione è attivo se l'app è stata in primo piano nell'intervallo, e l'app diventa `idle` con le stesse regole delle altre entità, anche se non è mai stata in primo piano | |
| SYSTEM, SESSION, SELF | non valutato | |

Regole di stato:

- Un'entità è `active` se almeno un campione della finestra di osservazione (default 30 minuti) è attivo; `since` = primo campione attivo della serie corrente.
- È `idle` se nessun campione della finestra è attivo e la storia copre almeno l'intera finestra; `since` = ultimo campione attivo. Se non c'è mai stato attività dall'avvio del monitor, `since` = il più recente fra l'avvio del processo (`create_time`) e l'ultimo istante persistito (RF-12); il motivo lo dice ("inattivo da almeno 3 h, cioè da quando il monitor è partito").
- È `unknown` se la storia copre meno della finestra (ad esempio subito dopo l'avvio) oppure se il tipo non è misurabile. Il motivo distingue i due casi ("in osservazione da 4 minuti", "attività non misurabile per i browser").
- **Dopo un riavvio** dell'applicazione la storia in memoria è vuota. Per un'entità con la stessa identità di prima (processo: `pid` + `create_time`; container: `id`) e un `last_active_at` persistito (RF-12), lo stato è subito `idle` con `since = last_active_at`, finché la nuova storia non contiene un campione attivo: a quel punto diventa `active`. Senza dato persistito vale la regola della storia corta (`unknown`). La persistenza vince sulla storia corta, mai su un campione attivo.
- Un gruppo è `active` se almeno un membro misurabile è `active`; `idle` se tutti i membri misurabili sono `idle` (`since` = il più recente dei loro `since`); `unknown` altrimenti.
- Caso noto da gestire: un dev server con HMR (vite, next) tiene una websocket aperta finché la scheda del browser è aperta, anche se la scheda è dimenticata. Per questo una connessione persistente **non** rende il server `active`: conta solo una connessione nuova o la CPU. Se il server ricarica perché l'utente modifica i file, la CPU lo segnala comunque. Il motivo lo dice: "inattivo da 3 h; c'è una connessione aperta da un browser (probabile scheda dimenticata su localhost:5173)".

Il motivo è sempre costruito dai numeri misurati, per esempio: "nessuna connessione in ingresso e CPU media 0,1% negli ultimi 30 minuti".

### 5.5 Raggruppamento

Funzione pura `build_groups(processes, containers, config) -> list[Group]`. Chiave di raggruppamento, nell'ordine:

1. Container: label `com.docker.compose.project`; il gruppo prende anche `com.docker.compose.project.working_dir`. Container senza compose: gruppo singolo col nome del container.
2. Processi figli di un'app desktop o del browser: il gruppo dell'antenato più vicino in `DESKTOP_APP`/`BROWSER`/`TERMINAL`.
3. Processi lanciati da terminale (`DEV_SERVER`, `DEV_PROCESS`, `AI_CLI`): radice del progetto ricavata dalla directory di lavoro (`Process.cwd()`), risalendo fino alla prima cartella che contiene uno fra `.git`, `pyproject.toml`, `package.json`, `compose.yaml`, `docker-compose.yml`, `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`, `build.gradle.kts`. Senza radice trovata: la `cwd` stessa.
4. Fusione: se la radice di un gruppo di processi coincide con il `working_dir` di un progetto compose (o ne è antenata o discendente), i due gruppi si fondono in un unico gruppo di progetto. È il caso "whitebox: 6 container + uvicorn sulla 8000".
5. App desktop: un gruppo per scope `app-gnome-<appid>-*` o `snap.<nome>.*`; il nome è il campo `Name` del `.desktop` trovato in `/usr/share/applications`, `~/.local/share/applications`, `/var/lib/snapd/desktop/applications`, `/var/lib/flatpak/exports/share/applications`; in mancanza, l'appid. Una directory illeggibile si salta con un avviso e le voci delle altre restano.
6. Tutto il resto: un gruppo per processo radice.

L'ID di un gruppo deve essere stabile fra campioni (serve a notifiche, silenzi e storia): hash di (categoria, chiave di raggruppamento), non di PID.

### 5.6 Calcolo della memoria

| Entità | "Usata" | "Recuperabile" | Fonte |
|---|---|---|---|
| processo dell'utente | PSS | USS + swap del processo | `psutil.Process.memory_full_info()` (campi `uss`, `pss`, `swap`) **[MISURATO: disponibili]** |
| gruppo di processi | somma dei PSS | somma degli USS + swap | |
| container | `memory.current - inactive_file` (stessa formula di `docker stats`) | uguale a "usata" | `/sys/fs/cgroup/system.slice/docker-<id>.scope/memory.current` e `memory.stat` **[MISURATO: leggibili senza root]** |
| sistema e cache | da `/proc/meminfo`: `MemTotal`, `MemAvailable`, `Cached`, `Buffers`, `SReclaimable`, `Shmem`, `SwapTotal`, `SwapFree` | non recuperabile da qui | |

Scomposizione di RF-02:

- per ogni categoria, la somma dei PSS dei processi utente (o dell'uso dei container);
- "Cache del kernel" = `Cached + Buffers + SReclaimable - Shmem`;
- "Non attribuita" = `MemTotal - MemFree - somma delle voci precedenti`, non negativa.

La UI spiega in una riga che la cache del kernel si libera da sola quando serve.

---

## 6. Architettura

### 6.1 Processo unico

Un solo eseguibile, `wimm`, che è una `Adw.Application` GTK4 residente:

```
 ┌───────────────────────────── wimm (Adw.Application, GTK4, main loop GLib) ─────────────────────────────┐
 │                                                                                                         │
 │  tray/  StatusNotifierItem + com.canonical.dbusmenu  ──clic sinistro──▶  ui/ finestra (nascosta/aperta)  │
 │         (Gio.DBus, nessuna libreria GTK3)                                     │                          │
 │                ▲                                                              │ richieste di piano       │
 │                │ snapshot                                                     ▼                          │
 │  service/ AppService (stato, ultimo snapshot, piani, notifiche, persistenza) ◀── esecuzione confermata  │
 │                ▲                                                                                         │
 │                │ GLib.idle_add(risultato)                                                                │
 │  worker thread: sampler -> collectors -> core (puro) -> Snapshot                                         │
 │  worker thread: scansione disco                                                                          │
 └─────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Perché un processo solo:

- **Vincolo tecnico**: `AyatanaAppIndicator3` è una libreria GTK3, libadwaita richiede GTK4, e le due versioni non convivono nello stesso processo Python. Invece di separare icona e finestra in due processi, l'icona si implementa direttamente sul protocollo D-Bus StatusNotifierItem con `Gio`, che non dipende da nessuna versione di GTK. Il codice esiste già ed è in uso in `sysbar` (sezione 0, punto 9).
- Con `ItemIsMenu = false` e il metodo `Activate`, il clic sinistro apre la finestra direttamente (RF-42). Con AppIndicator il clic sinistro aprirebbe sempre un menu.
- Lo stato vive in un solo posto: niente API D-Bus fra processi propri, niente servizio systemd, niente sincronizzazione.
- Costo: GTK4 resta caricato anche a finestra nascosta (budget in RNF-02).

Separazione interna, obbligatoria anche dentro un processo solo:

- `core/` è logica pura (sezione 5) e non importa `psutil`, `docker` o `gi`.
- `collectors/` legge il sistema e non importa `gi`.
- `service/` è l'unico modulo che esegue azioni (`executor.py`). UI e tray chiedono un piano e poi ne confermano l'esecuzione; non toccano mai processi o Docker direttamente. La validazione di sicurezza (8.2) vive quindi in un solo punto.

### 6.2 Ciclo di vita

- L'autostart di sessione (`/etc/xdg/autostart/io.github.wimm.WhereIsMyMemory.desktop`, `Exec=wimm --background`) avvia l'applicazione al login con la finestra nascosta.
- `application_id = "io.github.wimm.WhereIsMyMemory"` con flag `HANDLES_COMMAND_LINE`: l'applicazione è a istanza unica, e una seconda invocazione (dal lanciatore o con `wimm --group <id>`) passa gli argomenti all'istanza già in esecuzione, che mostra la finestra (eventualmente sul gruppo indicato). Un'applicazione GTK senza finestre termina da sola: `Gio.Application.hold()` la tiene in vita finché non si sceglie "Esci".
- Chiudere la finestra (`close-request`) la nasconde e restituisce `True`; il campionamento continua (RF-44). La finestra si costruisce alla prima apertura, non all'avvio, per contenere la memoria residente.
- **Riavvio di GNOME Shell**: `org.kde.StatusNotifierWatcher` sparisce e ricompare sul bus, e l'icona va ri-registrata. Si sorveglia il nome con `Gio.bus_watch_name` e, a ogni `name-appeared`, si chiama di nuovo `RegisterStatusNotifierItem`. `sysbar` non gestisce questo caso: è il pezzo da aggiungere al codice portato.
- **Nessun host della tray** (estensione disattivata): l'applicazione funziona lo stesso, notifiche comprese. A ogni avvio, se `org.kde.StatusNotifierWatcher` non è sul bus entro 10 s (all'autostart la shell può non averlo ancora pubblicato), la finestra si apre anche con `--background` e mostra un `Adw.Banner` ("L'icona nella barra richiede l'estensione AppIndicator di Ubuntu"). Il banner sparisce quando il watcher compare e l'icona si registra. "Esci" è sempre presente anche nel menu della finestra, così l'app si può chiudere anche senza icona.

### 6.3 Interfaccia interna e D-Bus

**API interna** (`service/app_service.py`), usata da finestra e tray:

| Metodo | Descrizione |
|---|---|
| `snapshot() -> Snapshot \| None` | ultimo snapshot |
| `disk_report() -> DiskReport \| None` | ultimo report disco |
| `rescan_disk() -> None` | avvia una scansione disco asincrona |
| `plan(request: ActionRequest) -> Plan` | costruisce un piano; non esegue niente |
| `execute(plan_id: str, typed_confirmation: str) -> None` | esegue un piano già emesso entro la sua scadenza, in un worker thread; l'esito arriva col segnale `action-finished` |
| `snooze(group_id, seconds)`, `set_ignored(group_id, ignored)`, `snooze_all(seconds)` | silenzi e gruppi ignorati |
| `config()`, `update_config(raw) -> Config` | configurazione validata (11) |

`AppService` è un `GObject.Object` con i segnali `snapshot-updated`, `disk-report-updated`, `action-finished`, emessi sempre sul main loop. Errori come eccezioni nominate in `service/errors.py`: `PlanExpired`, `PlanNotFound`, `TargetChanged`, `ConfirmationMismatch`, `ProtectedTarget`, `DockerUnavailable`, `InvalidRequest`.

**D-Bus esposto** (solo per diagnosi e per i test di accettazione, sul bus di sessione, accessibile solo all'utente stesso): nome `io.github.wimm.WhereIsMyMemory` (quello della `GApplication`), oggetto `/io/github/wimm/Inspector`, interfaccia `io.github.wimm.Inspector1`, sola lettura:

| Membro | Firma | Descrizione |
|---|---|---|
| `GetSnapshot` | `() -> s` | ultimo snapshot in JSON (6.5) |
| `GetDiskReport` | `() -> s` | ultimo report disco in JSON |
| `Version` (proprietà) | `s` | versione del pacchetto |

Nessuna azione è esposta su D-Bus: chi può eseguire un piano è solo la UI, dopo una conferma dell'utente.

Protocolli usati verso l'esterno:

- `org.kde.StatusNotifierItem` (oggetto `/StatusNotifierItem`, proprietà `Category=SystemServices`, `Id`, `Title`, `Status`, `IconName`, `ToolTip`, `ItemIsMenu=false`, `Menu`, `XAyatanaLabel`, `XAyatanaLabelGuide`; metodi `Activate`, `SecondaryActivate`, `ContextMenu`, `Scroll`; segnali `NewIcon`, `NewStatus`, `NewToolTip`, `XAyatanaNewLabel`) e registrazione su `org.kde.StatusNotifierWatcher`.
- `com.canonical.dbusmenu` (oggetto `/MenuBar`) per il menu del clic destro, con `LayoutUpdated` quando le voci cambiano.
- Notifiche con `Gio.Notification` tramite `Gio.Application.send_notification` (9).

### 6.4 Flusso dati del campionamento

1. `GLib.timeout_add_seconds(sample_interval)` (default 30 s) lancia un ciclo nel worker thread (un `ThreadPoolExecutor(max_workers=1)`; un nuovo ciclo non parte se il precedente non è finito).
2. I collector (7) producono dati grezzi in dataclass immutabili (`RawProcess`, `RawContainer`, `RawSocket`, `MemInfo`).
3. `history.append(sample)` aggiorna per ogni entità un ring buffer di campioni (`collections.deque(maxlen=...)`, lunghezza = finestra / intervallo + 1). Le entità sparite da più di 2 cicli vengono eliminate dalla storia.
4. Il core calcola: categorie, gruppi, attività, memoria, rischi, recuperabile, riepilogo. Risultato: `Snapshot`.
5. Il risultato torna sul main loop con `GLib.idle_add`, viene salvato come "ultimo snapshot" ed emesso col segnale `snapshot-updated` di `AppService`.
6. `notify_rules.evaluate(snapshot, notification_state, now)` (funzione pura) decide le notifiche da inviare; il notifier le invia.
7. Ogni 5 minuti lo stato persistente (ultimi istanti di attività, silenzi, notifiche già inviate) viene scritto su disco in modo atomico (file temporaneo + `os.replace`).

La scansione disco gira in un secondo worker separato, all'avvio (ritardata di 2 minuti), ogni 6 ore e su richiesta.

### 6.5 Schema dello snapshot (JSON)

```json
{
  "schema": 1,
  "taken_at": "2026-10-16T10:30:00+02:00",
  "monitor_started_at": "2026-10-16T08:00:00+02:00",
  "memory": {
    "total": 41742000000, "available": 8800000000, "used": 32900000000,
    "swap_total": 4294967296, "swap_used": 120000000,
    "breakdown": {"CONTAINER": 950000000, "DEV_SERVER": 2100000000, "BROWSER": 9800000000,
                  "DESKTOP_APP": 3200000000, "AI_CLI": 2400000000, "kernel_cache": 6500000000,
                  "unattributed": 1900000000}
  },
  "disk": {"mount": "/", "total": 375809638400, "used": 329638211584, "free": 27917287424},
  "reclaimable_now": {"ram": 4200000000, "disk": 7400000000},
  "pressure": "warning",
  "docker": {"available": true, "error": null},
  "groups": [
    {
      "id": "g_3f9a1c",
      "name": "whitebox",
      "category": "PROJECT",
      "protection": "actionable",
      "activity": {"state": "idle", "since": "2026-10-16T05:12:00+02:00",
                   "reason": "nessuna connessione in ingresso e CPU media 0,1% negli ultimi 30 minuti"},
      "memory": {"used": 1100000000, "reclaimable": 1050000000},
      "ports": [8000, 8080],
      "primary_action": {"kind": "stop_group", "risk": "safe"},
      "ignored": false, "snoozed_until": null,
      "explanation": "progetto compose 'whitebox' in /home/bonn/.../ai-whitebox-core più un processo uvicorn lanciato dal terminale nella stessa cartella",
      "members": [
        {"kind": "container", "id": "2c9184903a37", "name": "whitebox-keycloak",
         "image": "quay.io/keycloak/keycloak:26.0.8", "state": "running",
         "memory": {"used": 682000000, "reclaimable": 682000000},
         "mounts": [{"type": "bind", "source": "...", "destination": "/opt/keycloak/vault"}],
         "activity": {"state": "idle", "since": "...", "reason": "..."},
         "actions": [{"kind": "container_stop", "risk": "safe"}]},
        {"kind": "process", "pid": 941149, "create_time": 1760590000.12, "name": "uvicorn",
         "cmdline": ["uvicorn", "app:main", "--port", "8000"], "cwd": "/home/bonn/...",
         "category": "DEV_SERVER", "listen_ports": [8000],
         "memory": {"used": 180000000, "reclaimable": 165000000},
         "activity": {"state": "idle", "since": "...", "reason": "..."},
         "actions": [{"kind": "process_terminate", "risk": "safe"}]}
      ]
    }
  ],
  "protected_summary": [{"label": "Sessione GNOME", "memory": 1400000000, "reason": "componente del desktop"}]
}
```

Le dimensioni sono in byte (interi) nel JSON e si formattano solo nella UI. Le date sono ISO 8601 con fuso.
- `pressure` vale `"ok"`, `"warning"` o `"critical"`: il peggiore fra RAM disponibile e disco libero, confrontati con `pressure_warning_pct` e `pressure_critical_pct` (11). Stessi tre stati dell'icona (RF-41).
- `activity.state` vale `"active"`, `"idle"` o `"unknown"`; `protection` vale `"actionable"` o `"protected"`; `risk` vale `"safe"`, `"caution"` o `"danger"`.

`PROJECT` è la categoria di un gruppo fuso (5.5 punto 4); la scomposizione della memoria la ripartisce sulle categorie dei membri.

---

## 7. Raccolta dati

Tutti i collector stanno in `src/wimm/collectors/`, uno per fonte, e restituiscono dataclass immutabili. Ogni collector gestisce i propri errori: un collector che fallisce produce un dato vuoto con un campo `error` e un log `WARNING`, e non interrompe il ciclo.

### 7.1 Processi (`collectors/processes.py`)

- `psutil.process_iter(attrs=[...])` sui processi; per i processi dell'utente (`uids().real == os.getuid()`) si leggono `name`, `exe`, `cmdline`, `cwd`, `create_time`, `ppid`, `cpu_times`, `memory_full_info`, `terminal`, e `/proc/<pid>/cgroup`, `/proc/<pid>/stat` (campo `tpgid` per il foreground su TTY).
- Per gli altri utenti solo `name`, `uids`, `memory_info().rss` (per la vista Sistema; il PSS non è leggibile).
- `psutil.NoSuchProcess`, `AccessDenied`, `ZombieProcess` si gestiscono per processo: il processo viene saltato (o reso con i campi disponibili) senza interrompere la scansione.
- Costo misurato: 841 processi utente con `memory_full_info()` in 0,58 s **[MISURATO]**. Accettabile ogni 30 s. Se in fase 1 il ciclo supera 1,5 s, si applica l'ottimizzazione di 18-R3.
- Versione di psutil di sistema: 5.9.8 **[MISURATO]**. In questa versione il metodo per processo è `Process.connections()`; `Process.net_connections()` esiste solo da psutil 6.0. Usare `psutil.net_connections()` a livello di sistema (vedi 7.2), che non ha questo problema.

### 7.2 Socket (`collectors/sockets.py`)

- `psutil.net_connections(kind="tcp")`: 75 connessioni in 0,05 s, con il PID valorizzato per i processi dell'utente senza root **[MISURATO]**.
- Derivati: per PID, l'insieme delle porte in `LISTEN`; per PID, il numero di connessioni `ESTABLISHED` la cui porta locale è una porta in `LISTEN` dello stesso processo o di un suo antenato o discendente (i server con worker, come gunicorn, accettano nel figlio).
- Escludere le connessioni il cui indirizzo remoto è un processo dello stesso gruppo che fa health check periodici è fuori scope per la versione 1.0; i falsi `active` dovuti a questo si documentano.

### 7.3 Container (`collectors/docker_source.py`, `collectors/cgroups.py`)

- Elenco e metadati con l'SDK Docker di sistema (`python3-docker` 5.0.3 **[MISURATO]**): `docker.from_env()`, `client.containers.list(all=True)`, attributi `Labels`, `Mounts`, `State`, `Image`, `NetworkSettings.Ports`, `State.Pid`.
- **Non usare `container.stats(stream=False)` nel ciclo**: costa ~1 s per container **[MISURATO: 1,01 s]**, e con 8 container il ciclo durerebbe 8 s. Si leggono invece direttamente i file del cgroup v2, leggibili dall'utente **[MISURATO]**:
  - `/sys/fs/cgroup/system.slice/docker-<id>.scope/memory.current`
  - `/sys/fs/cgroup/system.slice/docker-<id>.scope/memory.stat` (campo `inactive_file`)
  - `/sys/fs/cgroup/system.slice/docker-<id>.scope/cpu.stat` (campo `usage_usec`)
- Traffico di rete: `/proc/<State.Pid>/net/dev`, leggibile senza root **[MISURATO]**; si sommano rx e tx di tutte le interfacce tranne `lo`.
- Fallback: se il path del cgroup non esiste (driver cgroup diverso, Docker rootless, Docker Desktop) si cerca il cgroup leggendo `/proc/<State.Pid>/cgroup`; se nemmeno così si trova, si usa `container.stats(stream=False)` solo per i container in esecuzione, in parallelo, al massimo ogni 5 minuti, e lo si segnala nel motivo dell'attività.
- Docker non raggiungibile (daemon fermo, utente non nel gruppo `docker`, socket assente): lo snapshot riporta `docker.available = false` con il motivo, la UI mostra lo stato vuoto "Docker non disponibile: <motivo>" e il resto funziona.
- Azioni compose: `docker compose -p <project> stop` / `down` / `down -v` via `subprocess.run([...], check=False, timeout=120)` con argomenti in lista, mai `shell=True`. Docker Compose v5.6.0 è installato **[MISURATO]**. **[DA VERIFICARE, T-3.6]** che `docker compose -p <nome> down` funzioni senza file compose (usando solo le label); se non funziona, il fallback è stop e rimozione dei container per label `com.docker.compose.project=<nome>` tramite SDK, più `client.networks.prune(filters={"label": "com.docker.compose.project=<nome>"})`.

### 7.4 Memoria di sistema (`collectors/meminfo.py`)

Parsing di `/proc/meminfo` (valori in kB, convertiti in byte). Funzione pura `parse_meminfo(text) -> MemInfo` testata su fixture.

### 7.5 Disco del filesystem (`collectors/disk.py`)

`shutil.disk_usage("/")` e, se configurato, delle altre mount di interesse (default solo `/` e la mount che contiene la home, se diversa).

### 7.6 Report disco (`collectors/disk_report.py`, `collectors/devdirs.py`, `collectors/caches.py`)

- Docker: `client.api.df()` (presente in docker 5.0.3 **[MISURATO]**) restituisce `Images`, `Containers`, `Volumes`, `BuildCache` con dimensioni e conteggi d'uso. Classificazioni:
  - immagine **in uso**: referenziata da almeno un container, anche fermo;
  - **dangling**: senza tag (`RepoTags` vuoto o `<none>:<none>`);
  - **costruita in locale**: `RepoDigests` vuoto;
  - volume **orfano**: `UsageData.RefCount == 0`.
- Cache utente note, misurate con una funzione di dimensione ricorsiva (7.6.1):
  - uv: `~/.cache/uv`, pulizia con `uv cache prune` (`safe`);
  - npm: `~/.npm/_cacache`, pulizia con `npm cache clean --force` (`safe`);
  - pip: `~/.cache/pip`, pulizia con `pip cache purge` se `pip` esiste, altrimenti rimozione della cartella (`safe`);
  - cestino: `~/.local/share/Trash` (`danger`);
  - `~/.cache/thumbnails` (`safe`).
- Cartelle di dipendenze: nelle radici configurate si cercano le cartelle ricostruibili elencate sotto, il cui progetto (la cartella padre) non ha file modificati da più di `devdirs_min_age_days` (default 90). Senza una scelta salvata le radici sono le cartelle candidate che contengono un repository `.git` entro 2 livelli: `~/code`, `~/projects`, `~/src`, `~/dev`, `~/git`, `~/workspace`, `~/Documents`, `~/Documenti` e la cartella documenti di `~/.config/user-dirs.dirs`, saltando i mount di rete, FUSE e autofs; altre radici si aggiungono dalle preferenze. La ricerca non scende dentro una cartella trovata, non segue symlink, salta le cartelle nascoste tranne i nomi dell'elenco, e ha una profondità massima (default 6). Un progetto che sta direttamente nella home è sempre escluso.
  - `node_modules`;
  - `.venv` e `venv`, solo con `pyvenv.cfg` dentro;
  - `.tox`, con `tox.ini`, `pyproject.toml` o `setup.cfg` nel progetto;
  - `target`, con `Cargo.toml` o `pom.xml`;
  - `.gradle` e `build`, con `build.gradle`, `build.gradle.kts`, `settings.gradle` o `settings.gradle.kts`;
  - `.next` e `.nuxt`, con `package.json`;
  - `vendor`, solo con `composer.json`.
  Per `target`, `vendor`, `build`, `.next`, `.nuxt` e `.gradle` il marker non basta: serve anche `CACHEDIR.TAG` dentro la cartella oppure il nome nel `.gitignore` del progetto, letto come testo senza eseguire git.
  Il "modificato" del progetto si stima sui file al primo livello e su `src/` (non su tutto l'albero, troppo costoso).

#### 7.6.1 Calcolo delle dimensioni

`os.scandir` ricorsivo, somma di `stat().st_blocks * 512` (spazio occupato, non dimensione apparente), con inode già visti saltati (hard link), senza seguire symlink, con `time.sleep(0)` ogni 1.000 voci per cedere il GIL e una pausa di 10 ms ogni 10.000 voci per non saturare l'I/O. Risultati in cache con il `mtime` della cartella radice; una cartella non cambiata non si ricalcola.

### 7.7 Browser

La memoria per scheda non è accessibile dall'esterno (`about:processes` di Firefox è interno al browser). Il gruppo `BROWSER` mostra: memoria totale (PSS), numero di processi, ripartizione per tipo di processo quando il nome lo indica (in Firefox `Isolated Web Co`, `WebExtensions`, `RDD Process`, `GPU Process`, `Socket Process`), e un suggerimento statico: "Per liberare memoria senza chiudere il browser apri `about:unloads` (Firefox) o il task manager con Shift+Esc (Chrome)". Firefox su questa macchina è uno snap (157.0.1) **[MISURATO]**.

### 7.8 Primo piano su X11 (opzionale, T-5.5)

Sulla sessione X11 (`XDG_SESSION_TYPE=x11` **[MISURATO]**), l'app in primo piano si legge dalla proprietà `_NET_ACTIVE_WINDOW` della root window e da `_NET_WM_PID` della finestra, tramite `xprop` (installato, 1.2.6 **[MISURATO]**) o tramite GdkX11. A ogni ciclo si registra il PID in primo piano: per `BROWSER` e `DESKTOP_APP` il campione è attivo se l'app è stata in primo piano nell'intervallo. Così Slack aperto e mai guardato da tre giorni diventa `idle`. Su Wayland la funzione si disattiva da sola e lo stato resta `unknown`.

---

## 8. Azioni

### 8.1 Flusso

1. La finestra chiama `AppService.plan(request)` con una richiesta (`ActionRequest(kind="stop_group", group_id="g_3f9a1c")`).
2. Il servizio costruisce il piano con la funzione pura `plan_action(request, snapshot) -> Plan`: elenco dei bersagli con la loro **impronta** (8.2), azione per bersaglio, rischio aggregato, conseguenze, recupero stimato, frase di conferma se `danger`, `plan_id` casuale (`secrets.token_urlsafe(16)`), scadenza (120 s).
3. La finestra mostra il dialogo di conferma (8.3).
4. Alla conferma la finestra chiama `AppService.execute(plan_id, typed_confirmation)`.
5. Il servizio verifica la scadenza e la frase, poi in un worker thread **rilegge lo stato attuale di ogni bersaglio** e lo confronta con l'impronta. Se un bersaglio è cambiato, l'intero piano viene rifiutato con `TargetChanged` e la finestra ne richiede uno nuovo. Se un bersaglio è già sparito (processo già terminato), si segna come "già fatto" e si prosegue.
6. Esecuzione (8.4), misura del liberato (differenza di `MemAvailable` e dello spazio libero prima e dopo, dopo 3 s), segnale `action-finished` con l'esito per bersaglio, e un campionamento immediato per aggiornare la vista.

Un piano si esegue una sola volta: dopo l'esecuzione o la scadenza viene eliminato.

**Tipi di richiesta** (`ActionKind`, enum in `model/enums.py`): `process_terminate`, `process_kill`, `app_close`, `container_stop`, `container_remove`, `group_stop`, `compose_down`, `compose_down_volumes`, `stop_all_idle_safe`, `image_remove`, `images_prune_dangling`, `images_prune_unused`, `builder_prune`, `containers_prune_stopped`, `volume_remove`, `cache_clean`, `trash_empty`, `devdir_delete`, `disk_free_safe` (libera in un passo tutto ciò che sul disco è `safe`), `container_start` e `restart_stopped` (riaccende i container fermati da un piano precedente). `ActionRequest(kind, group_id | None, target_id | None)`.

**Campi del piano** (`Plan`, dataclass frozen): `plan_id`, `request`, `created_at`, `expires_at`, `steps: tuple[PlanStep, ...]`, `risk` (il massimo degli step), `consequences: tuple[str, ...]`, `estimated_reclaim_ram`, `estimated_reclaim_disk`, `confirm_phrase: str | None` (solo `danger`). `PlanStep(order, kind, target_label, fingerprint, risk)`.

**Semantica di `group_stop`**: prima i processi (terminate, 8.4), poi i container (`container.stop` via SDK, in parallelo, uno per container: non serve il file compose e non serve `docker compose stop`). L'ordine evita che un'app server registri errori di connessione al database mentre si ferma. **Successo parziale**: si eseguono tutti gli step anche se uno fallisce, nessun rollback, esito per step (`ok`, `already_gone`, `not_responding`, `failed` con la causa); il toast riassume ("3 su 4 fermati, 1 non risponde") e il pulsante "Dettagli" mostra gli step.

### 8.2 Impronte e validazioni (defense in depth)

| Bersaglio | Impronta | Validazioni all'esecuzione |
|---|---|---|
| processo | `pid`, `create_time`, `uid`, hash di `cmdline` | stesso `create_time` (contro il riuso dei PID), `uid == os.getuid()`, categoria non protetta, non è `wimm` stesso né un suo antenato |
| container | `id`, `State.Status` | esiste, stato compatibile con l'azione |
| progetto compose | nome, insieme degli id dei container | stesso insieme di container |
| immagine | `id` | non usata da alcun container al momento dell'esecuzione |
| volume | `name` | `RefCount == 0` al momento dell'esecuzione |
| cartella | path reale (`os.path.realpath`), `st_ino`, `st_dev` | non è un symlink, è dentro una radice configurata, il nome e il marker del progetto rispettano ancora la regola della §7.6, stesso inode |

La protezione si ricontrolla nell'executor anche se il piano l'ha già esclusa: il controllo nel planner serve alla UI, quello nell'executor è la garanzia.

### 8.3 Conferme per rischio

- `safe`: `Adw.AlertDialog` con titolo ("Fermare whitebox?"), elenco dei bersagli, recupero stimato ("libera circa 1,1 GB di RAM"), pulsanti "Annulla" e "Ferma" (stile `suggested-action`).
- `caution`: come sopra, con le conseguenze in un riquadro di avviso e il pulsante in stile `destructive-action`.
- `danger`: come `caution`, più un `Adw.EntryRow` "Scrivi `<nome>` per confermare"; il pulsante si abilita solo quando il testo coincide. Il servizio ricontrolla la frase (`ConfirmationMismatch`).
- Azioni multiple (RF-24): un solo dialogo con l'elenco raggruppato, il totale stimato e la possibilità di togliere singole voci prima di confermare.
- Selezione multipla (RF-53): un solo dialogo "Libera i selezionati", con le voci raggruppate per rischio (prima `safe`, poi `caution`), la conseguenza di ciascuna, il totale stimato e la possibilità di togliere singole voci prima di confermare. Il livello del dialogo è quello della voce più rischiosa; le voci `danger` non sono selezionabili (Q3=A) e non compaiono, quindi non serve la frase digitata.

### 8.4 Esecuzione

- **Termina processo**: si calcola l'albero (`proc.children(recursive=True)`), si invia SIGTERM ai figli e poi alla radice (alcuni wrapper come `npm` non inoltrano il segnale), si attende con `psutil.wait_procs(..., timeout=terminate_timeout)` (default 5 s). Se resta qualche processo vivo, l'esito è "non risponde" e il pannello offre "Forza chiusura", che è un nuovo piano con rischio proprio. Nessun SIGKILL automatico.
- **Chiudi app desktop o browser**: SIGTERM al processo principale del gruppo (non ai figli: il browser chiude da sé i suoi processi e salva la sessione), stessa attesa. **[DA VERIFICARE, T-3.8]** che Firefox snap con SIGTERM chiuda conservando la sessione; se non la conserva, la conseguenza mostrata va aggiornata di conseguenza.
- **Container**: `container.stop(timeout=10)`, `container.remove(v=False)`.
- **Compose**: comandi della 7.3.
- **Immagini**: `client.images.remove(image_id, noprune=False)`; dangling: `client.images.prune(filters={"dangling": True})`; tutte le inutilizzate: `client.images.prune(filters={"dangling": False})`.
- **Build cache**: `client.api.prune_builds()` (presente in 5.0.3 **[MISURATO]**).
- **Volumi**: `client.volumes.get(name).remove()`.
- **Cache**: comandi della 7.6 con `subprocess.run` a lista e timeout.
- **Cartelle**: dopo le validazioni della 8.2, rimozione che apre ogni directory con `O_NOFOLLOW|O_DIRECTORY` e cancella con `dir_fd`, senza seguire symlink; una sottodirectory su un altro `st_dev` o elencata come mount in `/proc/self/mountinfo` resta intatta e viene registrata. Gli errori per voce si registrano senza interrompere.
- **Cestino**: rimozione del contenuto di `~/.local/share/Trash/files` e `~/.local/share/Trash/info`.

Ogni azione eseguita si registra con un log `INFO` strutturato: azione, bersaglio, esito, byte liberati.

---

## 9. Notifiche

- Invio con `Gio.Notification` e `Gio.Application.send_notification(id, notification)`, con `id = "idle-<group_id>"` o `"pressure-ram"`/`"pressure-disk"`: lo stesso id sostituisce la notifica precedente invece di accumularne. Le azioni sono azioni dell'applicazione (`app.open-group` e `app.snooze-group` con parametro `s` = `group_id`), quindi funzionano anche a finestra chiusa. Nessuna dipendenza da `libnotify`.
- Regole in una funzione pura `evaluate_notifications(snapshot, state, now, config) -> list[NotificationIntent]`:
  - **idle**: gruppo `actionable`, `idle`, `now - since >= notify_after` (default 2 h), recuperabile >= `notify_min_bytes` (default 200 MB), non ignorato, non silenziato, categoria tra quelle con notifiche attive (default: PROJECT, CONTAINER, DEV_SERVER, DEV_PROCESS; AI_CLI e DESKTOP_APP disattivate di default), nessuna notifica già inviata per questo episodio di inattività (l'episodio è identificato da `group_id + since`);
  - **pressione**: RAM disponibile < 10% o disco libero < 10%, al massimo una ogni ora per tipo;
  - **limite**: al massimo 3 notifiche in 60 minuti; quelle in eccesso si aggregano in una sola.
- Testi (esempi da rispettare nel tono, illustrativi):
  - titolo "whitebox è inattivo da 2 h", corpo "4 container e 1 server, 1,1 GB di RAM recuperabile.";
  - titolo "RAM quasi esaurita (7% libera)", corpo "Liberabile subito: whitebox 1,1 GB, vite (frontend) 640 MB, jupyter 410 MB.";
  - aggregata: titolo "4 gruppi inattivi", corpo "3,8 GB di RAM recuperabile. Apri il pannello per vederli."
- Azioni: `app.open-group` (mostra la finestra sul gruppo) e `app.snooze-group` (silenzia 24 h).

---

## 10. Interfaccia utente

### 10.1 Icona nella barra (`tray/`)

- StatusNotifierItem portato da `sysbar` (6.3), registrato su `org.kde.StatusNotifierWatcher`, con `Id = "io.github.wimm.WhereIsMyMemory"` e `Category = "SystemServices"`. Icone a colori installate in `/usr/share/icons/hicolor/scalable/status/`: `wimm-normal` (il logo dell'app), `wimm-warning` e `wimm-critical` (il logo con un badge "!" giallo o rosso) (RF-41). Decisione dell'utente (2026-10-17): ovunque compaia un'icona dell'app, tray compresa, si mostra il logo di `assets/logo/wimm-logo.png`; tutte le icone si rigenerano da quel file con `uv run python scripts/build_icons.py`, cambiate con il segnale `NewIcon`.
- Etichetta (RF-40) nella proprietà `XAyatanaLabel`, aggiornata con `XAyatanaNewLabel`; `XAyatanaLabelGuide` contiene la stringa più lunga prevista ("88,8 GB inattivi") per evitare che la barra cambi larghezza. Il tooltip ripete il riepilogo a parole ("Memoria usata 79%, disco: 28 GB liberi").
- `Activate` (clic sinistro) mostra la finestra e la porta in primo piano; se è già in primo piano non la nasconde. `SecondaryActivate` (clic centrale) fa lo stesso.
- Il menu del clic destro (RF-42) è servito con `com.canonical.dbusmenu`. Il modello delle voci è una funzione pura `build_menu(snapshot) -> list[MenuItem]` in `tray/menu_model.py`; il layout si ripubblica (`LayoutUpdated`) solo se l'hash delle voci è cambiato, per evitare flicker.
- Se il campionamento fallisce per 3 cicli di fila, l'icona passa allo stato di avviso e la prima voce del menu dice "Monitoraggio in errore: apri il pannello per i dettagli".

### 10.2 Pannello (`wimm`)

GTK4 con libadwaita 1.5 (installata **[MISURATO]**; `Adw.AlertDialog` e `Adw.ToastOverlay` disponibili). Finestra `Adw.ApplicationWindow` di 960x720 al primo avvio, ridimensionabile, dimensioni ricordate. Larghezza minima 360 px: sotto i 600 px un `Adw.Breakpoint` porta il layout a una colonna e nasconde le colonne secondarie delle righe.

Struttura:

```
┌ Adw.HeaderBar ─ [Panoramica | Disco | Sistema] (Adw.ViewSwitcher) ─ [↻] [⋮ menu: Preferenze, Silenzia 1 h, Info, Esci] ┐
├ Riepilogo ───────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ RAM  ███████████████████░░░░  30,1 / 38,9 GB   disponibile 8,2 GB   swap 0,1 GB                                  │
│      [barra segmentata per categoria + legenda]                                                                  │
│ Disco /  ████████████████████░  307 / 350 GB   liberi 26 GB                                                      │
│ Recuperabile ora: 4,2 GB di RAM · 7,4 GB di disco          [Ferma tutti gli inattivi sicuri]                     │
├ Filtri: (Tutti) (Inattivi) (Categoria ▾) (Rischio ▾)       Cerca… ───────────────────────────────────────────────┤
│ ▸ whitebox               Progetto · inattivo da 5 h            1,1 GB   [Sicuro]   [Ferma]                       │
│   nessuna connessione in ingresso e CPU media 0,1% negli ultimi 30 minuti · porte 8000, 8080                     │
│ ▸ Firefox                Browser · attività non misurabile    9,8 GB   [Attenzione]  [Chiudi…]                   │
│ ▸ frontend (vite)        Dev server · in uso                    640 MB  [Attenzione]  [Ferma…]                   │
└──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Panoramica**: `Gtk.ListView` (o `Adw.PreferencesGroup` con `Adw.ExpanderRow` se i gruppi sono meno di 200) con un gruppo per riga. Titolo = nome; sottotitolo = categoria, stato e durata; seconda riga = motivo e porte; suffissi = RAM recuperabile, badge del rischio, pulsante dell'azione principale. Espandendo la riga si vedono i membri (RF-05), ciascuno con le sue azioni, e i pulsanti "Silenzia" e "Ignora". Menu contestuale con "Copia comando", "Apri cartella" (`Gio.AppInfo.launch_default_for_uri`), "Copia PID".
- **Disco**: sezioni `Adw.PreferencesGroup`: Docker (immagini, container fermi, volumi, build cache), Cache, Cartelle di dipendenze, Cestino. Ogni riga ha dimensione, stato, rischio e azione. Le sezioni stanno in tre fasce per costo ("Si libera senza pensarci", "Da guardare prima", "Attenzione: cancella dati") e ogni riga sta nella fascia del proprio rischio: le cache e le immagini con rischi diversi si dividono in più sezioni. In testa, "Ultimo controllo alle 10:12" e il pulsante "Controlla ora", che durante la scansione diventa "Controllo in corso" con lo spinner.
- **Sistema**: elenco in sola lettura (RF-07) con il motivo della protezione.
- **Preferenze**: `Adw.PreferencesDialog` con i campi della RF-50; i valori passano da `AppService.update_config` e si validano lì.

Il badge del rischio non si affida al solo colore: ha sempre il testo ("Sicuro", "Attenzione", "Pericolo") e usa le classi di stile di libadwaita `success`, `warning`, `error`.

Formati: dimensioni con `GLib.format_size` (unità SI, separatore decimale della locale: "1,1 GB"); durate relative ("da 5 h", "da 3 giorni", "da 12 min"); orari locali.

### 10.3 Stati dell'interfaccia

| Superficie | Loading | Empty | Error | Edge |
|---|---|---|---|---|
| Panoramica | `Adw.Spinner` (o `Gtk.Spinner`) con "Raccolta dati in corso…"; oltre 15 s "Ci sta mettendo più del previsto" | "Niente di inattivo. Tutto ciò che è acceso risulta in uso." con il filtro "Inattivi" attivo; senza filtri non può essere vuota | `Adw.StatusPage` "Il monitor non risponde" con causa e pulsante "Riavvia monitor" | 300+ gruppi, nomi di 200 caratteri con ellissi, cmdline molto lunghe, gruppo senza porte, `cwd` non leggibile |
| Disco | spinner sulla sezione in scansione, il resto visibile | "Nessuna cartella di dipendenze più vecchia di 90 giorni nelle radici configurate" | "Docker non disponibile: <motivo>" solo nella sezione Docker | 10.000+ cartelle trovate (mostrare le prime 200 per dimensione con un contatore), volumi senza dimensione nota |
| Dialogo di conferma | pulsante in loading durante l'esecuzione, campi bloccati | n/d | esito per bersaglio con causa; i bersagli riusciti restano segnati come riusciti | piano scaduto: messaggio "La situazione è cambiata, ricalcolo…" e nuovo piano |
| Icona | icona normale senza etichetta finché non arriva il primo snapshot | etichetta assente sotto 100 MB | icona di avviso e "Monitor non attivo" | |

Ogni esito di azione appare come `Adw.Toast` che nomina il soggetto e l'esito ("whitebox: arresto completato. Liberati 1,0 GB di RAM"; la forma "soggetto: esito" evita gli errori di accordo di genere), con il pulsante "Dettagli" se qualche bersaglio è fallito.

### 10.4 Accessibilità

- Tutto è raggiungibile e azionabile da tastiera; ordine di tabulazione naturale; `Ctrl+F` sulla ricerca, `F5` per aggiornare, `Ctrl+,` per le preferenze.
- Ogni pulsante solo icona ha `tooltip_text` e un nome accessibile (`update_property([Gtk.AccessibleProperty.LABEL], [...])`).
- Il rischio e lo stato sono sempre espressi anche a testo.
- La barra segmentata della RAM ha un'alternativa testuale (la legenda con i valori).

---

## 11. Configurazione e persistenza

| File | Contenuto | Formato |
|---|---|---|
| `~/.config/where-is-my-memory/config.json` | preferenze (RF-50) | JSON, scritto solo da `AppService` |
| `~/.local/state/where-is-my-memory/state.json` | ultimi istanti di attività per entità e per gruppo, silenzi, gruppi ignorati, episodi già notificati | JSON, scrittura atomica |
| `~/.cache/where-is-my-memory/disk-cache.json` | dimensioni di cartelle e mtime (7.6.1) | JSON |

Si usa JSON e non TOML perché l'applicazione deve scrivere il file e `tomllib` della stdlib sa solo leggere. I path si risolvono con `GLib.get_user_config_dir()`, `get_user_state_dir()`, `get_user_cache_dir()`.

Modello della configurazione: `@dataclass(frozen=True) Config` con valori di default e una funzione `parse_config(raw: dict) -> Config` che valida tipi e intervalli, scarta le chiavi sconosciute con un `WARNING` e, su un valore invalido, tiene il default per quel campo senza far cadere l'applicazione.

Valori di default (in `core/constants.py`):

| Chiave | Default | Intervallo |
|---|---|---|
| `sample_interval_s` | 30 | 10-300 |
| `activity_window_s` | 1800 | 300-14400 |
| `cpu_active_threshold_pct` | 1.0 | 0.1-50 |
| `net_active_threshold_bps` | 700 | 0-10485760 |
| `notify_after_s` | 7200 | 600-604800 |
| `notify_min_bytes` | 209715200 | 0-... |
| `notify_categories` | `["PROJECT","CONTAINER","DEV_SERVER","DEV_PROCESS"]` | sottoinsieme delle categorie actionable |
| `pressure_warning_pct` | 15 | 5-50 |
| `pressure_critical_pct` | 10 | 1-50 |
| `max_notifications_per_hour` | 3 | 1-20 |
| `terminate_timeout_s` | 5 | 1-60 |
| `devdirs_roots` | `["~/Documenti/00_Lavoro"]` | path esistenti nella home |
| `devdirs_min_age_days` | 90 | 7-3650 |
| `devdirs_max_depth` | 6 | 1-12 |
| `disk_scan_interval_s` | 21600 | 3600-604800 |
| `extra_protected_names` | `[]` | si aggiungono alla lista protetta, non la sostituiscono |
| `foreground_tracking` | `true` | attivo solo su X11 |

---

## 12. Packaging e installazione

### 12.1 Pacchetto

- Nome `where-is-my-memory`, architettura `all`, sezione `utils`, priorità `optional`, licenza GPL-3.0-or-later (sezione 0, punto 9).
- `Depends: python3 (>= 3.12), python3-gi, python3-psutil, python3-docker, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.5)`. Tutti installati sulla macchina **[MISURATO]** per python3-gi 3.48.2, python3-psutil 5.9.8, python3-docker 5.0.3, gir1.2-adw-1 1.5.0; **[DA VERIFICARE, T-2.1]** il nome esatto di `gir1.2-gtk-4.0` con `apt-cache policy`.
- `Recommends: gnome-shell-extension-appindicator | gnome-shell-extension-ubuntu-appindicators, docker-ce-cli | docker.io, x11-utils` (nomi da verificare in T-2.1). L'estensione è solo raccomandata perché senza di essa l'app funziona lo stesso (6.2).
- Nessuna dipendenza da `gir1.2-ayatanaappindicator3-0.1` né da GTK3.
- Il runtime usa il Python di sistema e i moduli apt: nessun venv né pip nel pacchetto.

### 12.2 File installati

```
/usr/lib/python3/dist-packages/wimm/                               codice
/usr/bin/wimm                                                       entry point (#!/usr/bin/python3, from wimm.app import main)
/etc/xdg/autostart/io.github.wimm.WhereIsMyMemory.desktop           avvio al login (Exec=wimm --background)
/usr/share/applications/io.github.wimm.WhereIsMyMemory.desktop      lanciatore (Exec=wimm)
/usr/share/icons/hicolor/{16,24,32,48,64,128,256,512}x…/apps/io.github.wimm.WhereIsMyMemory.png
/usr/share/icons/hicolor/scalable/status/wimm-{normal,warning,critical}.svg
/usr/share/metainfo/io.github.wimm.WhereIsMyMemory.metainfo.xml
/usr/share/doc/where-is-my-memory/copyright
```

Il lanciatore ha `DBusActivatable=false` e `X-GNOME-UsesNotifications=true` (richiesto da GNOME per mostrare le notifiche di `Gio.Notification` attribuite all'app). Il file di autostart ha `X-GNOME-Autostart-enabled=true` e `NoDisplay=true`.

### 12.3 Script del pacchetto

- `postinst`: aggiornamento della cache delle icone (`gtk-update-icon-cache -q /usr/share/icons/hicolor || true`) e del database dei lanciatori (`update-desktop-database -q || true`). Nessun avvio forzato nelle sessioni attive: il README dice di fare logout e login, oppure di lanciare `wimm --background`.
- `prerm`: nessuna azione necessaria; l'istanza in esecuzione continua fino a "Esci" o al logout.
- Build: `scripts/build_deb.sh` copia i file in una staging dir con la struttura sopra, genera `DEBIAN/control` con la versione letta da `pyproject.toml`, `Maintainer` preso da `WIMM_MAINTAINER` o, in mancanza, da `git config user.name` e `user.email` (il build fallisce se nessuno dei due è disponibile, invece di inventare un valore), `Description: tray monitor for forgotten containers, dev servers and apps` con una descrizione estesa di 2-3 righe, calcola `Installed-Size` e lancia `dpkg-deb --build --root-owner-group staging dist/where-is-my-memory_<ver>_all.deb`. Se `lintian` è disponibile lo esegue e fallisce sugli errori (gli warning si riportano).
- Disinstallazione pulita: `apt remove` lascia i file utente in `~/.config`, `~/.local/state` e `~/.cache`, come da convenzione Debian; `apt purge` non li tocca (sono dati dell'utente) e il README lo dice.

---

## 13. Requisiti non funzionali

| ID | Requisito | Come si misura |
|---|---|---|
| RNF-01 | Il processo `wimm` usa in media meno dell'1% di un core a finestra nascosta | `pidstat -p <pid> 60 10` con 800+ processi utente |
| RNF-02 | Memoria del processo `wimm` sotto 120 MB RSS a finestra mai aperta, sotto 200 MB dopo aver aperto e nascosto la finestra | `ps -o rss` dopo 1 h di funzionamento |
| RNF-03 | Un ciclo di campionamento completo sotto 1,5 s con 900 processi e 10 container; il main loop non resta mai bloccato più di 50 ms (il lavoro pesante sta nei worker thread) | log `DEBUG` con la durata del ciclo; nessun ritardo percepibile su clic e scroll durante un ciclo |
| RNF-04 | La finestra si apre con i dati in meno di 1 s (lo snapshot è già pronto) | cronometro dal clic sull'icona al primo render |
| RNF-05 | Nessun privilegio elevato: nessun `sudo`, `pkexec`, capability o setuid | revisione del codice e del pacchetto |
| RNF-06 | Nessuna azione su processi di altri utenti o protetti, anche chiamando l'executor con un piano costruito a mano che salta il planner | test dell'executor (15) |
| RNF-07 | Nessun `subprocess` con `shell=True`; argomenti sempre in lista, sempre con timeout | `ruff` regola `S602`/`S604` attiva |
| RNF-08 | Logging con il modulo `logging` su stderr (raccolto nel journal della sessione) e su file rotante `~/.local/state/where-is-my-memory/wimm.log` (`RotatingFileHandler`, 1 MB x 3); livello configurabile con `WIMM_LOG_LEVEL`; mai cmdline complete a livello `INFO` (possono contenere token passati come argomenti): a `INFO` solo nome e PID | revisione e test sul formatter |
| RNF-09 | Il sistema funziona senza Docker installato o senza permessi Docker | test con collector Docker finto che solleva eccezione |
| RNF-10 | L'applicazione sopravvive a qualsiasi eccezione di un collector o di una regola: il ciclo successivo riparte | test con collector che solleva |
| RNF-11 | Riavvio dell'applicazione (o logout e login) senza perdere i tempi di inattività (RF-12) | test di persistenza |

---

## 14. Struttura del repository

```
where-is-my-memory/
├── README.md                 installazione, uso, disinstallazione, FAQ ("perché il browser è 'non misurabile'?")
├── CLAUDE.md                 comandi, architettura in breve, convenzioni
├── LICENSE                   GPL-3.0-or-later
├── Makefile                  setup, test, lint, run, deb
├── pyproject.toml
├── docs/
│   ├── REPORT_ATTIVITA.md
│   └── DEVIATIONS.md         scostamenti da questa specifica con evidenza
├── assets/
│   └── SPECIFICHE.md         questo documento
├── specs/where-is-my-memory/ plan.md, tasks.md (piano derivato)
├── src/wimm/
│   ├── __init__.py           __version__
│   ├── app.py                main(), Adw.Application, opzioni --background / --group
│   ├── model.py              dataclass condivise (RawProcess, RawContainer, Entity, Group, Snapshot, Plan, ...)
│   ├── serialize.py          Snapshot <-> JSON (schema 1)
│   ├── config.py             Config, parse_config, load/save
│   ├── logging_setup.py
│   ├── core/                 SOLO logica pura, nessun import di psutil/docker/gi
│   │   ├── constants.py
│   │   ├── categorize.py     categorie e protezione (5.1, 5.2)
│   │   ├── grouping.py       raggruppamento e fusione (5.5)
│   │   ├── activity.py       regole di attività (5.4)
│   │   ├── memory.py         calcoli di memoria e scomposizione (5.6)
│   │   ├── risk.py           rischio per azione (5.3)
│   │   ├── planning.py       plan_action, impronte (8.1, 8.2)
│   │   ├── notify_rules.py   evaluate_notifications (9)
│   │   ├── disk_rules.py     classificazione di immagini, volumi, cartelle (7.6)
│   │   └── text.py           motivi e conseguenze in italiano
│   ├── collectors/           lettura del sistema, nessun import di gi
│   │   ├── processes.py  sockets.py  cgroups.py  docker_source.py
│   │   ├── meminfo.py    disk.py     disk_report.py  devdirs.py  caches.py
│   │   └── foreground.py     (opzionale, 7.8)
│   ├── service/
│   │   ├── app_service.py    AppService (GObject): stato, segnali, API interna (6.3)
│   │   ├── sampler.py        orchestrazione del ciclo nel worker thread
│   │   ├── history.py        ring buffer per entità
│   │   ├── state_store.py    persistenza atomica
│   │   ├── executor.py       esecuzione dei piani con validazione (8.2, 8.4)
│   │   ├── notifier.py       Gio.Notification
│   │   ├── inspector_dbus.py interfaccia D-Bus di sola lettura (6.3)
│   │   └── errors.py
│   ├── tray/                 portato da sysbar
│   │   ├── status_notifier.py  dbus_menu.py  menu_model.py (puro)  tray.py
│   │   └── watcher.py        ri-registrazione al riavvio di GNOME Shell (6.2)
│   └── ui/
│       ├── window.py  viewmodel.py (puro: snapshot -> righe)
│       ├── pages/ overview.py  disk.py  system.py
│       ├── widgets/ summary.py  group_row.py  risk_badge.py  memory_bar.py
│       └── dialogs/ confirm.py  preferences.py
├── data/
│   ├── desktop/  icons/  metainfo/  dbus/ (XML di introspezione)
├── packaging/
│   └── debian/ control.in  postinst  prerm  copyright
├── scripts/
│   ├── build_deb.sh
│   ├── test_deb.sh
│   └── dev_run.sh            avvia l'app dal sorgente
└── tests/                    stessa struttura di src/wimm
    ├── fixtures/             meminfo, cgroup, output docker df, snapshot di esempio
    ├── core/  collectors/  service/  tray/  ui/
    └── integration/          marcati @pytest.mark.integration
```

### 14.1 Ambiente di sviluppo

- uv per sviluppo e test, con il venv che vede i moduli di sistema (PyGObject, psutil e docker vengono dai pacchetti apt, non da PyPI, per testare esattamente le versioni del runtime):

  ```bash
  uv venv --system-site-packages --python /usr/bin/python3
  uv sync
  ```

- `pyproject.toml`: `[build-system]` con `hatchling` (serve solo a `uv sync` in sviluppo; il `.deb` copia i sorgenti e non usa il build backend), `[project.scripts] wimm = "wimm.app:main"`, `requires-python = ">=3.12"`, `dependencies = []`. psutil e docker **non** vanno nelle dipendenze: uv installerebbe nel venv versioni più nuove di quelle apt e i test girerebbero su librerie diverse da quelle del `.deb`. Il runtime è dichiarato in `debian/control`. `[dependency-groups] dev = ["pytest", "pytest-cov", "ruff", "mypy", "pygobject-stubs", "types-psutil", "types-docker"]`. **[DA VERIFICARE, T-0.1]** che le versioni degli stub siano compatibili con psutil 5.9 e docker 5.0; altrimenti si pinnano versioni coerenti. Un test di T-0.1 verifica che `psutil.__version__` nel venv sia quello di sistema.
- Ruff: `select = ["E","F","W","I","B","UP","S","SIM","RUF"]`, line-length 100. Mypy `strict` su `src/wimm/core` e `src/wimm/model.py`, normale sul resto.
- Makefile (verbi `setup`, `test`, `lint`, `run`, `deb`):

  ```make
  setup:  uv venv --system-site-packages --python /usr/bin/python3 && uv sync
  test:   uv run pytest -m "not integration and not ui and not dbus"
  test-all: dbus-run-session -- xvfb-run -a uv run pytest
  lint:   uv run ruff check . && uv run ruff format --check . && uv run mypy src
  run:    scripts/dev_run.sh
  deb:    scripts/build_deb.sh
  ```

  (nel file reale con TAB e un comando per riga). `test-all` include integrazione, D-Bus e UI, e si esegue a fine fase.
- Opzioni della riga di comando di `wimm` (in `app.py`, con `Gio.Application.add_main_option`): `--background` (avvia senza mostrare la finestra), `--group <id>` (mostra la finestra su un gruppo), `--version` (stampa la versione ed esce, senza registrarsi sul bus). Variabili d'ambiente: `WIMM_APP_ID` (default `io.github.wimm.WhereIsMyMemory`), `WIMM_LOG_LEVEL` (default `INFO`).
- `scripts/dev_run.sh` avvia l'app dal sorgente con `WIMM_APP_ID=io.github.wimm.WhereIsMyMemory.Devel`, così non entra in conflitto con un'eventuale versione installata (istanza unica e icona distinte).

---

## 15. Strategia di test

| Livello | Cosa | Come |
|---|---|---|
| Unità (core) | categorizzazione, raggruppamento, fusione progetti, attività, memoria, rischio, planning, regole di notifica, regole disco, testi, modello del menu, viewmodel | pytest su dataclass costruite nel test; nessun mock necessario. Copertura >= 90% su `core/` |
| Unità (parsing) | `/proc/meminfo`, `/proc/<pid>/cgroup`, `memory.stat`, `cpu.stat`, `net/dev`, output di `docker df` | fixture testuali in `tests/fixtures/` copiate dal formato reale |
| Collector | gestione di `NoSuchProcess`, `AccessDenied`, Docker assente | fake dei moduli (`psutil`, client Docker) iniettati per costruttore |
| Executor | rifiuto di bersagli protetti, di altri utenti, con impronta cambiata, piano scaduto, frase sbagliata, piano costruito a mano senza planner; ordine dei segnali; nessun SIGKILL automatico | `ProcessControl` e `DockerControl` come `Protocol`, con fake che registrano le chiamate |
| Servizio | `AppService` con collector finti: snapshot emesso, piani, scadenze, silenzi, persistenza | pytest con un `GLib.MainContext` iterato nel test |
| Integrazione | ciclo reale su bersagli creati dal test: un `python3 -m http.server` su porta libera (diventa `DEV_SERVER`, poi `idle` con finestra ridotta a 20 s, poi terminato tramite piano); container `alpine sleep` con label `wimm.test=1` fermato e rimosso | `@pytest.mark.integration`, si esegue con `uv run pytest -m integration`; i bersagli si ripuliscono in `finally` |
| D-Bus | interfaccia Inspector e StatusNotifierItem su un bus di sessione privato: `GetSnapshot` restituisce JSON valido, la registrazione sul watcher avviene, un watcher finto che sparisce e ricompare riceve una nuova registrazione | `dbus-run-session -- uv run pytest -m dbus`, con un watcher finto scritto nel test |
| UI | smoke test di costruzione della finestra con snapshot di fixture, filtri, dialoghi | `xvfb-run -a uv run pytest -m ui` (xvfb-run installato **[MISURATO]**) |
| Pacchetto | build, installazione in un container `ubuntu:24.04` con `apt install ./dist/*.deb`, verifica dei file e di `wimm --version` | `scripts/test_deb.sh` |

Regole: ogni asserzione negativa ("non termina un processo protetto") ha accanto il caso positivo che dimostra che lo stesso percorso termina un processo non protetto. Nessun test esegue azioni su processi o container che il test non ha creato.

---

## 16. Piano di implementazione

Ogni fase si chiude con `make lint` e `make test` verdi e con il proprio `verify:` osservato. I task sono da 10-30 minuti. Il pacchetto arriva subito dopo la sola visione: così l'utente usa lo strumento ogni giorno già dalla fase 2, e le fasi successive si provano sull'installazione reale.

### Fase 0 - Scheletro (prerequisito, non rilascia funzionalità)

- **T-0.1** `pyproject.toml`, venv con `--system-site-packages`, ruff, mypy, pytest, Makefile, CLAUDE.md, LICENSE, README minimo. verify: `make lint && make test` verdi; un test verifica che `psutil.__version__ == "5.9.8"` e `docker.__version__ == "5.0.3"` nel venv (cioè le versioni di sistema).
- **T-0.2** `model.py` con le dataclass della sezione 6.5 e `serialize.py` con round-trip JSON. verify: test di round-trip su uno snapshot di fixture.

### Fase 1 - Sola visione (usabile: si vede cosa occupa memoria e disco)

- **T-1.1** `collectors/meminfo.py` e `core/memory.py` (parsing e scomposizione). verify: test su fixture; valori coerenti con `free -b` eseguito nello stesso istante (scarto < 2%).
- **T-1.2** `collectors/processes.py` con lettura del cgroup ed esclusione dei processi dei container. verify: test con fake; esecuzione reale che elenca i processi utente in meno di 1,5 s.
- **T-1.3** `collectors/sockets.py`. verify: un `python3 -m http.server 0` avviato dal test compare con la sua porta in `LISTEN`.
- **T-1.4** `core/categorize.py` con la lista protetta. verify: tabella di test con un caso per riga della tabella 5.1, cgroup reali della sezione 5.1 inclusi.
- **T-1.5** `collectors/cgroups.py` e `collectors/docker_source.py` (lettura, nessuna azione). verify: i container in esecuzione compaiono con memoria entro il 5% di `docker stats --no-stream`.
- **T-1.6** `core/grouping.py` con la fusione progetto. verify: test in cui container compose e un processo con `cwd` nella `working_dir` producono un solo gruppo.
- **T-1.7** `service/history.py` e `core/activity.py`. verify: test sulle regole 5.4, inclusi i casi `unknown` (storia corta) e HMR (connessione persistente che non conta come attività).
- **T-1.8** `service/sampler.py`, `service/app_service.py` (solo snapshot), `service/inspector_dbus.py`, `app.py` con `--background`. verify: `gdbus call --session --dest io.github.wimm.WhereIsMyMemory.Devel --object-path /io/github/wimm/Inspector --method io.github.wimm.Inspector1.GetSnapshot` restituisce JSON valido.
- **T-1.9** Finestra: `ui/viewmodel.py`, riepilogo, panoramica con gruppi espandibili, vista Sistema, stati della 10.3, chiusura che nasconde. verify: avvio da `make run`, i gruppi reali sono visibili, i filtri funzionano, chiudere la finestra non termina il processo, la finestra a 360 px non ha sovrapposizioni (screenshot).
- **T-1.10** Tray portato da `sysbar`: StatusNotifierItem con etichetta e icona a tre stati, dbusmenu col menu della RF-42 (senza azioni), `Activate` che apre la finestra. verify: l'icona compare nella barra, il clic sinistro apre la finestra, il clic destro mostra il menu, un gruppo del menu apre la finestra espansa su quel gruppo, l'etichetta compare.
- **T-1.11** `tray/watcher.py`, ri-registrazione al riavvio della shell. verify: test D-Bus con watcher finto; prova manuale con `Alt+F2`, `r` (riavvio di GNOME Shell su X11): l'icona ricompare senza riavviare l'app.

### Fase 2 - Pacchetto (usabile: installato e avviato al login)

- **T-2.1** File in `data/` (lanciatore, autostart, icone SVG, metainfo), nomi dei pacchetti di `Depends` e `Recommends` verificati con `apt-cache policy`. verify: `desktop-file-validate` e `appstreamcli validate` senza errori.
- **T-2.2** `scripts/build_deb.sh`, `postinst`, `prerm`. verify: `dpkg-deb --info` e `--contents` corretti; `lintian` senza errori.
- **T-2.3** `scripts/test_deb.sh` in container `ubuntu:24.04`. verify: installazione pulita, `wimm --version` stampa la versione, `apt remove` non lascia file di sistema.
- **T-2.4** README per l'utente finale: installazione, primo avvio (logout e login), dove stanno i file, come disinstallare, FAQ. verify: un lettore che non conosce il progetto installa e trova il pannello seguendo solo il README.

### Fase 3 - Azioni su processi e container

- **T-3.1** `core/risk.py` (tabella 5.3) e `core/text.py`. verify: un test per riga della tabella.
- **T-3.2** `core/planning.py` con impronte e scadenza. verify: test su piani per gruppo, membro e "tutti gli inattivi sicuri" (che esclude `caution` e `danger`).
- **T-3.3** `service/executor.py` per i processi con validazioni 8.2. verify: test con fake per ogni rifiuto e per l'ordine SIGTERM figli poi radice; test di integrazione su `http.server` creato dal test.
- **T-3.4** Executor per i container (stop, remove). verify: integrazione su container `alpine` con label `wimm.test=1`.
- **T-3.5** `AppService.plan` ed `execute` nel worker thread, segnale `action-finished`, misura del liberato, campionamento immediato dopo l'azione. verify: test del servizio con executor finto; l'esito arriva sul main loop.
- **T-3.6** Azioni compose; verifica della premessa di 7.3 (`down` senza file). verify: progetto compose di test con 2 container `alpine` creato in una tmpdir, fermato e rimosso; esito registrato in `docs/DEVIATIONS.md` se serve il fallback.
- **T-3.7** Dialoghi di conferma per i tre livelli, toast, "Forza chiusura" su processo che ignora SIGTERM. verify: click-through sulla finestra con un server di test: conferma, esito, liberato mostrato; la conferma `danger` resta disabilitata finché il nome non coincide.
- **T-3.8** Chiusura di browser e app desktop; verifica della premessa sulla sessione di Firefox. verify: esito registrato; conseguenza mostrata allineata all'osservazione.

### Fase 4 - Notifiche, silenzi, preferenze

- **T-4.1** `core/notify_rules.py`. verify: test su episodio unico, limite orario, aggregazione, categorie disattivate, pressione con cooldown.
- **T-4.2** `service/notifier.py` con `Gio.Notification` e le azioni "Apri" e "Silenzia 24 h". verify: con `notify_after_s` a 60 e un server di test inattivo, la notifica compare e "Apri" apre la finestra sul gruppo.
- **T-4.3** `service/state_store.py` e persistenza (RF-12), silenzi, gruppi ignorati. verify: riavvio dell'app, il gruppo resta "inattivo da" lo stesso istante; un gruppo ignorato non notifica.
- **T-4.4** Preferenze (`config`, `update_config`, dialogo). verify: un valore fuori intervallo viene rifiutato con messaggio sul campo; un valore valido cambia il comportamento al ciclo successivo.

### Fase 5 - Disco

- **T-5.1** `core/disk_rules.py` e `collectors/disk_report.py` per Docker. verify: valori coerenti con `docker system df -v`.
- **T-5.2** `collectors/caches.py` e `collectors/devdirs.py` con calcolo 7.6.1 e cache. verify: test su albero creato in tmpdir (symlink, hard link, cartelle annidate); scansione reale delle radici di default sotto i 60 s alla prima esecuzione e sotto i 5 s alla seconda.
- **T-5.3** Azioni disco (8.4) con validazioni sulle cartelle. verify: test che rifiuta un path fuori dalle radici, un symlink, un nome diverso da `node_modules`/`.venv`; integrazione su immagine `alpine` taggata dal test.
- **T-5.4** Vista Disco nella finestra. verify: click-through su ogni tipo di riga con un bersaglio di test.
- **T-5.5** (opzionale) `collectors/foreground.py` per X11 (7.8). verify: un'app tenuta in background per una finestra di test passa a `idle`; su Wayland la funzione risulta disattivata.

### Fase 6 - Disco granulare (usabile: ogni riga spiega cosa si perde, le cache si aprono per elemento, si libera più di una voce con un solo dialogo)

Piano e requisiti in `specs/002-disk-granular/` (`plan.md`, `spec.md`, `tasks.md`); questa specifica prevale. Decisioni dell'utente del 2026-10-19: **O1** (la conseguenza è il sottotitolo della riga, il badge si riduce a Sicuro, Attenzione, Pericolo), **O3** (le cache si espandono per elemento, con una voce "Non attribuito" per i byte fuori dagli elementi), **Q1=A** (i blob esclusivi del magazzino HuggingFace si rimuovono con il modello, ricontrollati all'esecuzione), **Q2=A** (ollama anche come servizio di sistema, via `ollama list` e `ollama rm`), **Q3=A** (le voci `danger` non sono selezionabili nella selezione multipla), **Q4=A** (nessun elemento per Maven in questa fase). Decisioni dell'utente del 2026-10-20 sul lotto L5 (`specs/002-disk-granular/design-l5-ollama.md`): **D1** (con il server di sistema attivo i modelli della home restano visibili senza azione, con il motivo), **D2** (la pulizia intera della home ollama resta rifiutata con qualunque server attivo), **D3** (dimensioni dei modelli di sistema stimate da `ollama list`, dichiarate in pagina), **D4** (i modelli di sistema entrano nei totali della pagina Disco). Ordine di esecuzione: L0, L1, L2, L3, L6, L4, L5; ogni lotto è rilasciabile da solo. Lo schema del report passa da 4 a 5 (RF-51, RF-52). T-6.1 è l'aggiornamento di questa specifica.

**Lotto L0: specifica e baseline**

- **T-6.2** Baseline: numero di test (`make test`), durata della scansione disco sulla home reale; voce DEVIATIONS "HuggingFace: rimozione per elemento senza il comando del tool" (assunzione del plan). verify: riga baseline in `docs/PERF.md` con comando e condizioni.

**Lotto L1: spiegazione in riga (O1)**

- **T-6.3** `core/row_consequence.py`: `row_consequence(kind, target, marker)` puro, testo = prima conseguenza di `assess_risk` o `devdir_consequence`. verify: `tests/core/test_row_consequence.py` parametrico su ogni `CacheKind`, devdir con e senza marker, immagine locale e da registry.
- **T-6.4** Il planner usa `row_consequence` per cache e devdir (stesso testo del dialogo); `planning_disk.py` resta <= 290 righe. verify: test esistenti verdi; `test_plan_cache_clean_consequence_matches_row_consequence`.
- **T-6.5** `DiskRowView.consequence`; `make_row` riceve il testo e usa `RISK_TEXT` per il badge. verify: `tests/ui/test_disk_model.py::test_make_row_badge_is_the_short_risk_text` + caso appaiato riga senza azione.
- **T-6.6** Righe di cache, cestino, devdir (`disk_view.py`) e Docker (`disk_view_docker.py`) passano la conseguenza. verify: `tests/ui/test_disk_view.py::test_cache_row_subtitle_carries_the_dialog_consequence` e una riga per tipo.
- **T-6.7** Rimozione di `DISK_RISK_CONSEQUENCE` se orfano; `make po`, traduzioni. verify: `grep -rn DISK_RISK_CONSEQUENCE src` vuoto; `make lint`.
- **T-6.8** GTK: sottotitolo percorso + conseguenza su righe separate, `subtitle_lines=4`, nome accessibile con la conseguenza. verify: test `-m ui` sul nome accessibile; render osservato a 360 e 1280 px senza sovrapposizioni; click-through di un bottone per sezione.
- **T-6.9** Chiusura L1: `code-reviewer`, riga `CHECKS:`, REPORT_ATTIVITA. verify: `make lint && make test` verdi, test > baseline.

**Lotto L2: elementi delle cache in sola lettura (O3)**

- **T-6.10** `model/cache_items.py`: `CacheItem`, `CacheRest`; `CacheEntry.items`/`rest` opzionali; `disk_wire` (`OPTIONAL_FIELDS`), `SCHEMA_VERSION` 5, XML D-Bus. verify: `tests/core/test_disk_wire.py` round-trip con elementi; schema 4 rifiutato; validazione: somma <= size.
- **T-6.11** `core/cache_items.py`: `TreeListing` (nomi, tipi, dimensioni, target dei link), dispatch per tipo, `CACHE_ITEMS_CAP`=50, ordinamento, resto = size meno elementi. verify: `tests/core/test_cache_items.py::test_items_and_rest_sum_to_cache_size`; tipo senza regola → nessun elemento.
- **T-6.12** `core/cache_items_hf.py`: repo `models--`/`datasets--`/`spaces--`, file regolari + blob raggiunti solo dai suoi link, condiviso, non attribuito; link fuori dalla cache ignorati. verify: `tests/core/test_cache_items_hf.py` con fixture che riproduce il layout misurato (magazzino `blobs/3b/...`, un repo standard, un blob condiviso, un blob orfano, un link verso `/tmp`).
- **T-6.13** `collectors/cache_items.py`: `scandir` senza seguire link, `readlink`, dimensioni via `measure_dir_size`; `collect_caches` allega gli elementi. verify: test su albero in `tmp_path`; nessun `os.path.realpath` su link fuori cache (test).
- **T-6.14** Rimisura della scansione con lo stesso comando di T-6.2. verify: riga risultato, aumento <= 15% o causa e scelta dichiarate.
- **T-6.15** `ui/disk_items.py`: sotto-righe pure (titolo leggibile `org/nome` da `models--org--nome`, "Condiviso fra più modelli", "Non attribuito" con la sua frase, "e altre N"). verify: `tests/ui/test_disk_items.py` con il report di fixture HF.
- **T-6.16** GTK: riga di cache con elementi come `Adw.ExpanderRow`, sotto-righe senza azione in questa fase; bottone della cache "Pulisci tutta la cache". verify: test `-m ui`: espansione mostra 5 modelli e "Non attribuito"; render 360/1280; click-through espandi/chiudi.
- **T-6.17** `make po`, traduzioni; DEVIATIONS schema 5. verify: `make lint`.
- **T-6.18** Chiusura L2: `code-reviewer`, `type-design-analyzer` sui tipi nuovi, `CHECKS:`. verify: suite verde; scansione reale mostra XTTS-v2 con i GB del magazzino.

**Lotto L3: rimozione del singolo modello HuggingFace**

- **T-6.19** `ActionKind.CACHE_ITEM_REMOVE`, `TargetShape.TARGET`, `ItemFingerprint` (cartella + blob esclusivi con ino/dev). verify: `tests/model/test_actions.py` validazione dell'impronta.
- **T-6.20** `core/planning_cache_item.py` + voci in `risk_table` (rischio per elemento); verifica con context7 di `huggingface_hub` cache API, esito in DEVIATIONS. verify: `tests/core/test_planning_cache_item.py`: piano con un passo, id sconosciuto → `InvalidRequest`.
- **T-6.21** `service/executor_cache_item.py`: controlli di S12 (cache in tabella, regola pura, niente link, owner, impronta). verify: `tests/service/test_executor_cache_item.py::test_*_is_refused` (`../`, fuori tabella, link, owner, ino cambiato), ognuno con il caso che passa; bersaglio intatto.
- **T-6.22** Rimozione HF: esclusività ricalcolata sui link attuali, `remove_directory` sulla cartella, `remove` dei blob esclusivi via `safe_tree`; blob diventato condiviso → resta, esito lo dice. verify: test in `tmp_path`: blob esclusivo rimosso, blob condiviso dopo il piano intatto, liberato = byte rimossi.
- **T-6.23** Dispatch dell'azione nel servizio, rimisura della cache dopo l'esito. verify: test del servizio con executor finto: esito con liberato, report aggiornato.
- **T-6.24** GTK: "Rimuovi" sulle sotto-righe, testi del dialogo (`dialogs/text.py`), `make po`. verify: click-through su un modello di test in una HOME isolata: dialogo, conferma, esito, riga sparita.
- **T-6.25** Chiusura L3: `security-reviewer` su T-6.21-T-6.22, `code-reviewer`, `CHECKS:`. verify: suite verde.

**Lotto L6: selezione multipla (eseguita dopo L3)**

- **T-6.26** `ActionKind.DISK_FREE_SELECTED`, `ActionRequest.selected_ids` (solo per questa azione), escludibile. verify: validazione: `selected_ids` vuoto o su altra azione → `ValueError`.
- **T-6.27** `core/planning_disk_selected.py`: un passo per id dai planner singoli, DANGER rifiutato (Q3=A), cache intera e suoi elementi non insieme. verify: `tests/core/test_planning_disk_selected.py` con il caso di DoD (elemento CAUTION + build cache).
- **T-6.28** `ui/disk_selection.py`: stato puro della selezione, esclusione reciproca cache/elementi, totale, azzeramento a ogni nuovo report. verify: `tests/ui/test_disk_selection.py`.
- **T-6.29** GTK: modalità "Seleziona", caselle, "Libera i selezionati (N, X GB)", dialogo raggruppato per rischio; `make po`. verify: click-through: seleziona 2 voci, togline una nel dialogo, conferma; render 360/1280.
- **T-6.30** Chiusura L6: `code-reviewer`, `CHECKS:`. verify: suite verde.

**Lotto L4: Android SDK, AVD, Playwright, JetBrains**

- **T-6.31** `core/cache_items_android.py`: pacchetti SDK da `package.xml` (id `path` con `;`), mai `cmdline-tools`/`licenses`; AVD da `<nome>.ini` + `<nome>.avd`. verify: fixture con `platforms/android-35/package.xml`; `licenses` assente dagli elementi.
- **T-6.32** Executor SDK: `sdkmanager --sdk_root=<cache> --uninstall <id>` (argv verificato con `--help` nel task), solo con il tool, nessun fallback di cancellazione. verify: `test_item_argv_android_sdk` con runner finto; tool assente → azione non offerta.
- **T-6.33** Executor AVD: `avdmanager delete avd -n <nome>`; rifiuto con emulatore `-avd <nome>` in esecuzione. verify: test con processo finto in esecuzione → rifiuto; caso appaiato senza.
- **T-6.34** `core/cache_items_misc.py`: Playwright (`<browser>-<rev>`) e JetBrains (prodotto+versione); rimozione via `safe_tree`. verify: fixture con 2 revisioni di chromium; nome non riconosciuto → non elemento.
- **T-6.35** Testi, `make po`, `security-reviewer`, `code-reviewer`, `CHECKS:`. verify: suite verde.

**Lotto L5: ollama per modello (dopo la risposta a Q2)**

- **T-6.36** Elementi ollama dalla home: manifest `manifests/<host>/<ns>/<nome>/<tag>`, dimensione dai layer, layer condivisi in "Condiviso". verify: fixture con due modelli che condividono un layer.
- **T-6.37** (Q2=A) collector `ollama list` con timeout per l'installazione di sistema: voce di sola rimozione, nessun accesso ai file. verify: parser su output reale registrato come fixture; tool assente → nessuna voce.
- **T-6.38** Executor `ollama rm <nome>:<tag>`: richiede il server attivo (inverso di `OllamaServing`), argv in lista. verify: test: server assente → rifiuto con messaggio; pulizia intera con server attivo resta rifiutata.
- **T-6.39** GTK e testi della conferma DANGER (frase = nome del modello), `make po`. verify: click-through con runner finto.
- **T-6.40** Chiusura L5: `security-reviewer`, `code-reviewer`, `CHECKS:`, REPORT_ATTIVITA. verify: suite verde.

---

## 17. Definition of Done

Il sistema è completo quando, sulla macchina dell'utente con il `.deb` installato:

1. Dopo un logout e un login, l'icona compare nella barra in alto senza azioni manuali e `pgrep -f "/usr/bin/wimm"` trova un processo.
2. Il clic sinistro sull'icona apre la finestra in meno di 1 s, con RAM, swap e disco coerenti con `free -b` e `df -B1 /` (scarto < 2%). Chiudere la finestra non termina il processo; "Esci" dal menu sì.
3. I container dei progetti `whitebox` e `luve-agent` compaiono raggruppati per progetto, con memoria coerente con `docker stats` (scarto < 5%).
4. Un `python3 -m http.server 8765` lanciato da terminale in una cartella di progetto compare come dev server di quel progetto, risulta `active` mentre lo si interroga con `curl` ogni 10 s, e `idle` dopo la finestra di osservazione senza richieste, con il motivo che riporta i numeri misurati.
5. Firefox compare come gruppo `BROWSER` con PSS totale (non RSS sommato), rischio "Attenzione" e attività "non misurabile" (o misurata col primo piano, se T-5.5 è fatto).
6. I componenti della sessione GNOME, dockerd e i processi di altri utenti compaiono solo nella vista Sistema, senza pulsanti di azione.
7. Fermare un gruppo `idle` dalla finestra mostra l'anteprima, esegue, e riporta il liberato misurato; il processo e i container risultano fermi.
8. La rimozione di un volume chiede di digitare il nome e rifiuta un nome diverso.
9. Un piano costruito a mano che punta a un processo protetto o di un altro utente, passato direttamente all'executor, viene rifiutato con `ProtectedTarget` (test automatico).
10. Con un gruppo inattivo oltre la soglia arriva una sola notifica; "Silenzia 24 h" la sopprime; dopo un riavvio dell'app il tempo di inattività è conservato.
11. La vista Disco mostra immagini inutilizzate e build cache coerenti con `docker system df`, e la pulizia della build cache libera lo spazio indicato (scarto < 10%).
12. Dopo un riavvio di GNOME Shell l'icona ricompare senza riavviare l'app.
13. `make lint` e `make test` verdi, copertura >= 90% su `src/wimm/core`, test di integrazione e D-Bus verdi.
14. Requisiti non funzionali RNF-01, RNF-02 e RNF-03 misurati e riportati in `docs/REPORT_ATTIVITA.md` con i numeri.

---

## 18. Rischi e decisioni di ripiego

| ID | Rischio | Segnale | Ripiego |
|---|---|---|---|
| R1 | L'host della tray (estensione `ubuntu-appindicators`) cambia comportamento o viene disattivato | icona assente, watcher assente sul bus | l'app resta utilizzabile dal lanciatore e con le notifiche; banner nella finestra (6.2) |
| R2 | Il codice SNI portato da `sysbar` non gestisce un caso (riavvio della shell, etichetta, icona a tema) | T-1.10, T-1.11 | correzione nel modulo `tray/`, annotata in `docs/DEVIATIONS.md` e segnalata anche per `sysbar` |
| R3 | Ciclo di campionamento oltre 1,5 s | log di durata | `memory_full_info()` solo per i processi con RSS > 30 MB a ogni ciclo, gli altri ogni 5 cicli; RSS come approssimazione segnalata nel dettaglio |
| R4 | Falsi `active` (health check, websocket HMR, polling dei reloader) | gruppi che non diventano mai `idle` | il motivo mostra il segnale; soglie configurabili; nella 1.0 nessuna euristica nascosta |
| R5 | Falsi `idle` (server usato a raffiche con più di 30 minuti fra una richiesta e l'altra) | utente che ferma qualcosa che stava usando | azione `safe` solo perché il riavvio è a un comando; la conseguenza mostrata cita come riavviarlo (cmdline e cwd copiabili) |
| R6 | Riuso dei PID fra piano ed esecuzione | | impronta con `create_time` (8.2) |
| R7 | `docker compose -p down` richiede i file compose | T-3.6 | fallback con SDK per label (7.3) |
| R8 | Firefox snap perde la sessione con SIGTERM | T-3.8 | conseguenza aggiornata e, se la perde, "Chiudi browser" passa a `danger` con frase di conferma = nome dell'app ("Firefox") |
| R9 | Cgroup dei container in posizione diversa (Docker rootless, driver diverso) | path assente | ricerca via `/proc/<pid>/cgroup`, poi `stats(stream=False)` limitato (7.3) |
| R10 | Wayland in futuro | `XDG_SESSION_TYPE=wayland` | foreground tracking disattivato; tutto il resto è indipendente da X11 |
| R11 | Cmdline con segreti nei log o negli screenshot | | log a `INFO` senza cmdline (RNF-08); nella UI la cmdline completa compare solo espandendo il membro |

---

## Appendice A - Comandi di verifica rapida

```bash
# processo e bus
pgrep -af "/usr/bin/wimm"
gdbus introspect --session --dest io.github.wimm.WhereIsMyMemory --object-path /io/github/wimm/Inspector
gdbus call --session --dest io.github.wimm.WhereIsMyMemory --object-path /io/github/wimm/Inspector \
  --method io.github.wimm.Inspector1.GetSnapshot | head -c 600

# icona registrata sul watcher
gdbus call --session --dest org.kde.StatusNotifierWatcher --object-path /StatusNotifierWatcher \
  --method org.freedesktop.DBus.Properties.Get org.kde.StatusNotifierWatcher RegisteredStatusNotifierItems

# confronto con gli strumenti di sistema
free -b; df -B1 /; docker stats --no-stream; docker system df -v

# log
tail -f ~/.local/state/where-is-my-memory/wimm.log
journalctl --user -f | grep wimm
```

## Appendice B - Fatti misurati sulla macchina di destinazione (2026-10-16)

- Ubuntu 24.04.5 LTS, GNOME, sessione X11, estensioni attive: `ubuntu-appindicators@ubuntu.com`, `ubuntu-dock@ubuntu.com`, `tiling-assistant@ubuntu.com`.
- Python di sistema 3.12.3; python3-gi 3.48.2; python3-psutil 5.9.8 (ha `Process.connections`, non `Process.net_connections`; `memory_full_info` espone `uss`, `pss`, `swap`); python3-docker 5.0.3 (`APIClient.df` e `APIClient.prune_builds` presenti; `stats` senza parametro `one_shot`); libadwaita 1.5 (`Adw.AlertDialog`, `Adw.ToastOverlay` presenti); gir1.2-ayatanaappindicator3-0.1 0.5.93.
- Docker server 29.9.0, Docker Compose v5.6.0, cgroup v2 con scope `system.slice/docker-<id>.scope`; `memory.current`, `memory.stat`, `cpu.stat` e `/proc/<pid>/net/dev` dei container leggibili dall'utente senza root.
- `container.stats(stream=False)`: 1,01 s per container.
- Scansione di 841 processi utente con `memory_full_info()`: 0,58 s. `psutil.net_connections("tcp")`: 75 connessioni in 0,05 s, PID presenti per i processi dell'utente.
- Firefox snap 157.0.1, cgroup `snap.firefox.firefox-<uuid>.scope`; processi lanciati da gnome-terminal in `vte-spawn-<uuid>.scope`.
- Disponibili: `xprop` 1.2.6, `xvfb-run`, `notify-send`.
