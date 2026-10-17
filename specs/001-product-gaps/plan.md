# 001 product gaps: piano

Riferimenti: `spec.md` (R1-R43; R25 è fuori scope, R35 è confluito in R33), `tasks.md`
(T001-T107), `assets/SPECIFICHE.md` (prevale), ADR-001..005. Stato di partenza misurato il
2026-10-18: `main` pulito a `6c9a134`, `make lint` pulito, `make test` 2082 passed.

## Obiettivo

Alla fine di ogni lotto l'app è rilasciabile e fa una cosa in più per uno sviluppatore Linux
qualsiasi: trova da sola le sue cartelle di progetto, parla inglese fuori dall'Italia, riconosce
le cartelle e le cache di Rust, Go, Java, JS e Python, vede Podman e i contesti Docker, spiega la
memoria che oggi resta "Non attribuita", segnala la pressione vera (PSI, OOM), funziona da
terminale senza finestra, e si installa oltre Ubuntu.

## Approccio

1. **Ordine per impatto su costo.** L1 toglie ciò che oggi rende l'app inutilizzabile a chi non
   è l'autore (radice `~/Documenti/00_Lavoro`, italiano su locale tedesca, solo node e Python);
   L2 rende ogni rilascio successivo verificabile; poi le estensioni che allargano il pubblico
   (cache, motori container), poi la diagnosi della memoria, poi le funzioni con decisioni di
   sicurezza o di prodotto aperte (F2, F5, F14, F4), per ultimo il packaging.
2. **Il core resta puro.** Ogni regola nuova (radici candidate, nome di cartella con marker,
   catalogo cache, endpoint Docker, etichette degli strumenti, voci di memoria, PSI, crescita,
   politica delle radici) è una funzione pura in `src/wimm/core/` testata per prima; i collector
   leggono e passano dati; l'executor applica **la stessa** funzione pura al momento
   dell'esecuzione (defense in depth di §8.2), mai una copia.
3. **Rischio per coppia entità/azione (ADR-003).** `CACHE_CLEAN` passa da statico a dipendente dal
   tipo di cache; i nuovi strumenti di F10 hanno rischio per etichetta. "Libera spazio" filtra
   sul rischio calcolato, non su un elenco di tipi.
4. **File al limite prima di crescere.** `app_service.py` (300), `sampler.py` (299),
   `categorize.py` (291), `config.py` (290), `serialize.py` (290), `app.py` (286) e
   `constants.py` (208, ma cresce di ~60 righe con le cache) si scompongono in un commit
   `refactor` separato e senza cambi di comportamento prima del task che li estende.
5. **Schema dello snapshot.** Il parser è stretto (`serialize.py:82` rifiuta campi sconosciuti),
   quindi ogni campo nuovo è una rottura per chi legge `GetSnapshot`. La politica la sceglie
   l'utente (Q4); il piano assume Q4=A (un bump per lotto che cambia la forma).
6. **Ogni lotto si chiude** con `make lint && make test`, `code-reviewer`, `security-reviewer`
   dove tocca executor o config, click-through delle superfici GTK (a11y-gate non si applica a
   GTK, si usano i test del nome accessibile già presenti), riga `CHECKS:` e voce in
   `docs/REPORT_ATTIVITA.md`. Commit atomici su `main`, mai push.

## Lotti

