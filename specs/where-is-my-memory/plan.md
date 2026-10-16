# where-is-my-memory: piano di implementazione

Versione 2.0, 2026-10-16. Rigenerato da zero su `assets/SPECIFICHE.md` v1.0, che prevale su questo
file. Requisiti tracciati in `spec.md` (R1-R68), task in `tasks.md` (id `T-x.y` della §16).

## Obiettivo

Sulla macchina dell'utente (Ubuntu 24.04, GNOME X11) il `.deb` installa `wimm`, che parte al login
nella barra in alto, mostra per gruppo e categoria cosa occupa RAM e disco, distingue in uso da
inattivo col motivo misurato, permette di fermare o pulire con anteprima e conferma proporzionata al
rischio, e notifica le inattività lunghe e la pressione su RAM e disco. Nessuna azione automatica,
nessun privilegio di root.

## Definition of Done

Vale la DoD §17 per intero (R42-R55 in `spec.md`), più:

- [ ] Ogni R1-R68 di `spec.md` ha un task chiuso col proprio `verify:` osservato (auto) o spuntato
  nella Checklist runtime manuale (manuale-utente).
- [ ] Le 4 premesse [DA VERIFICARE] hanno una voce in `docs/DEVIATIONS.md` con evidenza ed esito.
- [ ] Workflow CI presente e verde al primo run dopo il push (che fa l'utente, D-U2).
- [ ] Fase 6 chiusa: security baseline senza finding bloccanti, README per utente finale, ADR in
  `docs/adr/`, `make setup && make lint && make test` verdi da clone pulito, Delivery Report.
- [ ] Nessun test ha agito su processi, container, immagini, cache o file non creati dal test (R56).

Esempio concreto (DoD 4): Given `python3 -m http.server 8765` lanciato in `~/tmp/demo` con un
`pyproject.toml`, When si fa `curl localhost:8765` ogni 10 s per 2 min, Then `GetSnapshot` riporta
un gruppo `demo` categoria `DEV_SERVER` con `activity.state == "active"`; When le richieste si fermano
per `activity_window_s` (20 s nel test), Then `state == "idle"` e `reason` contiene "nessuna
connessione in ingresso" e la CPU media misurata.

## Assunzioni

- A1. Runtime: `/usr/bin/python3` 3.12.3, psutil 5.9.8, docker 5.0.3, Gtk 4.14, Adw 1.5 da apt.
  BASIS: measured (Research dell'orchestratore + `apt-cache policy` di questo turno).
- A2. `gir1.2-gtk-4.0` esiste (installato 4.14.5); `gnome-shell-extension-appindicator` esiste
  (58-1ubuntu24.04.1); `gnome-shell-extension-ubuntu-appindicators` NON risulta come pacchetto;
  `docker-ce-cli` installato, `docker.io` no. BASIS: measured. T-2.1 chiude formalmente la premessa
  e corregge la riga `Recommends` (alternativa senza il nome inesistente).
- A3. Il tray di sysbar si porta riscrivendo dove serve: `menu_builder.py` dipende da moduli sysbar
  (`core.i18n`, `services.scenes`) e non si porta; sysbar ha deroghe ai limiti (allowlist in
  `tests/test_source_limits.py` su `_handle_method`, `_get_property`, `build_menu_items`), qui le
  firme dettate da Gio restano in un'allowlist nominata, le funzioni lunghe si spezzano. Sysbar
  pubblica `XAyatanaLabelGuide` vuota e non ha `watch_name`. BASIS: measured (lettura dei file).
- A4. La lettura di file `.desktop` e la ricerca della radice di progetto (marker `.git`,
  `pyproject.toml`...) sono I/O: vivono in `collectors/desktop_entries.py` e
  `collectors/project_roots.py` (file non elencati in §14), e il core riceve i valori già risolti
  nei `RawProcess`. Scelta implementativa, nessun impatto architetturale.
- A5. Copertura >= 90% su `core/` imposta nel comando di `make test`
  (`--cov=src/wimm/core --cov-fail-under=90`), non in `addopts`, così gira anche in CI.
- A6. La CI gira solo dopo un push che fa l'utente; prima del push si verifica con `yamllint` e un
  controllo dei pin a SHA (`actionlint` e `act` non sono installati, BASIS: measured).
- A7. `lintian` assente sull'host (BASIS: measured): `scripts/test_deb.sh` lo installa ed esegue
  nel container `ubuntu:24.04`, così R64 non dipende da un `sudo apt install` sull'host.
- A8. `a11y-gate` lavora su HTML: non si applica a una UI GTK. Al suo posto: test `ui` che verifica
  nome accessibile e tooltip su ogni pulsante solo icona, click-through da tastiera
  (manuale-utente), render a 360 e 1280 px. Va dichiarato `N/A` col motivo nella riga `CHECKS:`.
- A9. T-0.1, stub di tipo: `types-psutil` recenti seguono psutil 7 e `types-docker` segue docker 7
  (UNVERIFIED, da training data). `pygobject-stubs` genera di default stub GTK3 e per GTK4 vuole
  `config-settings` (UNVERIFIED). Ripiego dichiarato in T-0.1a.
- A10. Fasi 2-6 "si provano sull'installazione reale" (§16): ogni reinstallazione del `.deb` sulla
  macchina richiede `sudo apt install ./dist/*.deb`, quindi è un passo manuale-utente a fine fase.
- A11. Bersagli Docker dei test: immagine `alpine` (pull consentito, è creata dal test), label
  `wimm.test=1`, nomi con prefisso `wimm-test-`, rimozione in `finally`.

## Domande aperte (non risolte in silenzio)

Default applicato se l'utente non risponde. Le Q bloccanti per una fase vanno chiuse prima di essa.

- **Q-1 [bloccante Fase 1, T-1.4b]** §5.1 regola 5 assegna `TERMINAL` "per antenato": ogni
  processo lanciato da gnome-terminal ha `gnome-terminal-server` come antenato, quindi regola 5
  (prima di AI_CLI e DEV_*) li renderebbe tutti `TERMINAL`. A) l'ereditarietà per antenato vale solo
  per BROWSER e DESKTOP_APP; TERMINAL solo per cgroup/nome proprio (default). B) l'ereditarietà si
  ferma al primo scope `vte-spawn-*` (i figli di emulatori non-VTE restano TERMINAL).
