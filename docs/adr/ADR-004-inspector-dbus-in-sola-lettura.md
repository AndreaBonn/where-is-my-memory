# ADR-004: Inspector D-Bus in sola lettura

- Stato: Accettata
- Data: 2026-10-17

## Context

Per la diagnosi e per i test di accettazione serve poter leggere lo stato di un `wimm` in
esecuzione dall'esterno. La DoD 4 del piano, per esempio, interroga `GetSnapshot` per verificare
che un server di prova passi da `active` a `idle` (`specs/where-is-my-memory/plan.md`).
Allo stesso tempo l'applicazione chiude processi e rimuove dati dell'utente: esporre quelle
azioni su un bus renderebbe ogni client di sessione un possibile esecutore (`assets/SPECIFICHE.md`
§6.3, §8).

## Decision

L'applicazione espone sul bus di sessione l'interfaccia `io.github.wimm.Inspector1`
all'oggetto `/io/github/wimm/Inspector`, con due metodi e una proprietà, tutti di lettura
(`assets/SPECIFICHE.md` §6.3, `data/dbus/io.github.wimm.Inspector1.xml`):

- `GetSnapshot() -> s`, l'ultimo snapshot in JSON;
- `GetDiskReport() -> s`, l'ultimo report disco in JSON;
- `Version` (proprietà `s`).

Nel codice la proprietà non è scrivibile (`set_property_closure=None`) e il gestore risponde solo
a questi due metodi (`src/wimm/service/inspector_dbus.py`). Prima del primo campionamento
`GetSnapshot` risponde con l'errore `io.github.wimm.Error.NotReady`, mentre `GetDiskReport`
restituisce `{"schema":2,"available":false}` (lo schema è la `SCHEMA_VERSION` corrente).

Nessuna azione è esposta: chi può eseguire un piano è solo la UI, dopo la conferma
dell'utente, tramite `AppService.plan` e `AppService.execute` (§6.3). L'esecuzione resta in un
solo modulo, `service/executor.py`, e controlla proprietario, categoria protetta e impronta del
bersaglio (RNF-06, `src/wimm/service/executor_checks.py`).

Lo snapshot esposto è redatto. `cmdline` può contenere token passati come argomenti, quindi
i valori delle opzioni lunghe e degli assegnamenti il cui nome finisce in key, token, password
o secret (`--api-token x`, `DB_PASSWORD=x`), le intestazioni `Authorization` e `Cookie` e le
password negli URL sono sostituiti nel JSON D-Bus (`src/wimm/redaction.py`, `redact_cmdline`,
`snapshot_for_dbus`) e nei log. Le forme brevi (`-p segreto`) restano visibili: la § 4 della
baseline di sicurezza (`docs/security/T-6.1-security-baseline.md`) lo annota come P2, perché lo
stesso utente legge comunque `/proc/<pid>/cmdline`, mentre la finestra mostra la riga completa solo
espandendo il membro (decisione Q-14 = A, `specs/where-is-my-memory/plan.md`; R11, §18).

## Consequences

- Un client D-Bus può osservare lo stato ma non cambiarlo: il peggio che può fare è leggere dati
  già redatti, sul bus di sessione dell'utente (§6.3).
- I test di accettazione leggono lo stato reale con `GetSnapshot` invece di inferirlo dalla UI.
- Il JSON dell'Inspector differisce da quello interno proprio nei campi `cmdline`.
- L'XML di introspezione è un file installato dal pacchetto in
  `/usr/share/where-is-my-memory/dbus/` (`docs/DEVIATIONS.md`, sezione "Nomi dei pacchetti").
- Un'azione da riga di comando o da altro strumento richiederebbe una decisione nuova e una
  nuova ADR: l'interfaccia è `Inspector1` e un'azione sarebbe una versione diversa.

## Alternatives considered

- **Interfaccia D-Bus con metodi di azione** (per esempio un `Execute`). Esclusa in modo
  esplicito da §6.3 ("Nessuna azione è esposta su D-Bus").
- **Redazione solo nei log, con il JSON D-Bus invariato.** Era l'opzione B di Q-14
  (`specs/where-is-my-memory/plan.md`) e non è stata scelta.
- **Nessuna interfaccia D-Bus, test dalla sola UI.** Alternativa dedotta: la specifica la
  motiva con diagnosi e accettazione (§6.3), senza discuterne l'assenza.
