# ADR-005: JSON per configurazione e stato

- Stato: Accettata
- Data: 2026-10-17

## Context

L'applicazione legge e scrive preferenze, stato persistente (ultimi istanti di attività per
entità e gruppo, silenzi, gruppi ignorati, episodi già notificati) e una cache delle dimensioni
delle cartelle (`assets/SPECIFICHE.md` §11). Il riavvio non deve far perdere i tempi di inattività
(RNF-11) e un file corrotto non deve fermare l'avvio (RNF-10).

## Decision

Tre file JSON nelle directory XDG dell'utente, risolte con `GLib.get_user_config_dir()`,
`get_user_state_dir()` e `get_user_cache_dir()` sotto la cartella `where-is-my-memory`
(`src/wimm/paths.py`, `default_user_paths`):

| File | Contenuto | Codice |
|---|---|---|
| `config.json` | preferenze (RF-50) | `src/wimm/config.py` |
| `state.json` | stato persistente, con `version` | `src/wimm/service/state_store.py` |
| `disk-cache.json` | dimensioni e mtime di cartelle | `src/wimm/core/constants.py` (`DISK_CACHE_FILENAME`) |

La scrittura è atomica e privata: file temporaneo accanto alla destinazione con `O_EXCL` e
`O_NOFOLLOW`, permessi `0600`, `fsync`, `os.replace` e `fsync` della directory; le cartelle sono
`0700` e un symlink come bersaglio è rifiutato (`write_private_atomic`, `ensure_private_dir`).
Lo stato si scrive ogni 300 s (`STATE_SAVE_INTERVAL_S`) e alla chiusura (`StateSaver`).

La lettura tollera i dati rovinati. `load_config` torna ai default se il file manca o non è un
oggetto JSON, e `parse_config` scarta le chiavi sconosciute con un `WARNING` e tiene il default
del solo campo invalido. `load_state` restituisce uno stato vuoto se il file è troncato o ha una
`version` diversa, e scarta le singole voci non valide. Una modifica dalla finestra tiene invece
il valore in uso sul campo invalido (`docs/DEVIATIONS.md`, sezione "Preferenze aggiornate dalla finestra").

## Consequences

- I file sono leggibili e correggibili a mano con un editor, e si leggono e scrivono con la sola
  libreria standard.
- Il formato non ha commenti: la documentazione delle chiavi sta in `assets/SPECIFICHE.md` §11.
- Una scrittura interrotta non lascia un file a metà; resta il vecchio contenuto.
- L'evoluzione dello schema passa dal campo `version` di `state.json`; una versione diversa fa
  perdere lo stato, non l'avvio.
- La perdita di stato dopo un crash può arrivare a 5 minuti di dati, l'intervallo di salvataggio.

## Alternatives considered

- **TOML.** Valutata dalla specifica (§11) e scartata: la libreria standard `tomllib` sa solo
  leggere, mentre l'applicazione deve anche scrivere il file.
- **GSettings/dconf.** Alternativa dedotta, non discussa in specifica o piano: richiederebbe uno
  schema installato e renderebbe i valori meno ispezionabili.
- **SQLite per lo stato.** Alternativa dedotta, non discussa in specifica o piano: per tre piccoli
  documenti senza query la specifica non vede un bisogno che giustifichi un database.