- **Q-2 [Fase 1]** Un dev server lanciato nel terminale integrato di VS Code è discendente di
  `code`, quindi per la regola degli helper (§5.1) diventa `DESKTOP_APP` e non compare come dev
  server. A) lettera della spec, limite documentato in README FAQ (default, prevale la spec).
  B) un processo che ha una shell fra sé e l'editor è "lanciato da terminale" (DEV_*).
- **Q-3 [Fase 1]** Le shell in `vte-spawn` "fanno parte del gruppo della scheda" ma §5.5 non definisce
  un gruppo per scheda. A) le shell vanno nel gruppo `TERMINAL` di gnome-terminal-server senza azioni
  proprie (default). B) le shell vanno nel gruppo di progetto della loro `cwd`, senza azioni.
- **Q-4 [bloccante Fase 1]** RF-01, RF-04, lo schema `primary_action.risk` e il badge di T-1.9
  servono già in Fase 1, ma `core/risk.py` è T-3.1. A) T-3.1 si esegue in Fase 1, prima di T-1.8,
  con id invariato (default). B) in Fase 1 rischio assente e "recuperabile ora" a zero.
- **Q-5 [Fase 3]** §8.3 permette di togliere voci dal dialogo multiplo, ma il `Plan` è immutabile e
  `ActionRequest(kind, group_id, target_id)` non ha esclusioni. A) `ActionRequest` riceve
  `excluded_ids: tuple[str, ...]` e ogni toggle chiede un nuovo piano (default). B) niente toggle.
- **Q-6 [Fase 1]** `reclaimable_now.disk` sta nello snapshot, ma il disco arriva da un report su un
  ciclo diverso. A) somma delle voci `safe` dell'ultimo report disco, `0` prima della prima scansione
  (Fase 1-4: sempre `0`) (default). B) campo `null` finché non c'è un report.
- **Q-7 [CP-0]** "Lo skeleton parte" dopo la Fase 0, ma `app.py` arriva in T-1.8. A) il checkpoint è
  `make setup && make lint && make test` verdi da zero, test versioni incluso (default). B) T-0.1
  anticipa uno stub `wimm --version`.