| Lotto | F | Contenuto | Stima (con 20% di buffer) | Rilasciabile perché |
|---|---|---|---|---|
| L1 | F1 F3 F7 F8 | radici rilevate, avviso radice mancante, inglese di default, cartelle e marker per Rust/Go/Java/JS/Python | 2,5-3,5 g | ogni voce è indipendente e non cambia lo schema |
| L2 | F17 (auto) | `make audit` (bandit, pip-audit) in CI, man page, metainfo, misura RNF-04, M-* aggiornate | 1-1,5 g | solo build e documentazione |
| L3 | F6 (basso rischio) | catalogo cache con XDG e variabili, rischio per tipo, comandi nativi | 3-4 g | report disco esteso, schema disco +valori enum |
| L4 | F9 F10 | podman, contesti Docker, Docker Desktop; etichette per VM, emulatore, daemon, LSP, kind/minikube | 3-4 g | il motore di default resta quello di oggi se non c'è contesto |
| L5 | F11 F12 | voci nuove della RAM, VRAM a parte, PSI, notifica OOM | 3-4 g | bump di schema (Q4) |
| L6 | F6 (alto costo) | HF, ollama, Android AVD/SDK con CAUTION/DANGER | 1,5-2 g | estende L3, nessuna voce in "Libera spazio" |
| L7 | F2 | radici fuori dalla home con ADR-007 | 2-2,5 g | config retrocompatibile, executor più severo, non meno |
| L8 | F5 F13 | sessioni SSH opzionali, indicatore di crescita | 2,5-3 g | opzione spenta di default; bump di schema |
| L9 | F15 | `wimm status [--json]` | 1,5-2 g | nuovo sottocomando, nessun cambio alla GUI |
| L10 | F14 | comando di riavvio dei processi fermati | 1,5-2,5 g | solo copia (Q7=A) o anche riavvio (Q7=B) |
| L11 | F4 | Wayland secondo ADR-006 | 1-5 g (dipende dall'opzione) | componente opzionale, senza resta il comportamento di oggi |
| L12 | F16 | formati di Q5, banner AppIndicator per distribuzione | 2-5 g | il .deb resta il formato di riferimento |

Totale: 25-43 giorni lavorativi con buffer. Il range largo viene da L11 e L12, che dipendono da
ADR-006 e Q5; L1-L10 sommano 21,5-29 g. Stima calibrata sul piano originale (71 task in 10-13 g):
qui i task toccano codice esistente (moltiplicatore brownfield 1,5) e ogni lotto ha la sua
chiusura con review.

## File da modificare

| File | Tipo | Lotto | Scopo |
|---|---|---|---|
| `src/wimm/config_roots.py` | nuovo | L1, L7 | estrazione da `config.py` della logica radici, radici mancanti, politica |
| `src/wimm/core/dev_roots.py` | nuovo | L1 | candidate e scelta delle radici (puro) |
| `src/wimm/collectors/root_candidates.py` | nuovo | L1 | lettura limitata delle candidate e di `user-dirs.dirs` |
| `src/wimm/core/constants.py` | modifica | L1, L3, L4, L5 | via `DEVDIRS_ROOTS` personale, marker unici, costanti PSI e crescita |
| `src/wimm/config.py` | modifica | L1, L7, L8 | default radici, radici mancanti, `remote_sessions_actionable` |
| `src/wimm/i18n.py` | modifica | L1 | `resolve_default` |
| `src/wimm/core/devdir_rules.py` | nuovo | L1 | nome + marker → tipo di cartella (puro) |
| `src/wimm/collectors/devdirs.py` | modifica | L1 | walker con regole e cartelle nascoste ammesse |
| `src/wimm/collectors/project_roots.py` | modifica | L1 | marker da costanti |
| `src/wimm/service/executor_disk_fs.py` | modifica | L1, L3, L6, L7 | rivalutazione marker, tabella cache, comandi, politica radici |
| `src/wimm/core/risk_table.py`, `core/risk.py` | modifica | L1, L3, L4, L6 | conseguenze per tipo, rischio cache per tipo, rischio per etichetta |
| `src/wimm/ui/disk_view.py`, `ui/disk_texts.py`, `ui/dialogs/preferences_*.py` | modifica | L1, L3, L7, L8 | avvisi radici, etichette cache, switch SSH |
| `Makefile`, `.github/workflows/ci.yml`, `pyproject.toml` | modifica | L2 | `audit`, bandit e pip-audit dev |
| `packaging/man/wimm.1`, `scripts/build_deb.sh` | nuovo, modifica | L2, L9 | man page |
| `data/metainfo/io.github.wimm.WhereIsMyMemory.metainfo.xml` | modifica | L2 | URL |
| `scripts/measure_open_time.py` | nuovo | L2 | RNF-04 |
| `src/wimm/core/cache_catalog.py` | nuovo | L3, L6 | catalogo cache, risoluzione percorsi (puro) |
| `src/wimm/model/disk.py`, `core/disk_wire.py` | modifica | L3, L6 | `CacheKind` esteso |
| `src/wimm/collectors/caches.py`, `service/fs_controls.py`, `service/sampler_environment.py` | modifica | L3 | tabella risolta passata a collector ed executor |
| `src/wimm/core/planning_disk_safe.py`, `core/disk_rules.py` | modifica | L3 | filtro SAFE |
| `src/wimm/core/docker_endpoint.py` | nuovo | L4 | endpoint da env e contesti (puro) |
| `src/wimm/collectors/docker_source.py`, `collectors/cgroups.py` | modifica | L4 | endpoint, scope libpod |
| `src/wimm/core/categorize.py`, `core/categorize_tools.py` | modifica, nuovo | L4, L8 | libpod, etichette strumenti, sessioni remote |
| `src/wimm/core/grouping_keys.py` | modifica | L4 | chiavi per daemon staccati |
| `src/wimm/collectors/meminfo.py`, `model/raw.py`, `model/memory.py` | modifica | L5 | campi nuovi |
| `src/wimm/collectors/kernel_memory.py`, `collectors/gpu.py`, `collectors/pressure.py` | nuovi | L5 | zram, tmpfs, VRAM, PSI, memory.events |
| `src/wimm/core/memory.py`, `core/notify_rules.py` | modifica | L5 | voci, PSI, OOM |
| `src/wimm/serialize.py`, `serialize_memory.py`, `model/enums.py` | modifica, nuovo | L5, L8 | forma nuova e `SCHEMA_VERSION` |
| `docs/adr/ADR-006-*.md`, `docs/adr/ADR-007-*.md` | nuovi | L7, L11 | Wayland, radici esterne |
| `src/wimm/core/root_policy.py` | nuovo | L7 | predicato radici (puro) |
| `src/wimm/core/growth.py`, `service/group_history.py` | nuovi | L8 | trend e storia ridotta |
| `src/wimm/cli_status.py`, `src/wimm/app.py` | nuovo, modifica | L9 | sottocomando |
| `src/wimm/service/restart_memory.py`, `ui/toasts.py` | modifica | L10 | processi fermati, copia comando |
| `packaging/arch/PKGBUILD`, `packaging/rpm/wimm.spec`, `scripts/test_<formato>.sh` | nuovi | L12 | secondo Q5 |
| `po/en.po` | modifica | tutti | traduzioni |
| `docs/DEVIATIONS.md`, `docs/PERF.md`, `docs/DELIVERY_REPORT.md` | modifica | tutti | scostamenti, misure, verifiche manuali |

`README.md` si aggiorna solo con l'ok dell'utente (`code-standards.md` § Documentazione): i task
che lo toccano sono marcati e la modifica si propone nel report di chiusura del lotto.

## Rischi

- Poiché "Libera spazio" oggi prende ogni cache tranne il cestino (`core/planning_disk_safe.py:25`),
  aggiungere modelli ML o maven al catalogo li manderebbe in un'azione SAFE di massa; un errore
  qui cancella decine di GB non ricostruibili. Mitigazione: il filtro passa al rischio calcolato
  in L3 (T035) prima che entri una voce CAUTION, con test appaiato; L6 dipende da quel task.
- Poiché la module cache di Go è in sola lettura, `safe_tree` fallirebbe a metà lasciando una
  cache rotta. Mitigazione: per Go solo `go clean`, senza `go` l'azione non si offre (T036).
- Poiché il `vendor` di Go è spesso versionato in git, trattarlo come cartella di dipendenze
  cancellerebbe sorgenti tracciati. Mitigazione: `vendor` solo con `composer.json`; `dist`
  escluso (spesso contiene artefatti da pubblicare). Scostamento da F7 dichiarato in DEVIATIONS.
- Poiché la prima scansione disco costa già il 14% di un core per un minuto ogni 6 ore
  (`docs/DELIVERY_REPORT.md:12`), ammettere cartelle nascoste e 12 cache in più può allungarla.
  Mitigazione: misura prima e dopo in L1 (T016-T017) e L3 (T042) con soglia +30%; oltre, si limita
  la profondità per le cartelle nascoste.
- Poiché le radici fuori dalla home sono un allargamento del perimetro di cancellazione, un
  predicato diverso fra config ed executor aprirebbe una via a percorsi di sistema. Mitigazione:
  un solo predicato puro (T075), usato da entrambi, ADR-007 e `security-reviewer` obbligatorio.
- Poiché il parser dello snapshot è stretto, ogni campo nuovo rompe i lettori esterni di
  `GetSnapshot`. Mitigazione: Q4 decide la politica; i lotti che cambiano forma (L3, L5, L8) la
  dichiarano in DEVIATIONS e nell'XML dell'Inspector.
- Poiché `nvidia-smi` avvia un processo, chiamarlo a ogni ciclo pesa su RNF-01. Mitigazione: un
  campione ogni 5 cicli, timeout 2 s, rimisura `pidstat` (T061).
- Poiché la cmdline può contenere token, la memoria dei processi fermati (F14) è una superficie
  di segreti. Mitigazione: solo RAM, mai log a INFO, avviso nel toast, nessun salvataggio.
- Poiché podman non è installato su questa macchina (misurato), il supporto podman si prova solo
  con fake e fixture cgroup; resta una verifica manuale M-* fino a un container di prova.
- Poiché F3 rovescia la decisione A1 del 2026-10-17 (`specs/i18n/plan.md:15`: `C` e `de` davano
  italiano), il cambio va registrato come nuova decisione in DEVIATIONS, non come correzione.

## Fuori scope

- Revisioni snap e runtime flatpak di sistema: richiedono root (N2).
- Runtime flatpak `--user` inutilizzati (era R25): `flatpak 1.14.6` non ha un modo di elencarli
  senza disinstallarli (`flatpak list` non ha `--unused`, misurato), quindi il piano non può
  mostrare cosa toccherebbe.
- Pacchetto Flatpak dell'app: il sandbox isola lo spazio dei pid, l'app non vedrebbe i processi
  dell'host (inferred, da confermare se Q5 lo riapre).
- Grafici storici e persistenza della storia (N3): F13 è un indicatore su 3 ore in RAM.
- Pulizia per singolo modello di HF o ollama: L6 tratta la cartella intera.
- Endpoint container remoti (`tcp://`, `ssh://`): l'app guarda solo la macchina locale (S8).
- Esecuzione della CI remota e verifiche M-*: le fa l'utente (push e installazione con sudo).
- Compositor Wayland diversi da GNOME, salvo diversa scelta in ADR-006.

## Domande aperte

Default raccomandato in testa; senza risposta il piano procede col default e lo registra.

- **Q1 (F5, sessioni SSH)**: A) opzione `remote_sessions_actionable`, spenta di default: Q-12 resta
  com'è per chi non la accende; B) cambiare il default: i processi dell'utente nelle
  `session-*.scope` seguono le regole normali, `sshd`, shell di login e server tmux protetti;
  C) nessun cambio, solo FAQ. A rispetta la decisione Q-12 e costa uno switch; B è più utile ma
  rende terminabili processi da cui dipende la propria connessione remota.
