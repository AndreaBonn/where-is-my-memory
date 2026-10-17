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