- **Q-8 [Fase 5]** `prune_builds()` non accetta filtri, e prune immagini/container, pulizia cache
  uv/npm e cestino agiscono sulle risorse reali dell'utente, in conflitto con §0.5. A) test con fake
  e con `HOME`/`UV_CACHE_DIR`/`npm_config_cache` in tmpdir; esecuzione reale delle prune solo
  manuale-utente dall'app installata (DoD 11) (default). B) prune di integrazione con filtro label
  `wimm.test=1`: testa una chiamata diversa da quella di produzione.
- **Q-9 [Fase 3, T-3.8b]** Verificare che Firefox con SIGTERM conservi la sessione chiude un processo
  dell'utente, vietato da §0.5. A) istanza Firefox lanciata dal test con profilo dedicato in
  `~/snap/firefox/common/wimm-test-profile` (lo snap non vede la `/tmp` dell'host), 2 schede,
  `browser.startup.page=3`, SIGTERM, rilancio, lettura di `sessionstore` (default). B) l'utente chiude
  il proprio Firefox da wimm (manuale-utente).
- **Q-10 [Fase 4]** RF-31 fissa la notifica di pressione al 10%, §11 ha `pressure_critical_pct=10`.
  A) la notifica usa `pressure_critical_pct` (default). B) soglia fissa al 10%.
- **Q-11 [Fase 5]** `~/.cache/thumbnails` è in §7.6 (safe) ma non in RF-22. A) azione `cache_clean`
  anche per le miniature (default). B) solo mostrata.
- **Q-12 [Fase 1]** Processi dell'utente in `user-1000.slice/session-N.scope` (SSH, tmux avviato lì)
  sono fuori da `user@1000.service`, quindi `SYSTEM` e protetti per la regola 2. A) lettera della spec,
  conservativo, documentato in FAQ (default). B) `session-N.scope` dell'utente trattato come utente.
- **Q-13 [Fase 5, da security review S1]** §8.4 esegue `images.prune`, `prune_builds` e il prune dei
  container fermi sull'insieme presente all'esecuzione: ciò che compare fra piano ed esecuzione
  (finestra di 120 s) viene rimosso senza essere stato mostrato. A) le azioni di massa su immagini e
  container diventano rimozioni per id lette al piano e rivalidate una per una, deviazione annotata
  in `docs/DEVIATIONS.md` (default); `builder_prune` resta prune perché la build cache non ha id
  elencabili via SDK 5.0.3. B) lettera della spec.
- **Q-14 [Fase 1, da security review S7]** `GetSnapshot` (§6.5) espone `cmdline` complete, che
  possono contenere token. A) redazione di `--token`, `--password`, `--secret`, `*KEY=`, `*TOKEN=`
  nel JSON D-Bus e nei log a ogni livello; la UI mostra la cmdline completa solo espandendo il
  membro, come da R11 (default). B) solo i log, JSON invariato.

## Approccio

- Ordine §16, con due spostamenti di dipendenza senza rinumerare: T-3.1 in Fase 1 (Q-4) e T-0.3 (CI,
  D-U3) in Fase 0. Fase 6 (hardening) aggiunta in coda con id `T-6.x`.
- Functional core, imperative shell: `core/` puro e test-first (copertura >= 90%); `collectors/`
  con dipendenze iniettate per costruttore (fake di psutil e del client Docker); `service/` unico
  esecutore; `ui/` e `tray/` chiedono piani e confermano.
- Contratti fissati presto, prima dei task che li consumano: `model.py` (T-0.2a) è il contratto di
  tutti; `ProcessControl`/`DockerControl` (`Protocol`, T-3.3a) di executor e test; `build_menu` e
  `viewmodel` sono puri e testabili senza display.
- Sicurezza in un punto: `executor.py` ricontrolla protezione, uid, impronta e frase anche su piani
  costruiti a mano (R36, R50), con caso positivo appaiato a ogni rifiuto.
- Ogni premessa [DA VERIFICARE] ha un task che la chiude e un ripiego §18 già scelto.
- Delega (D-U5): core e logica a `tdd-guide`, collectors e service a `senior-backend`, packaging e
  CI a `devops-engineer`, tutti con `[DELEGATE-CODEX]` e riga `SCOPE:`; `ui/` e `tray/` a
  `fullstack-developer` in-house. Lotti da 2-4 task (tabella in `tasks.md`). Restano in-house la
  verifica delle premesse esplorative (T-3.8b) e le misure RNF (T-6.5).
