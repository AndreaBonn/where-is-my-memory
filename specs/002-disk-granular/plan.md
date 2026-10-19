# 002 disco granulare: piano

Riferimenti: `spec.md` (S1-S20, decisioni O1 e O3), `tasks.md` (T-6.1-T-6.40),
`assets/SPECIFICHE.md` (prevale), ADR-003 (rischio per coppia entità/azione), 001/R13-R15 e
R24. Stato di partenza: `main` pulito a `7c3f960` (v1.0.0 + footer).

## Obiettivo

Nella vista Disco ogni riga dice da sola cosa si perde, ogni cache con contenuti distinguibili
(modelli, browser, emulatori, pacchetti SDK) si apre e permette di togliere un elemento alla
volta, e si possono liberare più voci con un solo dialogo, senza mai includere in silenzio
qualcosa che non si riscarica.

## Definition of Done

- [ ] Ogni riga Disco con azione ha come sottotitolo il percorso e sotto la conseguenza, identica
  al "Cosa succede" del suo dialogo; badge "Sicuro" / "Attenzione" / "Pericolo" (S1-S4).
- [ ] La riga HuggingFace si espande in 5 modelli, "Condiviso fra più modelli" (se c'è) e
  "Non attribuito"; la somma è la dimensione della cache; XTTS-v2 mostra i GB dei suoi blob nel
  magazzino, non 3,2 MB (S5-S8).
- [ ] "Rimuovi" su un modello HuggingFace di test in `tmp_path` cancella la sua cartella e i soli
  blob esclusivi; un blob diventato condiviso dopo il piano resta (S10-S12).
- [ ] Su un SDK di test, "Rimuovi" su `platforms;android-35` lancia (runner finto)
  `sdkmanager --sdk_root=<cache> --uninstall platforms;android-35`; senza `sdkmanager` l'azione
  per elemento non c'è (S11).
- [ ] "Libera i selezionati" con un elemento CAUTION e il build cache apre un dialogo con 2 voci
  raggruppate per rischio, livello "Attenzione"; una voce DANGER non ha casella (S16).
- [ ] `make lint`, `make test` verdi, test > baseline, copertura core >= 90%, nessun file oltre
  300 righe, `SCHEMA_VERSION` = 5 documentata (S18-S20).

## Assunzioni

- Il magazzino `blobs/` alla radice di `hub` è raggiunto dai modelli via symlink relativi
  (misurato su XTTS-v2, chatterbox, HTDemucs). La regola di attribuzione usa **solo** la
  risoluzione dei symlink dentro la cache, non i `.refs` dello strumento ignoto: funziona anche
  sul layout standard (blob come file regolari) e non dipende da un formato non documentato.
- HuggingFace senza `huggingface_hub` installato: la cancellazione la fa wimm con `safe_tree`.
  L'API ufficiale (`scan_cache_dir().delete_revisions(...)`, `hf cache rm`, UNVERIFIED: da
  training data, verificare con context7 nel task T-6.20) non conosce il magazzino alla
  radice: cancellerebbe i symlink e lascerebbe i GB. Per questo layout il comando del tool non
  sarebbe corretto anche se installato; R14 si applica dove il tool ha un comando che fa la cosa
  giusta. Da registrare in DEVIATIONS.
- Il rischio per elemento è quello della cache intera, salvo dove la tabella sotto dice altro.
- `Adw.ExpanderRow` è il widget delle righe espandibili (già usato in `group_row.py`,
  `system_section.py`): nessun widget nuovo.
- La vista per elemento si ricava dalla stessa scansione disco: niente scansione separata;
  il costo in più si misura (T-6.12) e deve restare <= 15% sulla scansione attuale.
- Gli id nuovi della specifica: RF-29 (spiegazione in
  riga), RF-51, RF-52, RF-53, Fase 6 con T-6.x. RF-29 è l'unico id libero nella sezione Azioni;
  RF-51..53 seguono RF-50.

