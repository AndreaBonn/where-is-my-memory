# Registro delle misure di performance

Ogni modifica fatta per le prestazioni, tenuta o scartata, con la misura prima e dopo.
Serve a non riprovare un'idea già misurata. Condizioni: macchina di sviluppo dell'utente,
Ubuntu 24.04, circa 1300-1340 processi utente, 41 gruppi, Docker attivo.

## Ciclo di campionamento (RNF-03: sotto 1,5 s)

Misura: `Sampler` con i collector reali, un ciclo di riscaldamento, poi il ciclo misurato.
Il profilo (cProfile) gonfia i tempi, quindi il verdetto si dà sul tempo non profilato.

| Data | Idea | Prima | Dopo | Verdetto | Perché |
|---|---|---|---|---|---|
| 2026-10-16 | Indice dei figli per ciclo e CPU "processo più figli" in un solo passaggio post-order, al posto di `ancestors()` per ogni coppia di PID | ciclo 7,67 s (profilato), `family_pids` 4,79 s con 3.009.692 chiamate | `family_pids` 0,018 s (micro-benchmark a 1339 processi) | tenuta | algoritmo quadratico sostituito da uno lineare |
| 2026-10-16 | Indice delle quadruple non-LISTEN per porta locale e remota, costruito una volta per ciclo | `non_listening_for_ports` 0,30 s (micro-benchmark) | 0,0018 s | tenuta | ogni server faceva una scansione completa dei socket |
| 2026-10-16 | Ciclo intero dopo i due fix | 7,67 s | 1,25-1,28 s su 5 cicli (rumore ±0,02 s); 1,31-1,34 s nel processo `wimm --background` | - | sotto il limite |
| 2026-10-16 | Mappa delle categorie degli antenati precalcolata in `categorize` | `_app_decision` 0,59-0,63 s | non provata | rimandata | il ciclo è già sotto il limite; da riprendere se una misura supera 1,5 s (ripiego R3 di §18) |
| 2026-10-16 | Ciclo del processo `wimm --background` con load average 7,5 (agent di sviluppo in parallelo) | - | 1,40 / 1,47 / 1,55 s | segnale | sotto carico il ciclo sfiora il limite: la riga sopra va ripresa in T-6.5, misurando a macchina quieta e sotto carico |
| 2026-10-16 | `psutil.Process.oneshot()` attorno alle letture per processo | 0,444 s | 0,441 s | scartata | neutro: domina `memory_full_info` (`smaps_rollup`) |

## Memoria del processo residente (RNF-02: sotto 120 MB a finestra mai aperta)

| Data | Configurazione | RSS | PSS | Verdetto |
|---|---|---|---|---|
| 2026-10-16 | Python di sistema con `import gi.repository.Gtk` (GTK 4), senza altro | 124 MB | - | il limite non è raggiungibile con GTK caricato all'avvio |
| 2026-10-16 | `Gio.Application` residente, GTK caricato solo all'apertura della finestra, dopo 3 cicli | 54,6 MB | 40,6 MB | tenuta (docs/DEVIATIONS.md) |

## Panoramica GTK con 300 gruppi (RNF-03: main loop mai bloccato oltre 50 ms)

Misura: `OverviewPage` in una `Gtk.Window` mappata sotto Xvfb, 300 `Adw.ExpanderRow`, slice = una iterazione del main loop. Baseline: 1 run; dopo: mediana di 5 run. Lo slice massimo include anche il layout del frame clock, non solo il lavoro della pagina.

