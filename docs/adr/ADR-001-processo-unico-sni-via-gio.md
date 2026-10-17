# ADR-001: un solo processo, con l'icona nella barra come StatusNotifierItem via Gio

- Stato: Accettata
- Data: 2026-10-17

## Context

`wimm` deve restare residente dal login, mostrare un'icona nella barra di GNOME e aprire una
finestra libadwaita al clic sinistro (RF-42, `assets/SPECIFICHE.md` §6.1). La libreria usuale per
le icone, `AyatanaAppIndicator3`, è GTK3, mentre libadwaita richiede GTK4: le due versioni non
convivono nello stesso processo Python (`assets/SPECIFICHE.md` §6.1, "Vincolo tecnico").
Con AppIndicator, inoltre, il clic sinistro apre sempre un menu e non permette di aprire
direttamente la finestra (§6.1).

Una misura successiva ha aggiunto un secondo vincolo: sulla macchina di destinazione il solo
`from gi.repository import Gtk` porta il processo da 19 MB a 124 MB di RSS, già sopra il tetto di
120 MB di RNF-02 (`docs/DEVIATIONS.md`, sezione "Processo residente senza GTK").

## Decision

Esiste un solo eseguibile, `wimm`, e un solo processo. L'icona implementa direttamente il
protocollo D-Bus `org.kde.StatusNotifierItem` con `Gio`, senza alcuna libreria GTK
(`src/wimm/tray/status_notifier.py`, `ItemIsMenu` sempre `False` e metodo `Activate`). Il menu del
clic destro usa `com.canonical.dbusmenu` (`src/wimm/tray/dbus_menu.py`). Il codice è portato dal
progetto `sysbar` dello stesso autore (`assets/SPECIFICHE.md` §0 punto 9).

La registrazione sul watcher segue il suo ciclo di vita: `Gio.bus_watch_name` ri-registra l'icona
a ogni riapparizione di `org.kde.StatusNotifierWatcher`, cioè dopo un riavvio di GNOME Shell
(`src/wimm/tray/watcher.py`, `src/wimm/tray/tray.py`). Se il watcher non compare entro 10 s
(`WATCHER_ABSENT_MS`), l'app resta utilizzabile e la finestra mostra un banner
(`assets/SPECIFICHE.md` §6.2).

Il processo residente è una `Gio.Application` con `application_id` `io.github.wimm.WhereIsMyMemory`,
istanza unica e `hold()` (`src/wimm/app.py`). GTK e libadwaita si importano alla prima apertura
della finestra, non all'avvio: la specifica prevedeva un'`Adw.Application`, e la deviazione è
registrata in `docs/DEVIATIONS.md`.

Dentro il processo la separazione resta obbligatoria: `core/` puro, `collectors/` senza `gi`,
`service/` unico esecutore di azioni, `ui/` e `tray/` che chiedono piani e non toccano mai
processi o Docker (`assets/SPECIFICHE.md` §6.1, `CLAUDE.md`).

## Consequences

- Lo stato vive in un solo posto: niente API D-Bus fra processi propri, niente servizio systemd,
  niente sincronizzazione (§6.1).
- Il clic sinistro apre la finestra direttamente.
- L'icona dipende da un'implementazione di protocollo mantenuta in casa: i casi non coperti
  (riavvio della shell, etichetta, icona a tema) sono un rischio dichiarato (R2, §18).
- Senza estensione AppIndicator l'icona manca, ma notifiche e lanciatore funzionano (R1, §18).
- Il tetto di memoria di RNF-02 resta raggiungibile a finestra mai aperta; dopo l'apertura il
  consumo va misurato sul display reale (`docs/DEVIATIONS.md`, `docs/PERF.md`).

## Alternatives considered

- **Due processi, icona AppIndicator in GTK3 e finestra in GTK4.** Citata dalla specifica
  (§6.1, "Invece di separare icona e finestra in due processi") e scartata: obbligherebbe a
  un'API fra processi propri e a sincronizzare lo stato.
- **AppIndicator nel processo della finestra.** Impossibile per la coesistenza GTK3/GTK4 (§6.1).
- **`Adw.Application` residente con GTK sempre caricato.** È la lettera di §6.1 e non rispetta
  RNF-02, come misurato in `docs/DEVIATIONS.md`.
