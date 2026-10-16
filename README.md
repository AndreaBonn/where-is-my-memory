# where-is-my-memory

Applicazione per Ubuntu che mostrerà RAM e disco occupati da processi,
container e progetti, segnalando le risorse inattive.
Le azioni sulle risorse richiederanno una conferma dell'utente.

Il progetto è allo scheletro iniziale (lotto L0-1): la GUI non è ancora implementata.
È disponibile `wimm --version`.

Per lo sviluppo servono Ubuntu 24.04, Python di sistema ≥3.12, uv e i pacchetti apt
`python3-gi`, `python3-psutil`, `python3-docker`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`.

```bash
make setup
make test
make lint
uv run wimm --version
```

La specifica di riferimento è `assets/SPECIFICHE.md`.
Licenza GPL-3.0-or-later, testo completo in `LICENSE`.
