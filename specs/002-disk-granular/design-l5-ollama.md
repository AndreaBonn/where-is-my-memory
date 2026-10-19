# Nota di design L5: modelli ollama dell'installazione di sistema (T-6.37, T-6.38)

Data 2026-10-20, HEAD `f5dbbd0`. Fonte di verità `assets/SPECIFICHE.md` (RF-22, RF-51, RF-52,
§5.1 riga `SYSTEM`, decisioni della Fase 6, lotto L5). Decisione dell'utente **Q2=A**: i modelli
ollama si offrono anche per l'installazione come servizio di sistema, elencati con `ollama list`
e rimossi con `ollama rm`, senza mai toccare i file. Rischio `danger`.

Questa nota non cambia la specifica: dove serve un testo nuovo in SPECIFICHE lo segnala nel
task che lo produce.

## Fatti misurati su questa macchina (2026-10-20)

| Fatto | Come | BASIS |
|---|---|---|
| ollama 0.18.0 in `/usr/local/bin/ollama`, unità systemd `ollama`, `User=ollama` (uid 997), `ExecStart=/usr/local/bin/ollama serve`, `Environment=... OLLAMA_HOST=0.0.0.0:11434` | `systemctl show ollama` | measured |
| Un solo processo `ollama serve`, pid 2600, utente `ollama`; `/proc/2600/cmdline` leggibile (0444), `/proc/2600/environ` negato | `ps`, `ls -l`, `cat` | measured |
| Il socket in ascolto su `:11434` (in `/proc/net/tcp6`) ha uid 997 | `awk` su `/proc/net/tcp6` | measured |
| `~/.ollama` non esiste: oggi la home non ha magazzino | `ls` | measured |
| Colonna ID di `ollama list` = primi 12 esadecimali dello sha256 del **file manifest** (4 su 4) | `sha256sum` dei manifest in `/usr/share/ollama/.ollama/models/manifests` | measured |
| Colonna SIZE in unità **decimali** a una cifra: 5 969 245 856 B (config + layer) → `6.0 GB`; 6 594 474 711 → `6.6 GB`; 3 338 801 804 → `3.3 GB`; 4 676 805 193 → `4.7 GB`. Errore massimo 0,05 GB per riga | somma `size` dei manifest contro l'output | measured |
| Le righe di `ollama list` finiscono con spazi | `cat -A` | measured |
| `ollama list` dura ~0,2 s | `time` | measured |
| Server irraggiungibile: `Error: could not connect to ollama server, run 'ollama serve' to start it`, exit 1 | `OLLAMA_HOST=127.0.0.1:1 ollama list` | measured |
| `ollama rm -- <nome inesistente>`: `Error: model '<nome>' not found`, exit 1; l'output contiene sequenze di escape del terminale (spinner) anche senza tty | probe con un nome che non esiste | measured |
| `--` chiude le opzioni: `ollama show -- gemma3:4b` funziona, `ollama show -- -x` risponde `invalid model name`; con `rm` il `--` è accettato (probe sopra) | comandi di sola lettura e probe | measured |
| `ollama rm` e `ollama list` parlano al server indicato da `OLLAMA_HOST` (default `127.0.0.1:11434`) | `--help` di entrambi | measured |
| `ollama rm` cancella dal magazzino del server che risponde, non da un path scelto da chi chiama | deduzione dall'architettura client/server di ollama | inferred |

Fatti del codice (HEAD `f5dbbd0`), tutti `measured` per lettura:

- `planning_cache_item._find_item` identifica un elemento con `<cache kind>:<item id>` e prende
  la **prima** voce con quel `kind`: due voci `CacheKind.OLLAMA` renderebbero ambiguo
  `ollama:gemma3:4b`.
- `executor_cache_item.SUPPORTED_KINDS` (HF, Playwright, JetBrains) e `COMMAND_KINDS` (Android)
  non contengono `OLLAMA`: oggi la UI (`ui/disk_items.py:55`) mostra "Rimuovi" sugli elementi
  ollama della home, il piano si costruisce, e l'executor lo rifiuta con `ProtectedTarget`
  ("not directly inside an item cache"). Il percorso dell'elemento è un **file** manifest, e
  `_verify_folder` esige una cartella. È un buco aperto da T-6.36 che T-6.38 chiude.
