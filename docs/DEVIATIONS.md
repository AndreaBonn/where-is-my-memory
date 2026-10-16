# Scostamenti e verifiche

Premesse [DA VERIFICARE] della specifica chiuse durante lo sviluppo e scelte che se ne
discostano, ciascuna con l'evidenza osservata.

## Type stubs (T-0.1a): premessa smentita, ripiego applicato

La premessa di §14.1 era che `pygobject-stubs`, `types-psutil` e `types-docker` si
installassero accanto ai moduli apt. Due punti non reggono:

- `pygobject-stubs` 2.18.0 dichiara la dipendenza `pygobject`. `uv sync` prova a compilarlo da
  PyPI e fallisce (`Dependency 'girepository-2.0' is required but not found`). Se riuscisse,
  metterebbe nel venv un PyGObject diverso da `python3-gi` 3.48.2 e i test non girerebbero
  più sul runtime del pacchetto.
- `types-docker` esiste solo dalla 7.0.0, mentre il runtime è docker 5.0.3. L'API tipizzata
  descriverebbe metodi e parametri che la 5.0.3 non ha (per esempio `stats(one_shot=...)`).

Ripiego in `pyproject.toml`:

- `[tool.uv] override-dependencies = ["pygobject; sys_platform == 'never'"]` elimina la
  dipendenza runtime degli stub. `gi` resta quello di `/usr/lib/python3/dist-packages`
  (verificato con `uv run python -c "import gi; print(gi.__file__)"`).
- `no-binary-package` e `config-settings-package` costruiscono gli stub con
  `config = "Gtk4,Gdk4,Soup3"`. Verificato: `gi-stubs/repository/Gtk.pyi` contiene
  `from ._Gtk4 import *`, e `mypy --strict` su una sonda risolve `Gtk.Box` e
  `Adw.AlertDialog` ai tipi GTK4 e Adw 1.
- `types-psutil==5.9.5.20240516`, l'ultima serie 5.9. Limite osservato: con questi stub i
  campi di `memory_full_info()` (`pfullmem`) risultano `Any`. I collector convertono quindi
  in `int` in modo esplicito al confine e i dataclass di `model.py` restano tipizzati.
- Nessuno stub per docker: override mypy `ignore_missing_imports` su `docker.*`. Il SDK si
  usa solo dietro `Protocol` tipizzati (`DockerControl`, sorgente dei container), quindi il
  resto del codice non vede `Any`.

Esito: `make setup`, `make lint` (ruff, ruff format, mypy) e `make test` (19 passed) verdi
il 2026-10-16. BASIS: measured.

## CI (T-0.3)

- Action pinnate a SHA: `actions/checkout` v6.1.0 =
  `d23441a48e516b6c34aea4fa41551a30e30af803`, `astral-sh/setup-uv` v8.3.2 =
  `11f9893b081a58869d3b5fccaea48c9e9e46f990`. SHA riverificati con `git ls-remote`.
- Noble pubblica python3-psutil 5.9.8 e python3-docker 5.0.3, gli stessi pin di
  `tests/test_runtime_versions.py`. La CI quindi non imposta `WIMM_SKIP_RUNTIME_PIN`.
  BASIS: inferred da packages.ubuntu.com; la CI remota non è ancora stata eseguita.
- La CI esegue `make test`, non `make test-all`: i test UI, D-Bus e di integrazione hanno
  bisogno di una sessione grafica e di Docker (decisione D-U3 di `plan.md`).

## `stop_group` / `group_stop` (T-0.2a)

§6.5 (esempio JSON, `primary_action.kind`) e l'esempio di chiamata in §8.1 scrivono
`stop_group`. L'enum `ActionKind` di §8.1 e il paragrafo "Semantica di `group_stop`" usano
invece `group_stop`. Vale `group_stop`, perché l'enum è la definizione e gli esempi sono
illustrativi. Il decoder rifiuta `stop_group`. BASIS: measured.

## Ordine di `categorize_process`: esclusione Docker prima di SYSTEM (T-1.4a)

Con l'ordine letterale di §5.1 la regola 3 non si raggiunge mai. Un processo in
`system.slice/docker-<id>.scope` sta sempre fuori da `user@<uid>.service`, quindi la regola 2
lo classifica `SYSTEM` prima che l'esclusione possa scattare. La riga `CONTAINER` della stessa
tabella chiede invece di escludere questi processi dal censimento, perché li rappresenta il
container. Senza esclusione la loro memoria comparirebbe due volte, nella vista Sistema e nel
gruppo del container.

Ordine applicato: `SELF`, esclusione per scope Docker, `SYSTEM`, poi le regole 4-9 invariate.

## Ereditarietà di `TERMINAL` (Q-1, T-1.4b)

Nella regola 5 di §5.1 l'ereditarietà per antenato vale solo per `BROWSER` e `DESKTOP_APP`.
`TERMINAL` si assegna per scope al solo processo del terminale. Ogni processo lanciato da
gnome-terminal ha come padre `gnome-terminal-server` (verificato su `zsh` il 2026-10-16):
con l'ereditarietà letterale ogni dev server e ogni CLI diventerebbe `TERMINAL`. Motivazione
completa in `specs/where-is-my-memory/plan.md` § Decisioni prese.

## Radice di progetto: la home non è una radice (T-1.2b)

§5.5.3 risale dalla `cwd` fino alla prima cartella con un marker (`.git`, `pyproject.toml`,
...). Un repository dei dotfiles in `~/.git` renderebbe la home la radice di ogni processo
senza un marker più vicino, e fonderebbe in un solo gruppo processi senza relazione tra loro.
La risalita si ferma quindi prima della home. Senza marker sotto la home vale la regola
"senza radice trovata: la `cwd` stessa".