- **Q2 (F6, modelli ML e Android)**: A) HF hub e Android SDK CAUTION, modelli ollama e AVD DANGER
  (un modello creato con `ollama create` o un AVD con dati non si riscaricano), mai in "Libera
  spazio"; B) tutte DANGER; C) solo misura, nessuna azione.
- **Q3 (F10, strumenti)**: A) etichetta e motivo dentro le categorie esistenti, nessun valore nuovo
  in `Category` (niente cambio di enum né di `notify_categories`); B) nuove categorie (VM,
  BUILD_DAEMON, LANGUAGE_SERVER, LOCAL_CLUSTER) con bump di schema, filtri e notifiche dedicate.
- **Q4 (schema)**: A) bump di `SCHEMA_VERSION` a ogni lotto che cambia la forma (L3, L5, L8),
  parser stretto invariato; B) campi additivi senza bump e lettore tollerante ai campi
  sconosciuti (ADR nuovo); C) raccogliere tutti i cambi di forma in un solo lotto (L5 assorbe la
  parte wire di L3 e L8, che smettono di essere indipendenti).
- **Q5 (F16, formati)**: A) PKGBUILD per AUR e spec RPM per Fedora, ciascuno provato in container;
  Flatpak escluso; B) solo AUR; C) nessun formato nuovo, istruzioni di installazione manuale.