## Disambiguazione di scope: granularità per cache

| Cache | Elemento | Rimozione | Rischio elemento | Fase | BASIS |
|---|---|---|---|---|---|
| huggingface | repo `models--*`, `datasets--*`, `spaces--*` + blob esclusivi del magazzino | wimm: `safe_tree` sulla cartella e sui blob esclusivi (comando HF non adatto al layout, vedi assunzioni) | CAUTION | L3 | measured (layout); unknown (provenienza magazzino) |
| ollama (home) | modello (manifest `manifests/<host>/<ns>/<nome>/<tag>`) | `ollama rm <nome>:<tag>` | DANGER (create in locale non si riscarica) | L5, Q2 | measured (`ollama rm --help`); inferred (serve il server attivo) |
| ollama (servizio di sistema) | modello da `ollama list` | `ollama rm`, nessun accesso ai file | DANGER | L5 se Q2=A | measured (modelli in `/usr/share/ollama`, owner `ollama`) |
| android_sdk | pacchetto (`platforms;android-35`, `build-tools;35.0.0`, `system-images;...`, `ndk;...`) da `package.xml` | `sdkmanager --sdk_root=<cache> --uninstall <id>` | CAUTION; `cmdline-tools` e `licenses` mai elementi | L4 | measured (`--uninstall`, `--list_installed`); inferred (`--sdk_root` come opzione comune) |
| android_avd | dispositivo (`<nome>.avd` + `<nome>.ini`) | `avdmanager delete avd -n <nome>` | DANGER | L4 | measured (`delete avd [action options]`); inferred (`-n`) |
| playwright | browser (`chromium-<rev>`, `firefox-<rev>`, `webkit-<rev>`, `ffmpeg-<rev>`) | wimm: `safe_tree` (`playwright uninstall` toglie tutto, non un browser: UNVERIFIED) | SAFE | L4 | inferred (layout da doc); unknown (cartella vuota qui) |
| jetbrains | cartella prodotto-versione (`PyCharm2025.1`) | wimm: `safe_tree` (nessun comando) | CAUTION | L4 | inferred (non presente qui) |
| maven | artefatto `groupId:artifactId` | nessun comando per artefatto senza progetto (`dependency:purge-local-repository`, UNVERIFIED) | - | fuori scope | inferred |
| gradle | versione in `caches/<ver>` | nessun comando | - | fuori scope | inferred |
| uv, pip | pacchetto (`uv cache clean <pkg>`, `pip cache remove <pattern>`: UNVERIFIED) | - | - | fuori scope (contenuto indirizzato per hash, valore basso) | inferred |
| npm, pnpm, yarn, bun, conda, cargo, go_mod, go_build, thumbnails | nessuno: contenuto indirizzato per hash o opaco | solo cache intera | - | - | inferred |
| trash | file nel cestino | - | - | fuori scope (dati utente, merita un suo design) | - |

Docker e cartelle di dipendenze sono già atomici (una riga per immagine, volume, container,
cartella): ricevono solo S1-S3 e la casella di S16.

## Disambiguazione: cosa vuol dire "eliminazione massiva sicura"

Approcci plausibili (elencati prima di valutarli):

- A. "Libera spazio" com'è (solo SAFE) + modalità "Seleziona" trasversale con un dialogo unico.
- B. Un bottone "Libera tutto il sicuro di questa sezione" per ogni sezione.
- C. "Libera spazio" esteso a CAUTION con deselezione.

Valutazione: B moltiplica i bottoni e non copre la scelta mista (un modello + il build cache).
C rompe la promessa di D1 ("senza perdere niente") e 001/R13. **Raccomandata A**: il massivo
senza perdite resta un clic, il massivo con scelta passa da caselle e da un dialogo che mostra
ogni conseguenza; riusa `ConfirmSession` (esclusione già implementata) con una richiesta che
porta l'insieme selezionato.

## Fasi (indipendentemente mergiabili)