## Container in rete `host` (T-1.5b)

Con `NetworkMode=host`, `/proc/<pid>/net/dev` riporta il traffico dell'intero host, non quello
del container. Per questi container `net_bytes` vale `None` e l'attività si misura solo dalla
CPU (§5.4), invece di attribuire al container il traffico di tutto il sistema.

## Categorie: servizi utente e app con documenti lanciate dal terminale (T-1.4b)

Due casi in cui la lettera di §5.1 avrebbe classificato `safe` un'azione che può far perdere
lavoro o stato. Si applica la regola di §0.6, l'opzione più conservativa:

- Un servizio systemd dell'utente (`<nome>.service` sotto `user@<uid>.service/app.slice` o
  `session.slice`, che non sia un terminale né un servizio di sessione noto) con una porta in
  ascolto non è `DEV_SERVER`. È `OTHER` (rischio `caution`, motivo `user_service`), perché lo
  gestisce systemd e "si riavvia con lo stesso comando" non vale. Esempi: syncthing, ollama
  avviato come servizio utente.
- Un'app con documenti (`DOCUMENT_APP_NAMES`, per esempio `code .`) lanciata da un terminale
  sta nello scope `vte-spawn`. È comunque `DESKTOP_APP`, con i figli, e non `DEV_PROCESS`:
  chiuderla può perdere file non salvati (§5.3).

## Nomi delle unit systemd con escape (T-1.4b)

systemd fa l'escape dei caratteri nei nomi delle unit (`app-gnome-google\x2dchrome-123.scope`,
`update\x2dnotifier`; verificato sulla macchina). I pattern di §5.1 e il lookup dei `.desktop`
si applicano al nome decodificato. Senza decodifica Chrome risulterebbe `DESKTOP_APP` e ogni
appid con un trattino perderebbe il nome e le categorie del suo `.desktop`.

## Attività: CPU mai misurabile nella finestra (T-1.7b)

§5.4 ammette `unknown` solo per una storia troppo corta o per un tipo non misurabile.
Se però in nessun intervallo della finestra la CPU di un'entità è stata misurabile (letture
negate o contatori azzerati a ogni ciclo), dichiararla `idle` vorrebbe dire affermare
un'inattività che nessun dato prova. In quel caso lo stato è `unknown`, con il motivo "CPU
non misurabile negli ultimi campioni".

## Conseguenza per la categoria `OTHER` (T-3.1a)

La tabella di §5.3 non ha una riga per `OTHER`. Il testo generico delle app ("L'applicazione si
chiude.") sarebbe fuorviante per un servizio utente come syncthing, che non è un'applicazione
e che systemd può far ripartire. Testo usato: "Il programma si ferma: ciò che ha in memoria e
non ha salvato va perso. Se è un servizio, potrebbe riavviarsi da solo." Il rischio resta
`caution`.

## Id stabile dei gruppi: classe della chiave al posto della categoria (T-1.6b)

§5.5 calcola l'id come hash di (categoria, chiave) e chiede che sia stabile fra campioni,
perché notifiche, silenzi e storia vi si appoggiano. Con la categoria risolta nell'hash l'id
cambierebbe quando un gruppo cartella passa da `DEV_SERVER` a `DEV_PROCESS` (il server smette
di ascoltare), oppure quando un progetto compose si fonde con un dev server in `PROJECT`, e un
silenzio impostato dall'utente andrebbe perso. L'id usa quindi la classe della chiave
(`compose`, `container`, `folder`, `app`, `root_process`, `protected`), che non cambia mentre
il gruppo vive.

## Vista Sistema: gruppi per etichetta (T-1.6b)

I processi protetti si raggruppano nelle etichette di RF-07: "Sessione GNOME", "Audio",
"Servizi di sistema", "Altri utenti", più l'app stessa. Un gruppo per nome di processo
avrebbe prodotto decine di righe, e id instabili per i thread del kernel con il nome numerato.

## Processo residente senza GTK: `Gio.Application` con finestra caricata a richiesta (T-1.8c)

§6.1 prevede un'`Adw.Application` residente e mette in conto che "GTK4 resta caricato anche a
finestra nascosta (budget in RNF-02)". Misurato sulla macchina di destinazione il 2026-10-16,
con il Python di sistema: il solo `from gi.repository import Gtk` (GTK 4) porta un processo da
19 MB (Gio e GLib) a 124 MB di RSS, già sopra i 120 MB di RNF-02 prima di qualunque dato.
Con l'architettura letterale il requisito non si può rispettare.

Il processo residente è quindi una `Gio.Application` con lo stesso `application_id`, le
opzioni da riga di comando, `hold()`, l'istanza unica, l'Inspector D-Bus, l'icona
StatusNotifierItem e le notifiche `Gio.Notification`. Nessuna di queste parti dipende da GTK
(§6.1 lo dice già per l'icona). GTK e libadwaita si importano alla prima apertura della
finestra. La finestra è un'`Adw.Window` con `insert_action_group("app", applicazione)`, così le
azioni `app.*` continuano a funzionare. Il comportamento visibile non cambia: chiudere nasconde,
"Esci" termina, la seconda invocazione porta la finestra in primo piano.

Prototipo verificato sotto Xvfb: finestra mostrata, chiusura che nasconde, processo vivo. Il
consumo dopo l'apertura della finestra va misurato sul display reale (RNF-02, seconda soglia:
200 MB).