| Data | Idea | Prima | Dopo | Verdetto | Perché |
|---|---|---|---|---|---|
| 2026-10-16 | `Gtk.ListBox.set_sort_func` + `invalidate_sort()`, righe aggiunte o tolte per id, niente remove+insert | ordine invertito 11,6 s; jitter 3% 11,9 s; una riga che si sposta 5,8 s | invertito 0,38 s; jitter 0,41 s; una riga 0,30 s (slice unico) | tenuta | ogni remove+insert invalidava il layout della lista |
| 2026-10-16 | Membri aggiornati in place per chiave in `GroupRowWidget`, ricostruzione solo se cambia la sequenza di chiavi | 20 righe x 8 membri aperti: 1599 ms | 533 ms | tenuta | menu aperto e focus restano; costo 3x minore |
| 2026-10-16 | Costruzione e update a blocchi con `GLib.idle_add`, budget 10 ms per slice | costruzione 595 ms in uno slice; update con tutte le righe cambiate 530 ms | slice di lavoro della pagina max 15 ms; slice massimo del main loop 14-32 ms in update, 55 ms alla costruzione (layout dell'ultimo frame con 300 righe) | tenuta | totale più lungo (costruzione 2 s) ma nessun blocco; ListView non implementata, da valutare solo se la costruzione supera ancora 50 ms |
| 2026-10-16 | Stessa misura con il renderer dell'app (`GSK_RENDERER=cairo`, GL e Vulkan disattivati), ora default di `make perf` | slice massimo con GL: 14-32 ms in update, 55 ms alla costruzione | 5 run: update mappato 15-45 ms (mediana 17), costruzione 25-46 ms (mediana 33), una riga cambiata 7-11 ms | tenuta | sotto 50 ms in tutte le run; con GL la misura non rappresentava il processo reale |

## Memoria con la finestra aperta e poi nascosta (RNF-02: sotto 200 MB)

Misura: `scripts/dev_run.sh` sul display reale (X11), finestra aperta 35 s con circa 40 gruppi
reali, poi chiusa (nascosta) con `wmctrl -c`; RSS e PSS da `/proc/<pid>`.

| Data | Configurazione | RSS | PSS | Verdetto |
|---|---|---|---|---|
| 2026-10-16 | renderer di default (GL: Mesa `libgallium` e `libLLVM` caricate) | 227 MB | 196 MB | sopra il limite |
| 2026-10-16 | `GSK_RENDERER=cairo` | 210 MB | 178 MB | scartata da sola: GDK inizializza comunque GL |
| 2026-10-16 | `GSK_RENDERER=cairo` + `GDK_DEBUG=gl-disable,vulkan-disable` | 130 MB | 100 MB | tenuta: render visivamente identico (screenshot confrontati) |
| 2026-10-16 | stessa configurazione come default dell'app, avvio senza variabili | 126 MB | - | verifica: nessuna libreria GL nelle mappe |

## Apertura della finestra senza display (RNF-03: main loop mai bloccato oltre 50 ms)

Misura: `_build_window` in un sottoprocesso senza `DISPLAY` né `WAYLAND_DISPLAY`, su bus privato.

| Data | Idea | Prima | Dopo | Verdetto | Perché |
|---|---|---|---|---|---|
| 2026-10-16 | Controllo del display aperto da GTK prima di importare libadwaita | `Adw.init()` blocca 25,1 s prima del `RuntimeError` | errore in meno di 1 s (test D-Bus `--group` da 25 s a 2,5 s) | tenuta | il processo residente non resta fermo quando la sessione grafica manca |

## Pianificazione delle azioni sul main loop (RNF-03: sotto 50 ms)

Misura: `plan_action` in processo, 20 ripetizioni, snapshot sintetico con 300 gruppi idle e 3 processi ciascuno (900 processi). Il dialogo di conferma lo chiama sul main loop a ogni clic e a ogni interruttore.

| Data | Richiesta | Mediana | Massimo | Verdetto |
|---|---|---|---|---|
| 2026-10-17 | `stop_all_idle_safe` (900 step) | 20,2 ms | 22,0 ms | sotto il limite, nessuna ottimizzazione |
| 2026-10-17 | `group_stop` su un gruppo | 0,1 ms | 0,1 ms | sotto il limite |

## Misura di un'ora (T-6.5, 2026-10-17)

Build del repository, `wimm --background` per 1 h su bus D-Bus privato e Xvfb, cartelle XDG temporanee, servizio della barra finto. 393 processi utente, 8 container, load average 5,4-6,4.

| Grandezza | Valore | Limite | Verdetto |
|---|---|---|---|
| CPU a regime (`pidstat -p <pid> 60 10`, minuti 2-11) | 1,32-1,60% di un core; media 2,30% con il picco del 10,15% della prima scansione del disco | 1% (RNF-01) | non rispettato: il ciclo costa 0,47 s ogni 30 s, dominato da `smaps_rollup` |
| RSS a finestra mai aperta, dopo 55 min | 63 MB | 120 MB (RNF-02) | rispettato |
| RSS con la finestra aperta, dopo 56 min | 136 MB | 200 MB (RNF-02) | rispettato (limite superiore della finestra nascosta) |
| Ciclo di campionamento, 122 cicli | mediana 0,47 s, massimo 0,61 s | 1,5 s (RNF-03) | rispettato a 393 processi |

## CPU del ciclo per RNF-01 (2026-10-17)

Misura: `bench_cycle.py`, 12 cicli dopo uno di riscaldamento, tempo di CPU del processo per ciclo (`time.process_time`), tre run per riga; 721-727 processi in totale, 27 gruppi, load average 5,5-7,3. Limite di RNF-01 tradotto: sotto 0,30 s di CPU ogni 30 s.

| Idea | Baseline -> Risultato (mediane delle tre run) | Verdetto | Perché |
|---|---|---|---|
| Specifiche dei campi dei modelli lette una volta per classe invece che a ogni istanza | 0,409 / 0,413 / 0,433 s -> 0,387 / 0,389 / 0,393 s | tenuta | serie non sovrapposte; 4300 modelli per ciclo |
| Cache limitata (4096) su scomposizione del cgroup e confronto dei pattern | 0,387-0,393 -> 0,354-0,363 s | tenuta | 118 mila iterazioni e 98 mila `fnmatchcase` per ciclo su poche centinaia di stringhe |
| Nome dell'eseguibile da un percorso via helper in cache invece di `PurePosixPath` per ogni processo | 0,354-0,363 -> 0,324-0,340 s | tenuta | 10 mila costruzioni di `Path` per ciclo |
| Nessuna ricorsione di `require_immutable` sugli elementi scalari delle tuple | 0,324-0,340 -> 0,313-0,320 s | scartata | guadagno dentro il rumore fra run (±0,01 s) con codice in più |
| Lettura di `smaps_rollup` solo per i processi dei gruppi su cui si può agire (O1) | stima: 83 processi su 390 del proprio utente sono fuori da quei gruppi, `memory_full_info` costa 0,10 s per tutti i 390 | non provata | risparmio atteso circa 0,02 s: non porta da solo sotto 0,30 s |

Dopo le tre modifiche tenute il ciclo costa 0,33-0,34 s di CPU (circa 1,1% di un core a 30 s): RNF-01 resta sopra il limite. La voce rimasta più grande è `memory_full_info` (0,10 s).

## Conferma di RNF-01 con l'intervallo a 60 s (2026-10-17, 12:31-12:45)

Stesso isolamento della misura di un'ora (build del repository, bus D-Bus privato, Xvfb, servizio della barra finto, cartelle XDG temporanee). 391 processi utente, 8 container, load average 6,1-7,1. `pidstat -p <pid> 60 13` a partire dal primo minuto.

| Grandezza | Valore | Limite | Verdetto |
|---|---|---|---|
| CPU a regime, minuti 8-15 | 0,53-0,63% di un core | 1% | rispettato |
| CPU, minuti 4-13 | media 0,75% | 1% | rispettato |
| CPU, tutti i 13 minuti | media 1,72%, con il 14,05% del minuto della prima scansione del disco (2 minuti dopo l'avvio, poi ogni 6 ore) | 1% | sopra il limite solo per la scansione iniziale |
| Ciclo di campionamento, 15 cicli | mediana 0,40 s, massimo 0,71 s | 1,5 s | rispettato |
| RSS dopo 14 minuti, finestra mai aperta | 62 MB | 120 MB | rispettato |

## Scansione delle cartelle di dipendenze (001-product-gaps, R4: aumento al massimo del 30%)

Misura: `scan_devdirs` sulla radice `~/Documenti`, profondità 6, cartella di cache vuota a ogni
run (dimensioni misurate da zero), senza la pausa fra le cartelle (`sleep` nullo), 3 run, codice
del commit misurato. Script `measure_devdirs.py` (nella cartella temporanea di sessione).

| Data | Codice | Cartelle trovate | Durata (mediana, 3 run) | CPU (mediana) | Verdetto |
|---|---|---|---|---|---|
| 2026-10-18 | baseline `d40bd18`, solo `node_modules` e `.venv` | 76 | 5,21 s (7,25 / 5,21 / 4,81) | 4,86 s | baseline |
| 2026-10-18 | baseline `d40bd18`, rimisurata subito prima del risultato (cache del filesystem calda per entrambi) | 76 | 3,93 s (3,93 / 3,85 / 4,68) | 3,66 s | riferimento a parità di condizioni |
| 2026-10-18 | `e4b6244`, tabella dei nomi di R4 con marker e secondo segnale | 88 | 4,04 s (4,58 / 4,04 / 3,77) | 3,80 s | tenuta: +3% di durata e +4% di CPU, dentro il rumore fra run e sotto il budget del 30% |

La prima riga di baseline (5,21 s) includeva un run a cache fredda: il confronto valido è fra le
due righe misurate una dopo l'altra.

## Apertura della finestra (RNF-04: sotto 1 s dal clic al primo render)

Misura: `scripts/measure_open_time.py`, 10 ripetizioni per caso.

```
dbus-run-session -- xvfb-run -a uv run python -m scripts.measure_open_time --workdir <cartella temporanea>
```

Che cosa si cronometra: l'app parte come `python -m wimm --background` con HOME e XDG_* temporanei, `GSK_RENDERER=cairo` e `GDK_DEBUG=gl-disable,vulkan-disable`. Lo script invia `org.freedesktop.Application.Activate` sul bus (la stessa chiamata a cui porta il clic sull'icona) e interroga X (`xdotool search --onlyvisible --pid`) finché una finestra del processo risulta mappata. Il cronometro include circa 10 ms di avvio dei processi `gdbus` e `xdotool` e si ferma alla mappatura, non alla prima pittura del contenuto. Prima di misurare c'è un'apertura scartata: su un bus privato nuovo la prima apertura attiva il portale desktop e impiega circa 25 s, un artefatto della sessione di prova che non esiste su un desktop reale.

Condizioni (2026-10-18, 02:09-02:10): Xvfb, bus di sessione privato, 16 core, load average 2,5 (3,8 alla fine) letto con `uptime`, app avviata 3 s prima di ogni misura. Prima apertura: processo nuovo a ogni ripetizione, GTK e libadwaita da caricare. Riaperture: stesso processo, finestra chiusa con WM_DELETE_WINDOW tra un campione e l'altro.

| Caso | Campioni (ms) | Mediana | p90 | Limite | Verdetto |
|---|---|---|---|---|---|
| Prima apertura | 276, 272, 227, 292, 209, 205, 217, 234, 239, 246 | 236 ms | 276 ms | 1 s | rispettato |
| Riapertura | 12, 10, 10, 10, 9, 8, 8, 11, 9, 10 | 10 ms | 11 ms | 1 s | rispettato |

Riserve: Xvfb non dipinge su uno schermo reale e il "primo render" è approssimato dalla mappatura della finestra; i dati dello snapshot sono già pronti, come prevede la specifica, ma qui il campionamento ha avuto solo 3 s per finire. La prova sul display reale resta nel controllo manuale M-2.


## Misura delle cache degli sviluppatori (001-product-gaps, T042)

Misura: `collect_caches` sulla home reale, cartella delle dimensioni vuota a ogni run, senza
pausa fra le cartelle, 3 run, le due versioni una dopo l'altra (cache del filesystem calda).
Script `measure_caches.py` nella cartella temporanea di sessione.

| Data | Codice | Voci | Dimensione misurata | Durata (mediana) | Verdetto |
|---|---|---|---|---|---|
| 2026-10-18 | baseline `d40bd18` (5 tipi) | 5 | 11,6 GB | 1,58 s (1,86 / 1,57 / 1,58) | riferimento |
| 2026-10-18 | 17 tipi, tabella risolta | 12 | 17,3 GB | 2,57 s (2,57 / 2,18 / 2,60) | tenuta |

Sulla prima scansione intera (cartelle di dipendenze, sezione sopra, più cache) il totale passa da
circa 5,5 s a 6,6 s: +20%, sotto il budget del 30% di R30. L'aumento compra 5,6 GB di cache in
più resi visibili. BASIS: measured.

## RNF-01 dopo i lotti L5-L8 (001-product-gaps, 2026-10-18, 14:15-14:45)

**pidstat a regime.** Stesso isolamento della misura del 2026-10-17 (bus D-Bus privato, Xvfb, cartelle XDG temporanee, finestra mai aperta), `pidstat -p <pid> 60 13` dopo il primo minuto. Sulla macchina 940-950 processi in totale (597 dell'utente, contro i 391 del 17), load average 4-11 per altre sessioni attive.

| Grandezza | Valore | Limite | Verdetto |
|---|---|---|---|
| CPU a regime, minuti senza picchi | 1,02-1,63% di un core | 1% | sopra il limite |
| CPU, media dei 13 minuti | 1,80%, con tre minuti al 3,4-3,9% | 1% | sopra il limite |
| RSS dopo 14 minuti, finestra mai aperta | 114 MB | 120 MB | rispettato, margine stretto |

**Confronto con la fine di L4 (`166f123`), stesse condizioni.** Per separare il codice nuovo dalla macchina più carica, `bench_cycle.py` (CPU per ciclo, 12 cicli, tre run alternati) e l'app completa avviata in parallelo nelle due versioni.

| Idea | Baseline -> Risultato | Verdetto | Perché |
|---|---|---|---|
| L5-L8, CPU per ciclo (minimi dei tre run) | 0,58-0,75 s -> 0,62-0,69 s | dentro il rumore | mediane 0,61-0,82 s contro 0,66-1,84 s; il run da 1,84 s cade con load 13,4 |
| L5-L8, RSS dell'app dopo 5 minuti | 113 MB -> 115 MB | dentro il rumore | +2 MB; un ciclo da solo occupa 42 MB in entrambe |

Il superamento di RNF-01 viene dal numero di processi da censire, cresciuto di circa il 50% rispetto al 17 ottobre, non dai lotti L5-L8: con 930 processi anche la versione di L4 costa 0,6-0,8 s di CPU per ciclo, cioè 1,0-1,3% di un core a 60 s. Il costo per processo resta la voce da ridurre (vedi la misura del 2026-10-17, dominata da `smaps_rollup` e `memory_full_info`).

## Baseline del disco granulare (002-disk-granular, T-6.2, 2026-10-19)

Misura: `collect_caches` sulla home reale, cartella delle dimensioni vuota a ogni run, senza
pausa, 3 run di seguito (cache del filesystem calda), stesso metodo della misura T042 sopra.
Script `measure_caches.py` nella cartella temporanea di sessione. Codice `077b733`.

| Data | Codice | Voci | Dimensione misurata | Durata (mediana) | Verdetto |
|---|---|---|---|---|---|
| 2026-10-19 | baseline `077b733` | 14 | 39,8 GB | 2,36 s (2,41 / 2,05 / 2,36) | riferimento per T-6.14 (budget +15%) |

Test: `make test` 3509 passati (447 deselezionati), copertura del core 99,96%. BASIS: measured.