| Fase | Contenuto | Stima (buffer 20% incluso) | Rilasciabile perché |
|---|---|---|---|
| L0 | SPECIFICHE: RF-29, RF-51..53, RF-22 esteso, Fase 6; DEVIATIONS; baseline test e scansione | 0,5 g | solo documenti |
| L1 | Spiegazione in riga (O1): conseguenza nel sottotitolo per ogni tipo di riga, badge corto | 1-1,5 g | nessun cambio di schema né di azioni |
| L2 | Modello elementi + HuggingFace in sola lettura: righe espandibili, condiviso, non attribuito | 2,5-3,5 g | mostra il dettaglio senza nuove azioni; schema 5 |
| L3 | Rimozione del singolo modello HuggingFace | 2-2,5 g | prima azione per elemento, completa per la cache più grande dell'utente |
| L4 | Elementi e rimozione per Android SDK, AVD, Playwright, JetBrains | 2,5-3,5 g | ogni tipo è un task chiuso: un tipo in meno non rompe gli altri |
| L5 | ollama per modello (home e, se Q2=A, servizio di sistema) | 1,5-2 g | indipendente dalle altre cache |
| L6 | Selezione multipla e "Libera i selezionati" | 2-3 g | usa le azioni già esistenti; senza L3-L5 vale per righe intere |

Totale 12-16,5 g. Ordine consigliato L0, L1, L2, L3, L6, L4, L5: L6 porta il massivo con scelta
appena c'è almeno un'azione per elemento; L4 e L5 si aggiungono senza toccare L6. Quadrante:
obiettivo chiaro, soluzione chiara salvo HuggingFace (layout ignoto) e ollama di sistema:
buffer nella fascia alta per L3 e L5.

## Architettura

- **Core puro**: `core/cache_items.py` (dispatch per tipo, `CACHE_ITEMS_CAP`, somma e resto),
  `core/cache_items_hf.py` (attribuzione per symlink), `core/cache_items_android.py`,
  `core/cache_items_misc.py` (Playwright, JetBrains), `core/planning_cache_item.py`,
  `core/planning_disk_selected.py`. Input = un albero osservato (`TreeListing`: nomi, tipi,
  dimensioni, target dei symlink) prodotto dal collector; nessun `os` nel core.
- **Collector**: `collectors/cache_items.py` legge l'albero con `os.scandir` senza seguire
  symlink (solo `readlink`), riusa `measure_dir_size` e la sua cache per le cartelle intere.
- **Model**: `CacheItem` (id, titolo, path, size, st_ino, st_dev, kind di elemento) e
  `CacheRest` (shared, unattributed) in un modulo nuovo `model/cache_items.py`; `CacheEntry`
  acquista `items: tuple[CacheItem, ...] = ()` e `rest` (default zero) via `OPTIONAL_FIELDS`.
- **Executor**: `service/executor_cache_item.py` con la stessa regola pura (S12), dentro
  `DiskFsControl`; nessuna estensione di `executor_disk_fs.py` (266 righe).
- **UI**: `ui/disk_items.py` (view model puro delle sotto-righe), `ui/pages/disk_item_rows.py`
  (ExpanderRow), `ui/disk_selection.py` (stato della selezione, puro), un controllo nel
  `DiskHeader`. `window.py` (300) e `planning_disk.py` (283) non si toccano.
- **Conseguenza unica**: `core/row_consequence.py` dà il testo per (azione, bersaglio) usando
  `assess_risk` e `devdir_consequence`, chiamata sia da `make_row` sia dal planner, così riga e
  dialogo non divergono.

## Rischi e mitigazioni

- Poiché il magazzino HuggingFace è di uno strumento ignoto (causa), un blob "esclusivo" oggi può
  servire a un programma che lo legge senza symlink (rischio), e la rimozione romperebbe quel
  programma (effetto: modello da riscaricare, ore). → si cancellano solo blob raggiunti da un
  symlink dell'elemento e da nessun altro symlink della cache, ricontrollati all'esecuzione; il
  dialogo dice che i file del magazzino condiviso vengono rimossi; DEVIATIONS.