- **Q6 (F15, sorgente dei dati)**: A) `GetSnapshot` dell'istanza attiva, campionamento singolo se
  non c'è; B) sempre campionamento singolo (attività sempre `unknown`); C) solo istanza attiva,
  errore se manca.
- **Q7 (F14, riavvio)**: A) solo "Copia comando di riavvio"; B) anche "Riavvia" eseguito dall'app
  (azione CAUTION, ambiente di wimm e non quello del terminale originale: un venv attivato o
  variabili esportate a mano si perdono).
- **Q8 (F17, fatto da fornire)**: URL della homepage e del bug tracker per la metainfo: il repo
  non ha un remote configurato (`git remote -v` vuoto), quindi non è ricavabile.
- **F4**: decisione proposta in ADR-006 (sezione Decisioni architetturali), da accettare.

## Assunzioni

- Ubuntu 24.04, GNOME 46, Python 3.12 di sistema; psutil, docker, gi da apt (ADR-002).
- `C`/`POSIX` → inglese (R3): è il caso dei container e delle sessioni SSH senza locale.
- Le cache indicate da una variabile d'ambiente fuori dalla home reale si ignorano (invariante
  attuale dell'executor, `executor_disk_fs.py:89`); con F2 non si estende alle cache.
- Le radici rilevate in automatico non si salvano finché l'utente non tocca le Preferenze: a ogni
  avvio la rilevazione si ripete (costo limitato a 2 livelli per 8 candidate).
