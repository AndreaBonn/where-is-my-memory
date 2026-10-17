# Piano: app bilingue IT/EN

Stato: in attesa di approvazione. Nessun codice scritto.

## Decisioni approvate (Qualify, 2026-10-17)

- Libreria: `gettext` della stdlib, msgid in italiano. Il dizionario IT è il msgid stesso,
  `po/en.po` contiene l'inglese.
- Selettore: riga "Lingua" nel dialog Preferenze, due toggle a bandiera (IT, US).
- Cambio lingua: finestra e menu della tray ricostruiti, senza riavvio.
- Primo avvio senza scelta salvata: segue la locale di sistema.

## Assunzioni da confermare

- **A1** Locale di sistema `en*` → EN, qualsiasi altra (`it*`, `de*`, `C`) → IT. Era la
  formulazione dell'opzione scelta; l'alternativa è "solo `it*` → IT, tutto il resto → EN".
- **A2** I file `.desktop` e la metainfo restano come sono: li legge la shell con la locale
  di sistema, la scelta fatta nell'app non li può raggiungere.
- **A3** I messaggi di log, le eccezioni interne e l'interfaccia D-Bus Inspector restano in
  inglese e fuori da i18n (non sono testo mostrato all'utente).
- **A4** La specifica §0.4 ("stringhe in italiano") viene superata da questa richiesta. La
  divergenza si registra in `docs/DEVIATIONS.md`; `assets/SPECIFICHE.md` non si tocca.

## Architettura

- `src/wimm/i18n.py`: `_()`, `ngettext()`, `N_()`, `set_language()`, `current_language()`,
  `resolve_default(env)`. Tiene un solo riferimento globale a un oggetto
  `gettext.NullTranslations` (IT) o `GNUTranslations` (EN). Lo scambio è un'assegnazione
  atomica, quindi il thread del sampler non vede mai uno stato a metà.
- `po/wimm.pot` (generato), `po/en.po` (versionato), `.mo` compilato in `build/locale`
  (dev) e in `/usr/share/locale/en/LC_MESSAGES/wimm.mo` (pacchetto). Il `.mo` non si
  versiona.
- `Config.language: Language | None = None` (`None` vuol dire "segui il sistema"),
  validato come gli altri campi e salvato in `config.json` (ADR-005).

### Convenzione di naming (al posto delle chiavi)

Con msgid italiano la chiave è il testo sorgente. Per distinguere due stringhe uguali con
significati diversi si usa `pgettext(context, msgid)`, con context `area.ruolo`
(`tray.menu`, `disk.action`). Solo dove serve, non ovunque.

### Tre forme di estrazione

| Caso nel codice attuale | Forma nuova |
|---|---|
| Testo usato dentro una funzione | `_("Applica")` |
| Costante di modulo (circa 260 casi) | `APPLY = N_("Applica")` e `_(APPLY)` nel punto in cui si usa |
| f-string con valori | `_("Chiudendolo liberi {size} di memoria.").format(size=...)` |
| `x if n == 1 else y`, `_counted(one=, many=)` | `ngettext("{n} giorno", "{n} giorni", n).format(n=n)` |

La riga sulle costanti è il punto delicato: `_()` valutato all'import fisserebbe la lingua
del momento, e il cambio dal vivo non le raggiungerebbe.

## Fasi (ognuna mergiabile: una stringa non tradotta ricade sull'italiano)

### F1. Infrastruttura, nessun cambiamento visibile
- `i18n.py` + test (IT identità, EN dal `.mo`, fallback su msgid mancante, A1).
- `Config.language` + parse/validazione/round-trip + test.
- `po/en.po` vuoto, target `make po` (xgettext → pot → msgmerge) e `make mo` (msgfmt);
  `make test` dipende da `mo`. `build_deb.sh` compila e installa il `.mo`; `gettext`
  entra in Build-Depends, non in Depends.
- verify: `make test` verde; `uv run python -c "from wimm import i18n; i18n.set_language('en'); print(i18n._('x'))"` stampa `x`.

### F2. Core (testo e formati)
- `core/text.py`, `risk_table.py`, `notify_rules.py`, `assemble.py`; `_counted` → `ngettext`.
- `format_decimal` e `format_size` usano il separatore della lingua attiva (`,` IT, `.` EN).
- Prime voci in `en.po` per queste stringhe.
- verify: i test esistenti restano verdi in IT; nuovi test in EN su motivo, rischio,
  notifica e `format_size(1_100_000_000)` → `1.1 GB`.

### F3. UI: dialog e preferenze
- `ui/dialogs/*`, `ui/outcome.py`, `ui/toasts.py`.
- verify: test UI esistenti verdi; nuovo test che apre conferma ed esito in EN.

### F4. UI: pagine, widget, formati
- `ui/pages/*`, `ui/widgets/*`, `ui/format.py` (durate relative), `summary*.py`,
  `disk_*.py`, `plain.py`, `viewmodel.py`, `window*.py`, About dialog.
- verify: come F3, sulla finestra principale e sulla pagina disco.

### F5. Tray, servizio, notifiche
- `tray/menu_model.py`, `service/errors.py`, `config.py` (messaggi di errore campo),
  `first_run.py`, notifiche.
- verify: test del menu model in EN.

### F6. Selettore e cambio dal vivo
- Riga "Lingua" in Preferenze: due `Gtk.ToggleButton` raggruppati, bandiera come contenuto
  (emoji regionali 🇮🇹 🇺🇸, font Noto Color Emoji già presente su Ubuntu), tooltip e nome
  accessibile "Italiano" / "English". La scelta si applica al clic, non con "Applica",
  come già succede per "Programmi senza avvisi".
- Al cambio: `set_language`, salvataggio in config, la MainWindow viene ricostruita e
  riapre Preferenze sulla stessa pagina, il menu della tray viene rigenerato, si chiede un
  nuovo campione.
- verify: test UI che clicca 🇺🇸, ritrova la finestra in EN, riavvia l'app con la stessa
  config e la trova ancora in EN.

### F7. Verifica di completezza e documenti
- `scripts/check_i18n.py`: (a) scansione AST di `ui/`, `tray/`, `core/` alla ricerca di
  literal con testo naturale fuori da `_()`/`N_()` e fuori da docstring e log, con lista di
  eccezioni dichiarata; (b) ogni msgid del pot ha un msgstr in `en.po`; (c) i msgid già
  in inglese (container, Docker, cache...) hanno msgstr identico. Esce 1 su ogni violazione,
  ed entra in `make lint`.
- Test UI di sweep: in EN percorre l'albero dei widget di finestra, Preferenze e pagina
  disco, e fallisce su ogni etichetta che coincide con un msgid italiano tradotto in modo
  diverso.
- `docs/DEVIATIONS.md` (A4), `CLAUDE.md` del progetto (convenzione `_()`/`N_()`).
- verify: `make lint` e `make test-all` verdi, sweep a 0 residui.

## Rischi

- **R1** Testo calcolato dal sampler e già salvato nello snapshot resta nella lingua
  precedente fino al campione successivo. Mitigazione: nuovo campione forzato al cambio.
- **R2** Il core passa a dipendere da uno stato globale (la lingua attiva). Resta senza
  gi, psutil e Docker, ma l'output non dipende più solo dagli argomenti. Alternativa
  scartata: codici messaggio resi dalla UI, che è un refactor del core fuori scope.
- **R3** Ricostruire la finestra perde scroll e dialog aperti oltre a Preferenze.
- **R4** Volume: 450-550 stringhe. Un errore di forma (`_()` all'import) passa i test IT e
  si vede solo in EN: è il motivo per cui lo sweep di F7 gira sulla UI renderizzata.
- **R5** Le emoji bandiera dipendono dal font installato. Senza font a colori si vedono le
  lettere "IT"/"US", che restano leggibili. Alternativa: SVG in `data/icons`.

## Dipendenze nuove

Nessuna su PyPI. Solo `gettext` (apt) come Build-Depends, per `msgfmt` e `xgettext`.
