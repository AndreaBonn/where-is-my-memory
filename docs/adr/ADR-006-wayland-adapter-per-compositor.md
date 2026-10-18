# ADR-006: programma in primo piano su Wayland, un adapter per compositor

- Stato: Accettata (2026-10-18, decisione D1 del piano 001-product-gaps)
- Data: 2026-10-18

## Context

Browser, app desktop e terminali sono giudicati dal primo piano (`assets/SPECIFICHE.md` §7.8):
senza quel segnale restano `unknown`. Oggi lo legge solo `ForegroundReader`
(`src/wimm/collectors/foreground.py`) con due chiamate a `xprop` (`_NET_ACTIVE_WINDOW`, poi
`_NET_WM_PID`), attivo solo con `XDG_SESSION_TYPE=x11`. Su Wayland il lettore torna `disabled`,
`foreground_group_pids` restituisce None, `EntitySample.foreground` resta None e le entità di
quelle categorie restano `unknown` (N4). Il sampler dipende dal protocollo `ForegroundSource`
(`src/wimm/service/sampler_collectors.py:27`, un solo metodo `read() -> ForegroundState`), quindi
la sorgente si sostituisce senza toccare core e sampler. Ubuntu 24.04 parte in Wayland di default:
R36 chiede la scelta, R37 il segnale, con l'app che funziona come oggi se il componente manca.

## Decision

`ForegroundSource` diventa una porta con un adapter per compositor, scelto all'avvio da
`XDG_SESSION_TYPE` e `XDG_CURRENT_DESKTOP`:

1. **X11**: `ForegroundReader` com'è oggi, nessuna modifica.
2. **GNOME Shell su Wayland**: estensione opzionale `wimm-focus@wimm.github.io`, nel pacchetto
   .deb sotto `/usr/share/gnome-shell/extensions/` (`data/gnome-shell-extension/`, T100, T102).
   Il .deb non la attiva: l'utente la abilita (`gnome-extensions enable ...` o app Estensioni),
   dalle Preferenze di wimm che spiegano come. Il collector (`collectors/foreground_wayland.py`,
   T101) la legge con un proxy Gio e segue la comparsa del nome con `Gio.bus_watch_name`: se
   l'utente la abilita a app aperta, il segnale arriva senza riavvio.
3. **KWin e wlroots** (sway, Hyprland): nessun adapter finché un utente non lo chiede. Restano
   possibili dietro la stessa porta (script KWin, IPC di sway e Hyprland).
4. **Euristiche, in ogni sessione Wayland**: possono solo alzare un campione ad attivo, mai
   abbassarlo. Uno stream PipeWire in stato running con `application.process.id` di un membro
   del gruppo (musica o video in sottofondo) e un delta di CPU sopra soglia nel ciclo marcano il
   campione attivo. Non producono mai `foreground=False`: senza un adapter di focus un'app non
   diventa `idle`, quindi nessuna proposta di chiusura nasce da un'euristica.

### Interfaccia D-Bus dell'estensione

- Bus: sessione. Nome posseduto da `gnome-shell`: `io.github.wimm.Focus`.
- Oggetto `/io/github/wimm/Focus`, interfaccia `io.github.wimm.Focus1`
  (`data/dbus/io.github.wimm.Focus1.xml`, stesso schema di ADR-004).
- Proprietà `FocusedPid`, tipo `u`, accesso `read`, con `PropertiesChanged` emesso su
  `notify::focus-window` di `global.display`. Si legge anche con
  `gdbus call --session --dest io.github.wimm.Focus --object-path /io/github/wimm/Focus
  --method org.freedesktop.DBus.Properties.Get io.github.wimm.Focus1 FocusedPid` (verifica di T100).
- Valore: `Meta.Window.get_pid()` della finestra con il focus. Senza focus (desktop, schermo
  bloccato, overview senza finestra selezionata) o con un pid sconosciuto o non positivo vale `0`.
  Il collector traduce `0` in `unavailable`, mai in "nessuna app in primo piano".