- Poiché la dimensione per elemento segue i symlink (causa), un link che esce dalla cache
  potrebbe far contare o cancellare file altrui (rischio, effetto grave). → il target risolto deve
  stare dentro la cache reale; test appaiato con link fuori; `safe_tree` non segue link.
- Poiché `ollama rm` parla col server (causa), la regola attuale "rifiuta mentre ollama serve"
  (`OllamaServing`) si inverte per l'elemento (rischio di incoerenza). → per l'azione per
  elemento il server è richiesto, per la pulizia intera resta vietato; due test distinti.
- Poiché `sdkmanager` richiede Java e scarica il manifest (causa), può superare il timeout o
  fallire offline (rischio: azione fallita a metà, 0,5 g di debug). → `--offline` se supportato
  (UNVERIFIED), timeout `CACHE_COMMAND_TIMEOUT_S`, esito FAILED con l'output; mai fallback a
  cancellare la cartella (l'SDK tiene `package.xml` coerenti).
- Poiché il parser del report è stretto (causa), lo schema 5 rompe i client D-Bus schema 4
  (rischio) → politica Q4=A già adottata, voce DEVIATIONS, XML aggiornato.
- Poiché una cache può avere migliaia di elementi (causa), la pagina rallenta (rischio) →
  `CACHE_ITEMS_CAP` = 50 sotto-righe, "e altre N", ordinamento per dimensione.
- Poiché le righe crescono di una riga di testo (causa), a 360 px titolo e bottone si
  schiacciano (rischio) → `subtitle_lines` 0, senza limite: con 4 righe la misura a 360 px
  troncava 6 conseguenze (Maven, SDK Android, ollama, AVD, immagine senza nome), 2026-10-19.
  Render osservato a 360 e 1280 a fine L1.

## Fuori scope

- Elementi per maven, gradle, uv, pip, cargo e le altre cache indirizzate per hash: valore basso
  o nessun comando sicuro per elemento; si rivedono su richiesta.
- Cancellazione di singoli file dal cestino: sono dati utente, servirebbe una vista a sé.
- Dataset e spaces HuggingFace sono inclusi come elementi; i modelli diffusers fuori da `hub`
  no.
- Nessuna rimozione automatica né pianificata: ogni cancellazione passa da un dialogo.

## Decisioni (prima domande aperte)

L'utente ha scelto il 2026-10-19 l'opzione A per Q1, Q2, Q3 e Q4 ("va bene quello che
consigli"). Il testo delle opzioni resta qui sotto come registro.

- **Q1** Blob del magazzino HuggingFace: (A, raccomandata) rimossi con il modello quando
  esclusivi per symlink, ricontrollati all'esecuzione; (B) mai toccati, il modello libera solo i
  propri file e il resto va in "Non attribuito".
- **Q2** ollama installato come servizio di sistema (il caso della macchina): (A, raccomandata)
  elenco e rimozione via `ollama list` / `ollama rm`, senza accesso ai file e con dimensioni dal
  server; (B) solo l'installazione nella home.
- **Q3** Voci DANGER nella selezione multipla: (A, raccomandata) non selezionabili, si rimuovono
  una per volta con la frase digitata; (B) selezionabili, con una frase digitata per ciascuna nel
  dialogo unico.
- **Q4** Elementi per Maven: (A, raccomandata) fuori scope ora; (B) per `groupId:artifactId`
  con CAUTION e cancellazione della cartella.

## Handoff

`tdd-guide` con `[DELEGATE-CODEX]` per i task di core, collector, executor (2-4 task per
invocazione, riga `SCOPE:`); `fullstack-developer` in-house per i task GTK (T-6.8, T-6.16,
T-6.24, T-6.29, T-6.39); `security-reviewer` a fine L3, L4, L5; `code-reviewer` a fine fase.