- Ogni lotto: commit atomici Conventional Commits su `main` (D-U2), `code-reviewer` sull'output
  delegato prima del commit, nessun push.

## Fasi (ognuna lascia il sistema usabile)

| Fase | Task | Stato usabile a fine fase |
|---|---|---|
| 0 Scheletro | 5 (T-0.1a..T-0.3) | `make setup/lint/test` verdi da zero, versioni di sistema nel venv, modello e JSON con round-trip, CI pronta al push. **CP-0**: checkpoint umano "lo skeleton parte" |
| 1 Sola visione | 26 (T-1.1a..T-1.11, più T-3.1a/b) | `make run` mostra icona, menu, finestra con gruppi reali, vista Sistema; Inspector D-Bus risponde. Nessuna azione |
| 2 Pacchetto | 4 (T-2.1..T-2.4) | `.deb` costruito e testato in container; dopo l'installazione (manuale-utente) parte al login |
| 3 Azioni | 11 (T-3.2a..T-3.8b) | Fermare processi, container e progetti compose con anteprima e conferma; esito e liberato misurato |
| 4 Notifiche | 7 (T-4.1..T-4.4b) | Notifiche idle e pressione, silenzi, gruppi ignorati, persistenza, preferenze |
| 5 Disco | 12 (T-5.1a..T-5.5b) | Vista Disco con pulizie; primo piano X11 per browser e app |
| 6 Hardening | 6 (T-6.1..T-6.6) | Security baseline, README, ADR, clean clone, misure RNF, Delivery Report |

Totale 71 task. Stima: 8-11 giorni di sviluppo (task da 20-45 min effettivi con review e commit),
più buffer 20% per imprevisti e primo pacchetto = **10-13 giorni**. Il primo di ogni specie (primo
collector, primo test D-Bus, primo dialogo) pesa di più: T-1.2, T-1.8c, T-1.10a, T-3.7a. Le
verifiche manuali dell'utente (~2-3 h in tutto) sono fuori da questa stima.

Gate di fine fase (§0.2): `make lint && make test` verdi, `make test-all` verde (integrazione,
D-Bus, UI), voci `manuale-utente` della fase spuntate, nessuna Q bloccante aperta per la fase dopo.

## Checklist runtime manuale (manuale-utente)

Raccolte qui perché nessun agent può eseguirle: logout, riavvio della shell, `sudo`, clic reali,
chiusura di app dell'utente, azioni distruttive su risorse reali.

| Id | Quando | Azione dell'utente | Esito atteso | Task / R |
|---|---|---|---|---|
| M-1 | CP-0 | Approvare lo skeleton (`make setup && make lint && make test` da zero) | verdi | T-0.1a..T-0.3 |
| M-2 | Fase 1 | `make run`: clic sinistro, clic destro, gruppo del menu, chiusura finestra, filtri | apre/porta in primo piano, menu RF-42, gruppo espanso, processo vivo | T-1.9b..T-1.10b / R27, R29 |
| M-3 | Fase 1 | `Alt+F2`, `r` (riavvio GNOME Shell X11) con l'app in esecuzione | icona ricompare senza riavviare l'app | T-1.11 / R53 |
| M-4 | Fase 1 | Click-through da tastiera (Tab, Ctrl+F, F5, Ctrl+,) e finestra a 360 px | tutto raggiungibile, nessuna sovrapposizione | T-1.9d / A8 |
| M-5 | Fase 2 e fine di ogni fase successiva | `sudo apt install ./dist/where-is-my-memory_<ver>_all.deb` | installato | T-2.3 / A10 |
| M-6 | Fase 2 | Logout e login | icona nella barra, `pgrep -f /usr/bin/wimm` trova il processo, finestra nascosta | T-2.2 / R28, R42 |
| M-7 | Fase 2 | Seguire solo il README su una macchina o un utente che non conosce il progetto | pannello trovato | T-2.4 |
| M-8 | Fase 3 | Click-through dei dialoghi safe/caution/danger su `http.server` e compose di test | anteprima, esito, liberato; danger disabilitato finché il nome non coincide | T-3.7a, T-3.7b / R48, R49 |
| M-9 | Fase 3 | Solo se Q-9 = B: chiudere il proprio Firefox da wimm e riaprirlo | sessione conservata o no, annotato | T-3.8b |
| M-10 | Fase 4 | `notify_after_s=60` con server di test inattivo: clic su "Apri" e su "Silenzia 24 h" | finestra sul gruppo; nessuna nuova notifica | T-4.2b / R51 |
| M-11 | Fase 4 | Riavvio dell'app (Esci e rilancio) | "inattivo da" invariato | T-4.3a / R11 |
| M-12 | Fase 4 | Preferenze: valore fuori intervallo, poi valido | errore sul campo; effetto al ciclo successivo | T-4.4b / R30 |
| M-13 | Fase 5 | Click-through della vista Disco; "Svuota build cache" reale con conferma dell'utente | liberato entro 10% dell'indicato | T-5.4b / R52 |
| M-14 | Fase 5 | Tenere Slack o un'app di prova in background oltre la finestra | app `idle` | T-5.5b |
| M-15 | Fase 6 | Clone pulito su altra cartella e misure RNF (1 h di esecuzione) | verdi, numeri nel report | T-6.4, T-6.5 |
| M-16 | Fase 6 | Percorso completo della DoD §17 sull'installato | 14 voci spuntate | T-6.6 |