- Proprietà `Version` (`u`), per far riconoscere al collector un'estensione più vecchia.
- `shell-version: ["46"]` nel `metadata.json`; `disable()` revoca il nome e l'oggetto.

### Sicurezza

- Sola lettura: nessun metodo, nessuna proprietà scrivibile, nessun segnale oltre
  `PropertiesChanged`. L'estensione non riceve comandi e non agisce su finestre o processi.
- Nessun dato oltre il pid: non escono titolo, classe, app id né contenuto della finestra.
- Il nome si verifica prima di fidarsi: il collector chiede
  `GetConnectionUnixProcessID` al bus e accetta il proprietario solo se `/proc/<pid>/exe` è
  `/usr/bin/gnome-shell` dello stesso utente. Un processo di sessione che occupa il nome per
  primo non fornisce il primo piano; in quel caso lo stato resta `unavailable`.
- Nessuna azione dipende dal segnale senza conferma (N1): un pid sbagliato al massimo fa
  proporre come inattiva un'app aperta, che l'utente vede e rifiuta.

## Consequences

- Senza estensione abilitata il comportamento resta quello di oggi: `disabled`/`unavailable`,
  entità `unknown`, più le sole euristiche che alzano ad attivo. Nessuna regressione su X11.
- Costo fisso: a ogni release di GNOME va provata l'estensione e aggiornato `shell-version`,
  altrimenti GNOME la disattiva; rilasciare il .deb con la versione nuova è la stessa attività.
- Il .deb aggiunge un componente JavaScript (ESM, GJS) con i suoi test manuali (M-* Wayland);
  la logica di traduzione pid -> stato resta in Python e si testa con proxy finto (T101).
- `docs/DEVIATIONS.md` registra il superamento di N4 (T102).
- Il pid arriva dalle credenziali del socket Wayland, non da `_NET_WM_PID` dichiarato dal client.

## Alternatives considered

- **`org.gnome.Shell.Introspect.GetWindows`.** Scartata: su GNOME 46 risponde AccessDenied ai
  client non autorizzati, misurato il 2026-10-18. È riservata a portali e strumenti di sistema.
- **`org.gnome.Mutter.IdleMonitor`.** Scartata come risposta: dà solo l'inattività dell'intera
  sessione, non quale app è in primo piano, quindi non distingue un browser usato da uno dimenticato.
- **AT-SPI** (albero di accessibilità, finestra attiva). Scartata: chiederlo accende l'albero di
  accessibilità in Chromium, Firefox ed Electron, che consumano più RAM proprio nelle app che
  wimm misura, e alza la CPU durante la navigazione.
- **Solo euristiche (audio, CPU).** Scartata come segnale unico: alzano ad attivo, ma senza focus
  non c'è modo onesto di dire `idle`.
- **Estensione attivata dal pacchetto** (`gsettings` di sistema). Scartata: un pacchetto non deve
  cambiare le estensioni abilitate della sessione dell'utente.

## Rischi residui

- Fra il rilascio di una nuova GNOME e l'aggiornamento di `shell-version` l'estensione è
  disattivata da GNOME e wimm torna allo stato di oggi senza errore visibile: le Preferenze
  devono mostrare "estensione non attiva" invece di tacere.
- `Meta.Window.get_pid()` per app Flatpak e per finestre Xwayland: UNVERIFIED che restituisca
  sempre il pid del namespace host; un pid che non è un processo noto resta None
  (`foreground_group_pids`), come oggi per Flatpak su X11.
- Il controllo sul proprietario del nome dipende dal path `/usr/bin/gnome-shell`: una distro che
  lo installa altrove deve allineare la costante.
- Le soglie dell'euristica CPU sono valori iniziali in costanti nominate, non tarati: un'app con
  timer in sottofondo può restare attiva e quindi non essere mai proposta.
- Uno stream PipeWire aperto ma silenzioso (una chiamata in muto, una scheda che tiene il device)
  tiene attivo il gruppo: è il verso sicuro dell'errore.
- Senza adapter KWin e wlroots gli utenti Plasma e sway restano a `unknown` fino a una richiesta.
