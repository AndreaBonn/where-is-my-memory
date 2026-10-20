[English](SECURITY.md) | **Italiano**

# Politica di sicurezza

## Versioni supportate

| Versione | Supportata |
|---|---|
| 1.1.x | Sì |
| < 1.1 | No, aggiorna all'ultima release |

## Segnalare una vulnerabilità

Segnala le vulnerabilità in privato tramite
[GitHub Security Advisories](https://github.com/AndreaBonn/where-is-my-memory/security/advisories/new),
non con una issue pubblica.

Includi:

- una descrizione della vulnerabilità e la versione coinvolta
- i passi per riprodurla
- il comportamento atteso e quello osservato
- l'impatto: cosa potrebbe ottenere un attaccante o un file locale malevolo

<!-- TODO: aggiungere i tempi di risposta che ci si impegna a rispettare, se ce ne sono -->
Prima esce la correzione; l'advisory diventa pubblico dopo la release.

## Misure di sicurezza implementate

L'app gira con il tuo utente e agisce solo sui tuoi processi, container e file. Le misure
qui sotto sono nel codice:

- **Nessuna elevazione di privilegi**: nessun `sudo`, `pkexec` o `setcap` nei sorgenti, nel
  packaging o nei file di dati. Ogni comando esterno è una lista di argomenti senza shell e
  con un timeout (`src/wimm/service/fs_controls.py:75`, `src/wimm/service/compose.py:129`,
  `src/wimm/collectors/foreground.py:112`).
- **Conferma imposta dal servizio**: un'azione Pericolo parte solo se la frase scritta
  coincide esattamente; il controllo è nel servizio, non solo nel dialogo
  (`src/wimm/service/plan_registry.py:31`).
- **Processi fermati, non uccisi**: l'esecutore manda `SIGTERM` all'albero dei processi,
  mai un `SIGKILL` automatico (`src/wimm/service/executor_process.py:23`).
- **Cancellazione sicura sul disco**: la rimozione procede tramite descrittori di cartella
  aperti con `O_NOFOLLOW`, quindi un percorso sostituito con un collegamento mentre l'app
  lavora non viene seguito (`src/wimm/service/safe_tree.py:23`). Prima di rimuovere, la
  cartella viene ricontrollata per inode, dispositivo e percorso reale
  (`src/wimm/service/executor_disk_fs.py:65`).
- **Dati Docker conservati**: rimuovere un container non rimuove mai i suoi volumi
  (`src/wimm/service/executor_docker.py:55`).
- **Ispettore D-Bus in sola lettura**: l'interfaccia D-Bus espone dati e non ha proprietà
  scrivibili (`src/wimm/service/inspector_dbus.py:46`); le righe di comando vengono
  oscurate prima di essere esportate (`src/wimm/snapshot_redaction.py:14`).
- **File privati**: configurazione, stato e log sono scritti con permessi `0600` in
  cartelle con permessi `0700`, con creazione esclusiva, `O_NOFOLLOW` e rinomina atomica
  (`src/wimm/paths.py:7`, `src/wimm/paths.py:62`, `src/wimm/paths.py:79`).
- **Controlli in CI**: bandit sui sorgenti e pip-audit sulle dipendenze di sviluppo
  bloccate girano a ogni push (`Makefile`, target `audit`; `.github/workflows/ci.yml`).

Le note della revisione interna, con i punti di irrobustimento aperti sotto la soglia di
sfruttabilità, sono in
[docs/security/T-6.1-security-baseline.md](docs/security/T-6.1-security-baseline.md).

## Fuori ambito

- Attacchi che richiedono codice già in esecuzione con il tuo utente: quel codice può
  leggere `/proc` e agire sui tuoi processi anche senza questa app.
- Vulnerabilità di GTK, libadwaita, psutil, SDK di Docker o altre librerie di sistema:
  vanno segnalate ai rispettivi maintainer o a Ubuntu.
- Perdita di dati dopo che hai confermato un'azione il cui dialogo descriveva quella
  perdita.

---

[Torna al README](README.it.md)