## Premesse [DA VERIFICARE]

| Premessa | Task che la chiude | Esito atteso | Ripiego se smentita |
|---|---|---|---|
| Stub di tipo compatibili con psutil 5.9 e docker 5.0 (§14.1) | T-0.1a | mypy verde senza `ignore` | pin `types-psutil` 5.9.x; per docker nessuno stub: override `ignore_missing_imports` limitato a `docker.*` e mypy normale (non strict) su `collectors/`; `PYGOBJECT_STUB_CONFIG=Gtk4,Gdk4` per gli stub GTK4. Annotato in DEVIATIONS |
| Nomi di `gir1.2-gtk-4.0` e dei `Recommends` (§12.1) | T-2.1 | `apt-cache policy` li trova | già parzialmente smentita (A2): si tolgono i nomi inesistenti, si annota |
| `docker compose -p <nome> down` senza file compose (§7.3) | T-3.6 | `down` rimuove i container del progetto di test | SDK per label + `networks.prune(filters=label)` (R7 §18) |
| Firefox snap con SIGTERM conserva la sessione (§8.4) | T-3.8b | schede ripristinate al rilancio | conseguenza aggiornata e "Chiudi browser" a `danger` con frase "Firefox" (R8 §18) |

Le premesse misurate ([MISURATO]) non si riverificano, salvo il ciclo < 1,5 s: se T-1.2b o T-1.8a lo
superano, si applica R3 §18 (memory_full_info solo su RSS > 30 MB, gli altri ogni 5 cicli).

## Fuori scope

- Per-tab del browser (N5), Wayland per il primo piano (N4), grafici storici (N3).
- Push, release su GitHub, pubblicazione del `.deb`: il push lo fa l'utente (D-U2).
- Esclusione degli health check dal calcolo di attività (§7.2, rinviata dalla spec).
- Modifiche a `sysbar` (la correzione del watcher si segnala nel report, non si applica lì).
- Installazione di pacchetti sull'host (`lintian`, `actionlint`): si usano container o si salta
  dichiarandolo.

## Rischi e mitigazioni

- **Poiché** la regola 5 di §5.1 classifica TERMINAL per antenato, **ogni** dev server da terminale
  potrebbe risultare TERMINAL, **il che** svuoterebbe il prodotto del suo caso d'uso principale
  (rework 0,5-1 g su categorize e grouping) → Q-1 chiusa prima di T-1.4b; test con l'albero reale
  gnome-terminal-server → zsh → uvicorn.
- **Poiché** il venv ha `--system-site-packages`, una dipendenza dev che tira psutil o docker da PyPI
  **farebbe** girare i test su versioni diverse dal `.deb` → test versioni di T-0.1a in ogni run,
  `dependencies = []`.
- **Poiché** i test di integrazione toccano Docker e processi reali, un `finally` mancato o un filtro
  sbagliato **potrebbe** agire su risorse dell'utente (§0.5) → solo label `wimm.test=1` e PID creati
  dal test; review dedicata in T-6.1; prune reali solo manuale-utente (Q-8).