- `executor_disk_fs._refuse_while_ollama_serves` rifiuta la pulizia intera della home con
  **qualunque** `ollama serve` vivo, anche quello di sistema, che non tiene aperti i file della
  home. Comportamento esistente (R24), fuori da questo lotto: vedi domande aperte.
- `list_process_identities` restituisce solo nome e argv, senza uid.
- File vicini al limite: `executor_cache_item.py` 251, `executor_disk_fs.py` 276,
  `risk_table.py` 255, `actions.py` 271 righe. Il codice nuovo va in moduli nuovi.

## 1. Come compare l'installazione di sistema nel report

**Scelta: nuovo `CacheKind.OLLAMA_SYSTEM = "ollama_system"`**, una `CacheEntry` separata da quella
della home, con elementi `CacheItemKind.OLLAMA_MODEL` (stesso rischio `danger`, stessa
conseguenza `ITEM_OLLAMA`).

Alternative scartate:

- *Stesso `CacheKind.OLLAMA` con un campo "origine" sulla voce*: il target `ollama:<nome>` diventa
  ambiguo fra home e sistema (vedi `_find_item`), e ogni tabella indicizzata per kind (titoli,
  rischio della pulizia intera, catalogo, `CACHE_CLEAN`) dovrebbe ramificare sul campo. Il
  difetto peggiore è il primo: un click sulla riga di un magazzino potrebbe pianificare
  l'elemento omonimo dell'altro.
- *Nuovo solo `CacheItemKind`*: lascia comunque due voci con lo stesso `CacheKind`, quindi la stessa
  ambiguità del target.

Contenuto della voce:

| Campo | Valore | Perché |
|---|---|---|
| `kind` | `OLLAMA_SYSTEM` | target univoco `ollama_system:<nome>` |
| `path` | costante `OLLAMA_SYSTEM_PATH = "ollama list"` | `require_text` la esige; non è un path e non va mai usata come tale. La UI non la mostra (T-6.39) |
| `st_ino`, `st_dev` | `0`, `0` | nessun file letto; `require_nonnegative` li accetta |
| `size` | somma delle dimensioni degli elementi | |
| `rest` | `CacheRest()` (zero e zero) | nessuna scansione: non esistono condiviso né non attribuito osservati |
| `items` | una riga per modello di `ollama list` | |

Invariante "elementi + resto ≤ dimensione": vale per costruzione, con l'uguaglianza. Il validatore
di `CacheEntry` aggiunge, **solo** per `OLLAMA_SYSTEM`: `st_ino == st_dev == 0`, `rest` vuoto,
ogni elemento con `model_id` valido (sezione 2). Uno stato illegale (una voce di sistema con un
inode, che qualcuno potrebbe trasformare in `DirFingerprint`) non si può costruire.

Dimensione: `float(valore) × 1000^unità` (B, KB, MB, GB, TB), arrotondata a intero. È una stima
con errore fino a 50 MB per modello, e conta due volte i layer che due modelli condividono (con
`ollama list` non si vedono). Alternative scartate:

- *API `GET /api/tags`* (byte esatti e digest completo): esce dal testo di Q2=A ("via `ollama list`"),
  aggiunge un client HTTP e una superficie di rete. Si apre solo con una decisione dell'utente
  (domanda aperta D3).
- *Leggere i manifest in `/usr/share/ollama`*: viola "nessun accesso ai file" (Q2=A, T-6.37), e il
  path del magazzino del servizio non è osservabile (`environ` negato): sarebbe un'inferenza dal
  default di systemd.

Pulizia intera: **mai** offerta. Nuova costante pura `ITEM_ONLY_KINDS = frozenset({OLLAMA_SYSTEM})`
in `core/item_tools.py`, consultata in tre punti indipendenti: la riga di cache in UI non ha
azione, il planner di `CACHE_CLEAN` rifiuta il kind con `InvalidRequest`, l'executor lo rifiuta
comunque perché il kind non è nella tabella di avvio (`CacheResolution`), quindi `_cache_of` e il
percorso di pulizia non lo trovano. "Libera spazio" prende solo `safe` e la selezione multipla
esclude i `danger` (Q3=A): nessuna via massiva arriva a questi modelli.

