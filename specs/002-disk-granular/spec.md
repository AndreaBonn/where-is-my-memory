# 002 disco granulare: requisiti

Richiesta dell'utente (2026-10-19, verbatim): "Vorrei che tutto fosse ben spiegato, facilmente
comprensibile e tutto sia possibile sia fare eliminazioni sicure massive, sia eliminazioni
atomiche del singolo modello, o della singola cache etc".

`assets/SPECIFICHE.md` resta la fonte di verità: il primo task (T-6.1) vi aggiunge RF-29,
RF-51, RF-52, RF-53, l'estensione di RF-22 e la Fase 6 (T-6.x) del §16. Gli id `S<n>` valgono
solo dentro questa cartella (le `R<n>` di `specs/001-product-gaps/` sono un altro spazio di
nomi; qui si citano come `001/R14`).

Formato: `S<n> | RF | requisito | Definition of Done (verificabile) | esempio`.
I nomi dei test sono quelli da creare; il test si vede rosso prima del verde.

## Decisioni già prese dall'utente (riportate dall'orchestratore il 2026-10-19)

- **O1**: in ogni riga della vista Disco la conseguenza è il sottotitolo, sotto il percorso;
  il badge si accorcia alla sola classe ("Sicuro", "Attenzione", "Pericolo").
- **O3**: le righe delle cache si espandono e mostrano un sotto-elemento per elemento
  (`models--*` di HuggingFace e gli equivalenti delle altre cache), più una voce
  "non attribuito" per i byte fuori dagli elementi. La rimozione del singolo elemento passa dal
  comando o dall'API del tool quando esistono (001/R14).

## Fatti misurati sulla macchina dell'utente (2026-10-19)

- `~/.cache/huggingface/hub` contiene 5 cartelle `models--*`, `.locks`, `CACHEDIR.TAG`,
  `version_diffusers_cache.txt` e una cartella `blobs/` alla radice da 15 GB con sottocartelle
  esadecimali a 2 caratteri, ciascuna con `<sha256>`, `<sha256>.lock`, `<sha256>.refs`.
- **Il magazzino alla radice è referenziato dai modelli**, contrariamente a quanto si supponeva:
  `models--coqui--XTTS-v2/blobs/1f69...` è un symlink a `../../blobs/3b/3b89...`; i `.refs`
  elencano 17 riferimenti (HTDemucs 1, XTTS-v2 4, chatterbox 12) su 18 blob. Due modelli
  (faster-whisper-large-v3 2,9 GB, speechbrain 86 MB) hanno blob come file regolari, layout
  standard. Lo strumento che ha creato il magazzino resta ignoto.
- Conseguenza: cancellare solo `models--coqui--XTTS-v2` libera 3,2 MB (symlink e snapshot) e
  lascia i suoi GB nel magazzino. La dimensione per elemento deve seguire i symlink dentro la
  cache.
- Né `hf` né `huggingface-cli` né il modulo `huggingface_hub` sono installati.
- ollama gira come servizio di sistema (`systemctl is-active ollama` = active): i modelli sono
  in `/usr/share/ollama/.ollama/models` (proprietario `ollama`), `~/.ollama/models` non esiste,
  quindi oggi wimm non li vede. `ollama list` elenca 4 modelli (4,7 + 3,3 + 6,6 + 6,0 GB).
  `ollama rm MODEL [MODEL...]` esiste (`ollama rm --help`).
- `~/Android/Sdk` ha `cmdline-tools/latest/bin/{sdkmanager,avdmanager}`, `platforms/android-35`,
  `build-tools`, `platform-tools`; `sdkmanager --uninstall [<packages>...]` e
  `sdkmanager --list_installed` esistono (`--help`); `avdmanager delete avd [action options]`
  esiste. `~/.android/avd`, `~/.cache/JetBrains` assenti; `~/.cache/ms-playwright` vuota.

## Requisiti

### Spiegazione in riga (RF-29, O1)

- S1 | RF-29 | Ogni riga con un'azione mostra la sua conseguenza | il sottotitolo è
  `<percorso o descrizione>` seguito, su una riga nuova, dal testo di conseguenza; il testo è
  **lo stesso** che il dialogo di conferma mette in "Cosa succede" per quella riga (una sola
  funzione pura lo produce per entrambi). Test
  `tests/ui/test_disk_view.py::test_cache_row_subtitle_carries_the_dialog_consequence` (caso
  appaiato: una riga senza azione non ha seconda riga) | Given la cache HuggingFace da 19,2 GB,
  When si apre Disco, Then la riga dice "~/.cache/huggingface/hub" e sotto "Modelli di
  HuggingFace: si riscaricano quando servono, anche diversi GB."