- **Poiché** il tray portato non ha mai gestito il riavvio della shell né le icone in dev (non
  installate nel tema), l'icona **potrebbe** sparire o essere vuota in `make run` → T-1.11 con watcher
  finto; proprietà `IconThemePath` puntata a `data/icons` quando si esegue dal sorgente.
- **Poiché** GTK4 non ha un harness UI headless robusto, i test `ui` **coprono** solo costruzione e
  conteggi di widget → viewmodel puro con la logica, click-through manuale M-2, M-8, M-13.
- **Poiché** gli stub GTK4 e docker potrebbero non combaciare (A9), mypy **potrebbe** bloccare la
  Fase 0 per mezza giornata → ripiego già scelto nella tabella premesse.
- **Poiché** la CI gira su un runner che non abbiamo provato, il primo push **potrebbe** essere rosso
  per differenze apt (versioni noble-updates) → test versioni con messaggio esplicito; il rosso del
  primo run è atteso come possibile e si corregge come T-0.3.
- **Poiché** il ciclo misurato è 0,58 s su 841 processi e i container aggiungono letture cgroup,
  con 900 processi **potrebbe** superare 1,5 s → log DEBUG della durata da T-1.8a, ripiego R3 §18.
- **Poiché** i 71 task sono delegati in ~25 lotti, il contesto passato agli agent **potrebbe** perdere
  vincoli della spec → ogni prompt porta id task, righe di `tasks.md`, sezioni della spec citate e
  `SCOPE:`; `code-reviewer` su ogni lotto.

## Criteri di successo

- `make lint && make test && make test-all` verdi; `pytest --cov` riporta >= 90% su `src/wimm/core`.
- `gdbus call ... Inspector1.GetSnapshot | jq` soddisfa i controlli di DoD 2-6 sulla macchina reale.
- Checklist runtime manuale M-1..M-16 spuntata dall'utente.
- `docs/DEVIATIONS.md` con le 4 premesse chiuse; `docs/REPORT_ATTIVITA.md` con i numeri RNF-01/02/03.
- Nessun processo, container, immagine o file dell'utente toccato da un test (review T-6.1).

## Rilievi degli specialisti integrati

Review del piano del 2026-10-16: `security-reviewer` (S1-S7, nessun P0) e `type-design-analyzer`
(T1-T12). Ogni rilievo diventa un criterio di verify del task indicato; S1 e S7 dipendono da Q-13 e Q-14.

