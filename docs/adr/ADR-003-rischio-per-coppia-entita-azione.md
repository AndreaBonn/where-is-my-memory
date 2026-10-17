# ADR-003: il rischio si valuta sulla coppia entità-azione

- Stato: Accettata
- Data: 2026-10-17

## Context

Prima di ogni azione l'utente vede un dialogo la cui severità dipende da cosa si può perdere.
Il rischio non è una proprietà dell'entità: fermare un container Postgres con un volume è
sicuro, perché i dati restano nel volume, mentre rimuovere il volume li distrugge
(`assets/SPECIFICHE.md` §5.3). La specifica chiede anche che un errore in questa parte non chiuda
processi che l'utente non voleva chiudere (§0 punto 1).

## Decision

Il rischio è il risultato di una funzione pura, senza I/O, sulla coppia (bersaglio, azione):
`assess_risk(target, action) -> RiskAssessment`, con livello e conseguenze in italiano
(`src/wimm/core/risk.py`). Il bersaglio è un `RiskTarget` con i soli fatti già calcolati
(categoria, stato di attività, primo piano su un terminale, documenti, nome del processo,
`RepoDigests`, volumi). Un'azione non applicabile al bersaglio solleva `ValueError`
(`ACTIONS_BY_KIND`, `_applicable_actions`).

I livelli sono tre, con la conferma proporzionata (§5.3): `safe` con un clic, `caution` con le
conseguenze in evidenza, `danger` con la digitazione del nome del bersaglio.

La tabella ha due forme nel codice. Le coppie con un esito fisso stanno in
`STATIC_ASSESSMENTS` e i testi in `CONSEQUENCES` (`src/wimm/core/risk_table.py`). Le coppie che
dipendono dallo stato sono rami espliciti: un dev server `idle` è `safe`, `active` o `unknown` è
`caution`; il primo piano su un terminale porta almeno `caution`; `PROCESS_KILL` è `danger` per
le app con documenti e per i database locali, altrimenti `caution`; un'immagine con `RepoDigests`
è `safe`, una costruita in locale è `caution`; `down` con volumi è `danger`
(`_process_assessment`, `_resource_assessment`).

Un gruppo prende il rischio massimo dei suoi membri (`group_primary_action`, §5.3).
Il rischio serviva già in Fase 1 per il badge e per `primary_action.risk`, perciò T-3.1 è stato
anticipato (decisione Q-4 = A, `specs/where-is-my-memory/plan.md`).

## Consequences

- La funzione non fa I/O: ogni coppia si verifica con un `RiskTarget` costruito a mano, senza
  processi né Docker.
- Un'entità ha tanti rischi quante sono le sue azioni, e la UI mostra quello dell'azione scelta.
- Ogni azione nuova richiede una riga di tabella e un testo di conseguenza; senza, `assess_risk`
  non la valuta e la solleva come non applicabile.
- Il livello dipende dai fatti catturati nel bersaglio: una categorizzazione sbagliata (per
  esempio un'app senza `.desktop`) sposta il rischio. Per questo l'esecuzione rivalida il
  bersaglio con un'impronta e controlla protezioni e proprietario
  (`src/wimm/service/executor_checks.py`).
- Il testo per Firefox è stato corretto dopo una misura: SIGTERM non è una chiusura normale e le
  schede tornano dal salvataggio automatico (`docs/DEVIATIONS.md`, T-3.8b).

## Alternatives considered

- **Rischio come proprietà dell'entità** (un livello per container, per processo, per volume).
  La specifica lo esclude con l'esempio Postgres (§5.3); la forma alternativa è dedotta dalla
  frase, non è descritta come opzione in un piano.
- **Un solo livello di conferma per tutte le azioni.** Alternativa dedotta: la specifica distingue
  tre conferme proprio per non trattare allo stesso modo `docker stop` e la rimozione di un volume.
- **Rischio assente in Fase 1.** Era l'opzione B di Q-4 (`specs/where-is-my-memory/plan.md`) e
  azzerava il "recuperabile ora"; scartata a favore dell'anticipo di T-3.1.