- S2 | RF-29 | Badge corto | il badge di ogni riga Disco è `RISK_TEXT` ("Sicuro", "Attenzione",
  "Pericolo"); `DISK_RISK_CONSEQUENCE` non è più usato dalle righe e, se resta orfano, si
  rimuove con le sue traduzioni. Test `tests/ui/test_disk_model.py::test_make_row_badge_is_the_short_risk_text` | badge "Attenzione" invece di "Attenzione: leggi prima cosa si perde"
- S3 | RF-29 | Vale per ogni tipo di riga | cache, cestino, immagini, container fermi, volumi,
  build cache, cartelle di dipendenze (con il comando di ricostruzione di `devdir_consequence`) e
  i sotto-elementi di S5. Test parametrico su un report di fixture con una riga per tipo | la
  riga `whitebox · node_modules` dice "Per usare di nuovo il progetto serve ricostruire la
  cartella con npm install."
- S4 | RF-29 | Leggibile a 360 px | sottotitolo senza limite di righe (`subtitle_lines=0`, mai troncato), nessuna
  sovrapposizione fra titolo, sottotitolo, dimensione, badge e bottone. Verifica: render
  osservato a 360 e 1280 px, nome accessibile della riga che include la conseguenza |
  screenshot allegati al task

### Elementi delle cache (RF-51, RF-52, O3)

- S5 | RF-51 | Una riga di cache con elementi si espande | la riga diventa espandibile e
  mostra un sotto-elemento per elemento, ordinati per dimensione decrescente, con titolo,
  dimensione, conseguenza, badge e azione "Rimuovi"; al massimo `CACHE_ITEMS_CAP` sotto-righe
  più "e altre N". Le cache senza elementi (tabella in `plan.md`) restano righe semplici | la
  riga HuggingFace si apre su 5 modelli e "Non attribuito"
- S6 | RF-51 | Elementi per tipo di cache (tabella di `plan.md` § Granularità) | una funzione
  pura per tipo trasforma le voci lette in elementi; nessun elemento per uv, npm, pip, pnpm,
  yarn, bun, conda, cargo, go, miniature, cestino, maven, gradle in questa specifica. Test
  `tests/core/test_cache_items.py` con una fixture di albero per tipo | -
- S7 | RF-51 | Dimensione vera dell'elemento HuggingFace | la dimensione di un repo
  (`models--*`, `datasets--*`, `spaces--*`) è la somma dei suoi file regolari più i blob del
  magazzino condiviso raggiunti **solo** dai suoi symlink; un blob raggiunto da symlink di due
  repo va in "Condiviso fra più modelli" e non nella dimensione di nessuno. Il percorso
  risolto di un symlink deve stare dentro la cache, altrimenti il link non conta. Test
  `tests/core/test_cache_items_hf.py::test_repo_size_counts_exclusive_store_blobs` (casi
  appaiati: blob condiviso, symlink fuori dalla cache) | XTTS-v2 vale 3,2 MB + i suoi 4 blob
  del magazzino
- S8 | RF-52 | Voce "Non attribuito" | i byte della cache fuori da ogni elemento (blob del
  magazzino non raggiunti da nessun symlink, `.locks`, file alla radice) compaiono come
  sotto-riga "Non attribuito" con una frase che dice cosa contiene e che si libera solo con
  "Pulisci tutta la cache"; nessuna azione propria. La somma degli elementi, del condiviso e
  del non attribuito è uguale alla dimensione della cache. Test
  `tests/core/test_cache_items.py::test_items_and_rest_sum_to_cache_size` | 1 blob su 18
  senza riferimenti finisce lì
- S9 | RF-22 | La pulizia della cache intera resta | il bottone della riga di cache (ora
  "Pulisci tutta la cache") resta com'è, con la conseguenza in riga | nessuna regressione
  dei test di `CACHE_CLEAN`

### Rimozione del singolo elemento (RF-22 esteso, O3)

- S10 | RF-22 | Azione `cache_item_remove` | target = id dell'elemento (`<kind>:<nome>`), piano
  con un passo, impronta della cartella (`realpath`, `st_ino`, `st_dev`) e, per HuggingFace,
  l'elenco dei blob esclusivi con la loro impronta. Rischio per tipo di cache e per elemento
  (tabella in `plan.md`); DANGER chiede la frase digitata = nome dell'elemento. Test
  `tests/core/test_planning_cache_item.py` | -