Quando la voce **non** compare: tool assente; nessun `ollama serve` o più di uno; il server unico
è dell'utente corrente (i suoi modelli sono già elementi della home); `OLLAMA_HOST` punta a un host
non locale (i modelli non sono su questo disco); `ollama list` esce con codice ≠ 0, va in timeout
o produce un output che il parser rifiuta. In tutti questi casi: nessuna voce, una riga di log
`WARNING` con il motivo, nessun dato inventato.

Doppio conteggio con la home: se il servizio di sistema è configurato sul magazzino della home
(`OLLAMA_MODELS=/home/<u>/.ollama/models` nell'unità), lo stesso modello comparirebbe due volte.
Regola: se l'insieme dei nomi listati coincide con quello degli elementi della home e non è vuoto,
la voce di sistema non si emette e il log lo dice. Sbaglia solo verso il basso (un magazzino di
sistema identico per nomi resta invisibile), mai verso una rimozione sbagliata. BASIS: inferred,
configurazione non presente su questa macchina.

## 2. Cosa identifica un modello di sistema all'esecuzione

**Scelta: nuovo `ServedModelFingerprint(name: str, model_id: str)`** in `model/actions.py`, con
`ACTION_FINGERPRINT_TYPES[CACHE_ITEM_REMOVE] = (ItemFingerprint, ServedModelFingerprint)`.
`model_id` sono i 12 esadecimali della colonna ID (sha256 del manifest, misurato). Subito prima di
`ollama rm` l'executor riesegue `ollama list` e procede solo se trova **esattamente una** riga con
quel nome e quell'ID; ID diverso → `TargetChanged` ("il modello è stato riscaricato o cambiato"),
nome assente → passo `SKIPPED` come per un elemento già sparito.

Alternative scartate:

- *`ItemFingerprint` con `realpath = nome` e inode 0*: mescola due semantiche (file controllato
  con `lstat` contro modello servito), e ogni controllo su `realpath` dovrebbe sapere che a volte
  non è un path. È esattamente lo stato illegale che il tipo deve impedire.
- *Solo il nome*: non distingue `gemma3:4b` riscaricato con un altro contenuto fra il report e la
  conferma; la conferma `danger` coprirebbe un oggetto diverso da quello mostrato.

Dove vive l'ID nel `CacheItem`: **nuovo campo opzionale `model_id: str = ""`**. Validazione: vuoto,
oppure `^[0-9a-f]{12}$`; obbligatorio (non vuoto) per gli elementi di `OLLAMA_SYSTEM`, che hanno
anche `path = f"ollama:{name}"`, `st_ino = st_dev = 0`, `blobs = ()`.

- Scartato *ID codificato nell'`id`* (`gemma3:4b@a2af6cc3eb7f`): l'`id` oggi è il nome che
  `ollama rm` accetta (convenzione di T-6.36) e il target `<kind>:<id>` lo trasporta; codificarci
  l'ID obbliga a un parse in più in planner, UI ed executor.
- Scartato *ID nel `path`*: il `path` è il sottotitolo in UI e il `owner_ids` del piano; renderlo
  portatore di identità sposta il contratto in una stringa.

Impatto sul wire: `CacheItem.model_id` entra in `disk_wire.OPTIONAL_FIELDS` con default `""` e
nel decoder come `TEXT`; `CacheKind` guadagna un valore. Entrambe aggiunte: lo schema resta 5.
Il report non è persistito su disco (`disk_report_from_json` non ha chiamanti in `src`), quindi
non c'è un file vecchio da rileggere. BASIS: measured (grep), da riverificare in T-6.37a.

## 3. Su quale magazzino agisce `ollama rm`

Su quello del server che risponde a `OLLAMA_HOST`, e su nessun altro. Il punto che decide la
sicurezza: quando risponde il server di sistema, `ollama rm gemma3:4b` lanciato da una riga della
**home** cancellerebbe la copia di sistema, se esiste, e lascerebbe intatta quella mostrata.

Regola pura `served_store(...)` in `core/ollama_served.py`, che classifica la situazione da fatti
raccolti dal collector (processi `ollama serve` con uid, `OLLAMA_MODELS` del server leggibile solo
se è dell'utente, `OLLAMA_HOST` dell'ambiente di wimm, path del magazzino home):

| Situazione | Riconoscimento | Voce di sistema | Elementi della home |
|---|---|---|---|
| S0 nessun server | nessun processo `ollama serve` | assente | mostrati, "Rimuovi" disabilitato: "Avvia ollama per rimuovere un modello" |
| S1 server dell'utente sul magazzino home | un solo `ollama serve` con uid corrente, e il suo `OLLAMA_MODELS` (da `/proc/<pid>/environ`) risolto con `realpath` coincide con il path della voce home; variabile assente = `~/.ollama/models` | assente | rimovibili con `ollama rm` |
| S1' server dell'utente su un altro magazzino | come S1 ma path diverso, o `environ` illeggibile | assente | non rimovibili: "Il server ollama attivo usa un'altra cartella di modelli" |
| S2 server di sistema | un solo `ollama serve` con uid diverso | presente, elementi rimovibili | non rimovibili: "Il server ollama attivo è quello di sistema e non vede questi modelli" |
| S3 ambiguo | due o più `ollama serve`, oppure `OLLAMA_HOST` non locale | assente | non rimovibili |

"Richiede il server attivo", in termini precisi:

- **elemento di sistema**: situazione S2 sia al report sia all'esecuzione, e la riga `nome` + `ID`
  presente nel `ollama list` rieseguito subito prima di `ollama rm`;
- **elemento della home**: situazione S1 all'esecuzione, il manifest ancora al suo posto con lo
  stesso `st_ino`/`st_dev` (`ItemFingerprint` esistente, controllo per **file** e non per cartella),
  posseduto dall'utente, e dopo il comando il manifest sparito. Altrimenti `ControlFailed`, mai un
  ripiego sulla cancellazione dei file.

La pulizia intera della home resta rifiutata con qualunque server attivo (regola R24 esistente,
"pulizia intera con server attivo resta rifiutata" nel verify di T-6.38).

Alternativa scartata per il riconoscimento del server: *uid del socket in `/proc/net/tcp6`* sulla
porta di `OLLAMA_HOST`. Più preciso quando girano più server, ma aggiunge un parser di
`/proc/net` per un caso (S3) che la regola scelta già tratta rifiutando. Si riprende se S3 risulta
frequente.

Ambiente dei comandi: `PATH`, `LANG`, `HOME` e, se presente, `OLLAMA_HOST` dell'ambiente di wimm;
lo stesso dizionario per `list` e per `rm`, così i due comandi parlano allo stesso server.
Timeout: `OLLAMA_LIST_TIMEOUT_S = 10` nuova costante per il listing in scansione (misurato 0,2 s);
`CACHE_COMMAND_TIMEOUT_S` (300) per `rm`.

Finestra residua: fra il `list` di controllo e `rm` passano circa 0,2 s; un `ollama pull` dello
stesso nome in quell'intervallo verrebbe rimosso. L'API di ollama non offre un `rm` condizionato al
digest. Si dichiara nel report di T-6.40; BASIS: inferred.

## 4. Validazione dei nomi prima dell'argv

Funzione pura `is_valid_model_name(name)` in `core/ollama_names.py`, applicata in quattro punti:
parser di `ollama list`, costruzione degli elementi home (T-6.36: i nomi vengono da path, che
possono contenere qualsiasi byte), planner, executor subito prima dell'argv.

- forma `[<host>/][<namespace>/]<nome>:<tag>`, regex
  `^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*){0,2}:[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$`;
- lunghezza massima 255;
- rifiutati quindi: `-` iniziale (anche dopo `/`), spazi, caratteri di controllo, `..`, una seconda
  `:` (un host con porta, `localhost:5000/...`, non si offre: perdita accettata, lato sicuro).

Un nome rifiutato: l'elemento della home **resta visibile senza azione** (i suoi byte contano);
una riga di sistema rifiutata fa rifiutare tutto l'output (sotto). `model_id` è validato con
`^[0-9a-f]{12}$`.

argv: `(<path assoluto di ollama>, "rm", "--", name)`, lista, niente shell; il path assoluto si
risolve come per gli strumenti Android (`which` iniettato, solo risultati assoluti). L'output del
comando, prima di finire in log o in `ControlFailed`, perde le sequenze di escape e i caratteri di
controllo (misurato: `rm` stampa lo spinner anche senza tty).

Parser di `ollama list` (puro, `core/ollama_list.py`), schema stretto:

- prima riga, spazi finali tolti, deve dividersi esattamente in `NAME ID SIZE MODIFIED`;
- ogni riga: `^(?P<name>\S+)\s+(?P<id>[0-9a-f]{12})\s+(?P<num>\d+(\.\d+)?) (?P<unit>B|KB|MB|GB|TB)\s+\S.*$`
  dopo aver tolto gli spazi finali; nome valido per la funzione sopra; nomi univoci;
- una sola riga fuori schema → tutto l'output rifiutato (`None`), log `WARNING`. Una lista parziale
  sottostimerebbe la voce senza dirlo, e un formato cambiato in una versione nuova di ollama si
  vede come assenza invece che come dati sbagliati;
- output con la sola intestazione → voce con zero elementi, non emessa (nessuna riga vuota in UI).

## 5. Scomposizione

Le righe T-6.37, T-6.38, T-6.39 del piano restano; si dividono in sotto-task con suffisso per
tenere il limite di 300 righe e moduli nuovi accanto ai file già pieni. Deviazioni dal file
indicato nel piano: il parser va in `core/` (funzione pura, regola di architettura) e l'executor
ollama in un modulo nuovo invece di `executor_cache_item.py` (251 righe).

| ID | Cosa | File | Dip | Verify | Rischio |
|---|---|---|---|---|---|
| T-6.37a | `CacheKind.OLLAMA_SYSTEM`; `CacheItem.model_id` opzionale e validato; invarianti di `CacheEntry` per il kind; wire (`OPTIONAL_FIELDS`, decoder); titolo in `cache_titles.py`; riga in `risk_table.py` (pulizia intera assente, elemento `danger`); `ITEM_ONLY_KINDS` | `src/wimm/model/disk.py`, `src/wimm/model/cache_items.py`, `src/wimm/core/disk_wire.py`, `src/wimm/core/cache_titles.py`, `src/wimm/core/risk_table.py`, `src/wimm/core/item_tools.py` | T-6.36 | `tests/model/test_cache_items.py`: `model_id` "" e 12 hex accettati, 11 hex/maiuscole rifiutati; `CacheEntry(OLLAMA_SYSTEM, st_ino=5)` rifiutata con caso appaiato `st_ino=0` accettato; round-trip wire con e senza `model_id`; `grep -c` del nuovo kind in ogni tabella esaustiva per kind (i test parametrici esistenti su `CacheKind` devono fallire prima di aggiungerlo) | medio: ogni tabella esaustiva per kind |
| T-6.37b | Parser puro di `ollama list`, `is_valid_model_name`, regola `served_store` | `src/wimm/core/ollama_list.py`, `src/wimm/core/ollama_names.py`, `src/wimm/core/ollama_served.py` | T-6.37a | fixture `tests/fixtures/ollama/list_0_18_0.txt` = l'output misurato sopra, spazi finali compresi: 4 elementi, `gemma3:4b` = 3 300 000 000 B, ID `a2af6cc3eb7f`; varianti: intestazione cambiata, riga con ID di 11 caratteri, nome `-rf:x`, nome con `\x1b`, unità `GiB`, solo intestazione, output vuoto → `None` o lista vuota come da sezione 4; tabella S0-S3 parametrica | basso |
| T-6.37c | Collector: tool risolto per path assoluto, processi `ollama serve` con uid (e `environ` solo se dell'utente), `ollama list` con `OLLAMA_LIST_TIMEOUT_S` via `CommandRunner` iniettato, regola anti-doppione; voce aggiunta alla scansione in `disk_scanner.py`; elementi home con nome non valido senza azione | `src/wimm/collectors/ollama_models.py`, `src/wimm/service/disk_scanner.py`, `src/wimm/core/constants.py` | T-6.37b | test con runner finto: tool assente → nessuna voce e nessuna esecuzione; exit 1 con il messaggio misurato → nessuna voce + `WARNING`; timeout → nessuna voce; server dell'utente → nessuna voce; server di sistema → voce con 4 elementi e `size` = somma; nomi identici alla home → nessuna voce. Nessun ollama reale nei test | medio |
| T-6.38a | `ServedModelFingerprint`, `ACTION_FINGERPRINT_TYPES`; planner: elemento di sistema → nuova impronta, elemento home → `ItemFingerprint` sul manifest; `CACHE_CLEAN` su `ITEM_ONLY_KINDS` → `InvalidRequest`; elementi ollama con nome non valido → `InvalidRequest` | `src/wimm/model/actions.py`, `src/wimm/core/planning_cache_item.py`, `src/wimm/core/planning_disk.py` | T-6.37a | `tests/core/test_planning_cache_item.py`: `ollama_system:gemma3:4b` → passo con `name` e `model_id`; `ollama:gemma3:4b` con entrambe le voci presenti → elemento della home (target univoco); `CACHE_CLEAN` di `ollama_system` rifiutato con caso appaiato su `ollama` accettato | medio: `actions.py` a 271 righe, l'impronta nuova può richiedere uno spostamento |
| T-6.38b | Executor di sistema: ricontrollo S2, `ollama list` ripetuto, riga unica con stesso ID, argv `(tool, "rm", "--", name)`, output ripulito, `list` dopo il comando senza il nome → `DONE` con `freed_bytes = size`; nome ancora presente → `ControlFailed`; dispatch per tipo d'impronta da `check_cache_item`/`run_cache_item` | `src/wimm/service/executor_ollama_item.py`, `src/wimm/service/executor_cache_item.py` (solo dispatch) | T-6.38a T-6.22 | runner finto che registra le chiamate: server assente → rifiuto con messaggio e **nessuna** chiamata a `rm`; ID cambiato → `TargetChanged` e nessun `rm`; nome sparito → `SKIPPED`; argv esatto con `--`; mutazione (togliere il ricontrollo dell'ID) fa fallire almeno un test | alto: azione `danger` irreversibile |
| T-6.38c | Executor home: controllo del manifest come **file** (`lstat`, stesso inode, proprietario, niente symlink), S1 obbligatoria, `ollama rm`, manifest sparito dopo il comando; chiude il buco attuale (UI che offre e executor che rifiuta) | `src/wimm/service/executor_ollama_item.py` | T-6.38b | test: S2 con elemento home → rifiuto con il testo della tabella S2 e nessun `rm`; S1 → `rm` e manifest rimosso dal runner finto → `DONE`; manifest rimasto → `ControlFailed` senza cancellare file; pulizia intera con server attivo resta rifiutata (test esistente verde) | alto |
| T-6.39 | UI: voce di sistema con titolo proprio, sottotitolo "dimensioni stimate da ollama" al posto del path, nessuna azione di cache; elementi home con azione disabilitata e motivo per S0, S1', S2, S3; conferma `danger` con frase = nome del modello; `make po` | `src/wimm/ui/disk_items.py`, `src/wimm/ui/disk_view.py`, `src/wimm/ui/dialogs/text.py`, `po/en.po` | T-6.38c | `tests/ui/test_disk_model.py`: riga `ollama_system` senza azione con caso appaiato `ollama` con azione; click-through con runner finto su S2 (rimuovi un modello di sistema, frase digitata, esito) e S0 (azione disabilitata con motivo); `make lint` verde con `check_i18n.py` | medio |

Rollback: `revert` per ogni sotto-task; nessuna migrazione e nessun dato persistito. I test non
eseguono mai `ollama` reale (§0.5): `CommandRunner` e la lista processi sono iniettati.

T-6.40 resta com'è; `security-reviewer` riceve in particolare la sezione 4 e la finestra residua
della sezione 3.

## Decisioni di prodotto (utente, 2026-10-20)

- **D1** Elementi della home con il server di sistema attivo (S2): mostrati senza azione, con il
  motivo scritto. Nessun `ollama serve` avviato dall'app.
- **D2** La pulizia intera della home resta rifiutata con qualunque server ollama attivo (R24
  invariata).
- **D3** Dimensioni dalla stima di `ollama list`, dichiarata in UI come "dimensioni stimate da
  ollama". Niente `GET /api/tags`.
- **D4** La voce di sistema entra nei totali della pagina Disco come le altre cache.