| Rilievo | Task | Criterio aggiunto |
|---|---|---|
| S2 P1 `rmtree` attraversa mount e bind-mount | T-5.3c | walk con `dir_fd` e `O_NOFOLLOW`, sottodirectory con `st_dev` diverso dalla radice saltate e registrate; test con fake `st_dev` diverso: il contenuto montato sopravvive |
| S3 P1 test che toccano cestino e config reali | T-0.1b, T-5.3c | fixture autouse che porta HOME e tutte le `XDG_*` in tmpdir e fallisce se un path dell'executor esce dalla tmpdir; test con un cestino "esca" fuori dalla tmpdir che resta intatto |
| S4 P1 nome progetto compose da label | T-3.6 | nome validato con `^[a-z0-9][a-z0-9_-]*$`, passato come `--project-name=<nome>`; insieme di container e volumi rivalidato all'esecuzione; test con nome `-v` e `a;b` -> `InvalidRequest` |
| S5 P2 discendenti non rivalidati | T-3.3a | stesse validazioni 8.2 su ogni discendente prima del segnale, protetti saltati con esito registrato; test con figlio `gpg-agent` che non riceve SIGTERM e figlio normale che lo riceve |
| S6 P2 TOCTOU su PID e attività | T-3.3a, T-3.5 | segnali solo tramite `psutil.Process` (ricontrolla il riuso del PID); attività e `tpgid` riletti all'esecuzione, rischio salito -> `TargetChanged`; test con fake che diventa `active` dopo il piano |
| S7 P2 permessi dei file utente | T-1.8b, T-4.3 | directory 0700, file 0600 creati con modo esplicito; test sui permessi di `state.json` e `wimm.log` |
| S7 P2 superficie D-Bus | T-1.8c | test che `org.gtk.Actions` non espone azioni che eseguono piani |
| Hardening | T-4.4a, T-5.3c | `devdirs_roots` con `realpath` dentro `realpath(HOME)`; `devdir_delete` rifiutato se un processo ha la `cwd` nel progetto |
| T1 `ActionRequest` | T-0.2a | tabella `ActionKind -> TargetShape` (NONE, GROUP, TARGET) e `__post_init__` che alza `InvalidRequest` |
| T2 id | T-0.2a | `NewType` `GroupId`, `PlanId`, `TargetId` |
| T3 `Plan` | T-0.2a | `risk` come `@property` = massimo degli step; `confirm_phrase` valorizzata se e solo se `DANGER`; `steps` non vuoto; datetime con fuso |
| T4 `Risk` | T-0.2a | `IntEnum` SAFE < CAUTION < DANGER, serializzato come `.name.lower()`; test `max([SAFE, CAUTION]) is CAUTION` |
| T5 membri | T-0.2a, T-0.2b | `ContainerMember \| ProcessMember` con discriminatore `kind`; `PROJECT` non ammesso come categoria di processo |
| T6 protezione | T-0.2a | `protection` derivata dalla categoria; protetto con azioni -> errore (test) |
| T7 attività | T-0.2a | `since` obbligatorio e con fuso per `ACTIVE` e `IDLE`, `None` solo per `UNKNOWN`; `reason` non vuota |
| T8 memoria | T-0.2a | byte interi >= 0, nessun tetto `reclaimable <= used` (USS+swap può superare PSS); nessun `list`/`dict`/`set` nei campi frozen |
| T9 snapshot | T-0.2a | `Pressure` Enum, `SCHEMA_VERSION = 1`, `DockerStatus` con `available=False` se e solo se `error` valorizzato, id di gruppo univoci |
| T10 config | T-0.2a, T-4.4a | intervalli rivalidati in `Config.__post_init__`; vincolo `pressure_critical_pct < pressure_warning_pct`; lista protetta = default \| extra |
| T11 round-trip | T-0.2b | decoder per union con dispatch su `kind`, niente `asdict`; test parametrici su gruppo solo container, solo processi, misto, `since=None`, fusi diversi, enum fuori vocabolario e `schema != 1` rifiutati |
| T12 impronte | T-0.2a | `Fingerprint` come union di dataclass per bersaglio (processo, container, compose, immagine, volume, cartella), non `str` |

## Decisioni prese (2026-10-16)

L'utente ha delegato Q-1, Q-4 e Q-7 all'orchestratore e ha accettato i default per tutte le altre.

- **Q-1 = A.** Nella regola 5 di §5.1 l'ereditarietà per antenato vale solo per `BROWSER` e
  `DESKTOP_APP`. `TERMINAL` si assegna solo per scope, cioè al processo `gnome-terminal-server`
  stesso. Perché: lo scope `vte-spawn-*` è il segnale che la spec usa per dire "lanciato da
  terminale" (regola 8). Ereditare `TERMINAL` assorbirebbe ogni dev server e ogni CLI dentro il
  terminale, svuotando RF-03, RF-04 e la DoD 4. La deviazione va annotata in `docs/DEVIATIONS.md`
  (T-1.4b). Test: l'albero reale `gnome-terminal-server -> zsh -> uvicorn` (verificato: il padre
  di `zsh` è `gnome-terminal-server`) produce `DEV_SERVER`.
- **Q-4 = A.** T-3.1a e T-3.1b si fanno in Fase 1 (lotto L1-5): RF-01, RF-04 e §6.5
  (`primary_action.risk`) chiedono il rischio fin dalla sola visione.
- **Q-7 = B.** CP-0 diventa `make setup && make lint && make test` verdi **e** `wimm --version`
  eseguibile dal venv. È il "minimo codice eseguibile" del workflow, e `--version` senza
  registrarsi sul bus è già previsto da §14.1. Lo stub `app.py` lo completa poi T-1.8c. Il
  checkpoint umano CP-0 decade: l'utente ha chiesto di procedere fino alla fine.
- **Q-2, Q-3, Q-5, Q-6, Q-8..Q-14:** il default A di ciascuna. Q-13 e Q-14 si annotano in
  `docs/DEVIATIONS.md` nei task T-5.3b e T-1.8c.
- **Git:** commit atomici direttamente su `main` (D-U2).