- S11 | RF-22 | Comando del tool quando esiste | Android SDK: `sdkmanager --uninstall <id>`
  con `--sdk_root=<cache>`; AVD: `avdmanager delete avd -n <nome>`; ollama: `ollama rm <nome>`
  (vedi Q2). Senza il tool: SDK e AVD non offrono l'azione per elemento (come `COMMAND_ONLY_KINDS`),
  HuggingFace, Playwright e JetBrains cancellano la cartella con `safe_tree`. argv in lista,
  timeout, ambiente in allowlist (`command_env`). Test
  `tests/service/test_executor_cache_item.py::test_item_argv_*` con runner finto | nessun
  `shell=True`
- S12 | RF-22 | L'executor ricontrolla tutto al momento | la cartella è un figlio diretto (o il
  percorso della regola del tipo) di una cache `CLEANABLE` della tabella risolta all'avvio, la
  regola pura di S6 la riconosce ancora come elemento, nessun symlink sul percorso, proprietario
  = utente, impronta uguale; per HuggingFace l'esclusività di ogni blob si **ricalcola** sui
  symlink presenti adesso e un blob diventato condiviso resta. Test
  `tests/service/test_executor_cache_item.py::test_*_is_refused` con un caso per controllo,
  ognuno appaiato al caso che passa | un piano con `../` o con un percorso fuori tabella dà
  `ProtectedTarget` e il bersaglio resta intatto
- S13 | RF-22 | Rifiuti specifici | AVD in uso da un emulatore in esecuzione (argv
  `-avd <nome>`) → rifiuto con messaggio; elemento HuggingFace con un `.lock` aperto
  di recente (vedi rischi) → rifiuto; ollama → vedi Q2 | -
- S14 | RF-26 | Esito misurato | dopo la rimozione l'esito mostra il liberato misurato e la
  cache si rimisura subito (non alla prossima scansione) | click-through

### Eliminazione massiva sicura (RF-53)

- S15 | RF-53 | "Libera spazio" resta il massivo senza perdite | prende solo le voci SAFE
  (comportamento attuale di `planning_disk_safe.py`), sotto-elementi SAFE compresi solo se la
  loro cache intera non è già nel piano; dialogo unico con voci rimovibili (§8.3 riga 542, già
  in `ConfirmSession`). Test `tests/core/test_planning_disk_safe.py::test_disk_free_safe_never_includes_caution_items` (caso appaiato: un elemento SAFE entra) | -
- S16 | RF-53 | Selezione multipla | una modalità "Seleziona" mette una casella su ogni riga e
  sotto-riga con azione; il bottone "Libera i selezionati (N, X GB)" apre **un** dialogo con le
  voci raggruppate per classe di rischio, il totale stimato, le conseguenze di ciascuna e la
  possibilità di togliere singole voci. Il livello di conferma è quello della voce più rischiosa
  fra le CAUTION; le DANGER non sono selezionabili (vedi Q3). Selezionare una cache intera
  toglie la selezione dei suoi elementi (e viceversa). Test
  `tests/core/test_planning_disk_selected.py` e `tests/ui/test_disk_selection.py` | selezionati
  XTTS-v2 e il build cache → un dialogo, 2 voci, "Attenzione"
- S17 | RF-53 | Nessuna azione automatica | la selezione non sopravvive a un nuovo report: se
  un elemento selezionato è sparito o cambiato, il dialogo lo dice (`CHANGED_NOTICE`) invece di
  confermarlo | test con report sostituito fra selezione e conferma

### Trasversali

- S18 | - | Schema | `CacheEntry` acquista `items` e `rest`; `SCHEMA_VERSION` passa da 4 a 5
  (politica Q4=A di `docs/DEVIATIONS.md`), `data/dbus/io.github.wimm.Inspector1.xml` e
  DEVIATIONS aggiornati; un report con schema 4 è rifiutato. Test
  `tests/core/test_disk_wire.py` round-trip della forma nuova | -
- S19 | - | Traduzioni | ogni stringa nuova in `_()`/`N_()` con msgid italiano e traduzione in
  `po/en.po`; `make lint` passa | -
- S20 | - | Floor | `make lint` e `make test` verdi a ogni task, numero di test maggiore
  della baseline misurata in T-6.1, copertura `src/wimm/core` >= 90%, `tests/test_source_limits.py`
  verde (300/30/4); nessuna cancellazione reale nei test (§0.5): bersagli in `tmp_path`, runner
  finto | -