- Le soglie PSI (10 e 5 su `avg60`) e di crescita (256 MiB, 20%, 3 h) sono valori iniziali in
  costanti nominate, non tarati: si rivedono con la misura sul sistema reale.
- Ollama installato come servizio di sistema tiene i modelli in `/usr/share/ollama` (non
  dell'utente): lì solo misura se leggibile, nessuna azione (N2).
- Gli argv dei comandi nativi delle cache (pnpm, yarn, conda) sono UNVERIFIED finché il task
  non li controlla sulla documentazione corrente.

## Decisioni architetturali (proposta dell'architect, da accettare)

- **ADR-006, Wayland (F4, L11).** Porta `ForegroundSource` con un adapter per compositor:
  X11 (xprop, quello di oggi), estensione GNOME Shell opzionale installata dal .deb in
  `/usr/share/gnome-shell/extensions`, KWin e wlroots solo su richiesta. In ogni sessione
  Wayland girano euristiche che possono solo alzare a "attivo", mai portare a inattivo: stream
  PipeWire attivi per pid (media in sottofondo) e delta CPU. Senza adapter lo stato resta
  `unknown` come oggi. Scartati: `org.gnome.Shell.Introspect` (risponde AccessDenied su GNOME 46,
  misurato), `IdleMonitor` (solo inattività di sessione), AT-SPI (accende l'albero di
  accessibilità nei browser, più RAM). Costo fisso: aggiornare `shell-version` a ogni release di
  GNOME.
- **F9, motori container (L4).** Lista di endpoint risolta in un modulo puro: `DOCKER_HOST`,
  poi `DOCKER_CONTEXT`, poi `currentContext` di `~/.docker/config.json` con
  `contexts/meta/<sha256(nome)>/meta.json`, poi il socket di default; in più
  `$XDG_RUNTIME_DIR/podman/podman.sock` se esiste. Docker e Podman rootless si leggono insieme,
  con deduplica per realpath del socket e per `ID` di `/info` (il pacchetto `podman-docker` fa di
  `/var/run/docker.sock` Podman stesso). Chiave del container `(engine_id, container_id)`;
  `libpod-*.scope` si aggiunge ai pattern di esclusione. Con Docker Desktop i container stanno
  nella VM: compaiono come membri del gruppo della VM e non si sommano al totale. Sostituisce
  l'esclusione "un solo endpoint" del piano originale e aggiunge circa 1 g a L4.
- **F16, distribuzione (L12).** Il .deb resta primario. RPM via COPR e PKGBUILD AUR dopo uno
  shim di compatibilità (versioni delle librerie, nomi degli scope systemd `app[-launcher]-<id>`
  oltre a `app-gnome-*`, fisso in `src/wimm/core/cgroup_paths.py:54`). Flatpak, PyPI e Snap
  esclusi dalla 1.x (sandbox dei pid; dipendenze `[]` per ADR-002). Matrice CI Ubuntu più
  Fedora; ADR-002 va emendato da "versioni apt pinnate" a "API minima garantita". Coincide con
  Q5=A. GNOME senza AppIndicator: resta il banner, con le notifiche come canale indipendente.

## Rilievi di sicurezza (security-reviewer sul piano)

Severità P0 bloccante: il task citato non si chiude senza la mitigazione e il suo test.

| ID | Superficie | Mitigazione da aggiungere | Task | Sev |
|---|---|---|---|---|
| S1 | `target/`, `vendor`, `.next` ecc. | secondo segnale oltre al marker: `CACHEDIR.TAG` di cargo o il nome nel `.gitignore` del padre (parsing testuale, mai `git`: `core.fsmonitor` eseguirebbe codice); senza segnale non offerta | T010 T013 T018 | P1 |
| S2 | `.gradle` con radice = home | rifiutare devdir con padre = home: `~/.gradle` contiene credenziali di firma | T010 T013 | P1 |
| S3 | radici fuori home | `root_refusal` rifiuta path con 2 componenti o meno, antenati della home, la home, fstype di rete/FUSE/autofs (da mountinfo), mount `ro`, cartelle di sistema; l'executor ripete la stessa funzione | T075 T077 | P0 |
| S4 | executor su radici esterne | `st_uid` proprio su devdir e progetto; `st_dev` della radice uguale a quello del piano | T077 T078 | P1 |
| S5 | cache ridirette da env | scartare path uguali o antenati di home e di ogni radice, o dentro una radice; un path rediretto vuole un sentinel (`CACHEDIR.TAG` o sottocartelle note), altrimenti solo misura | T031 T033 | P0 |
| S6 | comandi nativi | ambiente minimo in allowlist (`PATH`, `HOME`, `LANG` più la variabile del piano), `argv[0]` assoluto; yarn e conda con svuotamento diretto se la config non è nota | T037 T039 | P2 |
| S7 | modelli ML, Android | test che fallisce se un tipo L6 diventa SAFE; T034 mergiato prima di T069 | T034 T035 T070 T072 | P1 |
| S8 | docker context | solo `unix://` assoluto verso un socket (`S_ISSOCK`) in `$XDG_RUNTIME_DIR` (uid proprio, 0700) o `/var/run/docker.sock`, `/run/docker.sock`; `tcp://` e `ssh://` rifiutati con messaggio, `DOCKER_HOST` compreso; meta letti con limite di dimensione e senza seguire symlink | T044 T045 | P0 |
| S9 | endpoint cambiato fra piano ed esecuzione | il piano registra l'identità dell'endpoint (socket, ino/dev); l'executor la ricontrolla, altrimenti `TargetChanged` | T045 T050 | P1 |
| S10 | cmdline dei processi fermati | solo in RAM, mai in snapshot, D-Bus o log, durata pari al toast; `CREDENTIAL_PATTERN` esteso a `pass`, `passwd`, `pwd`, `credential`, `auth`, `-p<valore>`, con test di falsi positivi | T094 T096 T098 | P1 |
| S11 | comando di riavvio copiato | nessun pulsante se argv o cwd contengono caratteri di controllo; con Q7=B esecuzione da `/proc/pid/exe`, mai da PATH | T095 T096 T097 | P1 |
| S12 | `wimm status --json` | redazione spostata in un modulo senza `gi` e usata da JSON e testo; caratteri di controllo tolti dal testo; test con `--token abc` assente dall'output | T090 T091 T092 | P0 |
| S13 | estensione GNOME | wimm verifica che il proprietario del nome D-Bus sia gnome-shell dello stesso uid; l'estensione rifiuta i peer sandbox | T100 T101 | P1 |
| S14 | estensione GNOME, supply chain | sola lettura, niente `eval`, spawn o scritture; test grep sul sorgente | T100 T102 | P2 |
| S15 | rilevazione radici da `user-dirs.dirs` | assoluto, dentro home, mai la home, niente `..`, non symlink; scansione fuori dal main thread, skip dei fstype di rete | T003 T004 | P1 |
| S16 | radici rilevate = autorità di cancellazione | la rilevazione alimenta solo la scansione; l'executor accetta solo radici salvate o confermate nelle Preferenze | T004 T077 | P2 |
| S17 | cache su symlink | messaggio dedicato invece di un errore generico, nessun follow | T033 T040 | P2 |
| S18 | ordine di merge | T034 (rischio per tipo di cache) prima di T030 | T034 T035 | P2 |

## Decisioni registrate (2026-10-18)

L'utente ha detto "procedi all'implementazione" senza scegliere fra le opzioni: valgono i
default. D1, D2 e D3 accettate; Q1-Q7 = A. Q8 aperta: T025 sospeso finché manca l'URL.
