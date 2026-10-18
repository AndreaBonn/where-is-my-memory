# ADR-007: radici di sviluppo fuori dalla home

- Stato: Proposta
- Data: 2026-10-18

## Context

Oggi una radice di sviluppo deve stare sotto la home: `decode_roots` rifiuta ciò che non è
`is_relative_to(home)` (`src/wimm/config_roots.py`) e l'esecutore ripete il controllo in
`_inside_a_root` (`src/wimm/service/executor_disk_fs.py`). Chi tiene i progetti su un secondo
disco, per esempio `/mnt/data/code`, non può configurarli (R26). Allargare il perimetro tocca §0.5
e RNF-06: nessun percorso di sistema deve diventare cancellabile, nemmeno con un piano costruito a
mano. La rimozione resta in `safe_tree.py`, che lavora per descrittori `O_NOFOLLOW`, confronta
`st_ino`/`st_dev` e non attraversa i mount. Il rilievo S3 del piano è P0 per T075 e T077.

## Decision

Una radice è ammessa se una funzione pura, senza I/O, non restituisce un motivo di rifiuto. I
fatti li raccoglie il chiamante (lstat, catena degli antenati, `mountinfo`):

```python
def root_refusal(*, facts: RootFacts, home: Path) -> RootRefusal | None: ...
```

`RootFacts` porta `realpath`, `is_symlink`, `st_uid`, `own_uid`, `own_gid`, `mode` della radice,
`ancestors` (uid, gid, mode di ogni componente da `/` al padre) e `fstype` e `read_only` del mount
che contiene la radice. È una deviazione dalla firma a cinque parametri di T075: §0.7 ne ammette
quattro, e i fatti di mount e antenati non ci stanno comunque. `RootRefusal` è un enum con un
messaggio italiano per motivo (`N_()`), così la finestra spiega il rifiuto (R26).

Motivi, valutati in questo ordine:

1. `SYMLINK`: il percorso configurato è un symlink. Gli antenati symlink si risolvono e si giudica
   il `realpath` (vale `/home -> /data/home`).
2. `TOO_SHALLOW`: due componenti o meno (`/mnt/data`, `/data`).
3. `SYSTEM_PATH`: `realpath` è uguale o discendente di `/`, `/usr`, `/etc`, `/var`, `/boot`, `/proc`,
   `/sys`, `/dev`, `/run`, `/opt`, `/snap`, `/root`, `/srv`, `/tmp` (costante in `core/constants.py`).
4. `HOME_OR_ANCESTOR`: è la home o un suo antenato. La home resta fuori come in S3 e S15: contiene
   `~/.gradle` e le cache, che hanno regole proprie.
5. `OTHER_HOME`: sta sotto `home.parent` senza stare sotto la home (`/home/bob/...`), anche se il
   file è nostro.
6. `NOT_OWNED`: `st_uid != own_uid`.
7. `UNSAFE_PARENT`: un antenato non è di root o dell'utente, oppure è scrivibile da altri senza
   sticky bit, o dal gruppo senza sticky con un gid diverso da 0 e da `own_gid`. Stessa regola
   vale per la radice stessa.
8. `REMOTE_FS`: `fstype` di rete, FUSE (`fuse`, `fuse.*`) o `autofs` (`NETWORK_FSTYPES`).
9. `READ_ONLY`: il mount ha l'opzione `ro`.

Esempi: `/mnt/data/code` dell'utente, `/mnt/data` di root non scrivibile da altri: ammessa.
`/mnt/data` stessa: `TOO_SHALLOW`. `/var/www/proj` dell'utente: `SYSTEM_PATH`.

### Discendenti dei percorsi di sistema: rifiutati

Sotto `/opt`, `/srv` e `/var/www` un `node_modules` o un `.venv` non è materiale di sviluppo
rigenerabile ma il runtime di un servizio installato: cancellarlo rompe un'applicazione che gira,
e l'utente non lo ricostruisce con un `npm install` nel progetto. La proprietà non distingue i due
casi, perché un servizio installato a mano è spesso dell'utente. Sotto `/tmp` i progetti sono
effimeri e il direttorio è condiviso. Una regola sul prefisso è verificabile con un test riga per
riga; una lista di eccezioni no.

### Proprietà dei livelli: si controlla ogni antenato

La sola proprietà della radice non basta. In `/mnt/shared` scrivibile da tutti senza sticky bit,
un altro utente può rinominare `code` e mettere al suo posto un symlink o una cartella sua con un
`node_modules` dentro. Il fingerprint `st_ino`/`st_dev` del piano ferma lo scambio fra piano ed
esecuzione, ma non uno scambio avvenuto prima della scansione: l'utente vedrebbe proposte su
contenuti scelti da altri. Con lo sticky bit (`/tmp`, `/mnt/shared` in `1777`) gli altri non
possono rinominare voci non loro, e il livello è sicuro. È la regola di `sshd` StrictModes e di
`sudo` sui path sicuri. Il gid proprio è ammesso perché Ubuntu usa gruppi privati con umask 002.

### Mount: solo filesystem locali e scrivibili

Rete e FUSE sono rifiutati come radice. Su NFS e CIFS `st_uid` è mappato dal server (squash,
idmap), quindi `NOT_OWNED` e `UNSAFE_PARENT` controllano un numero che non dice chi può scrivere;
altri host modificano l'albero senza passare dai permessi locali; un mount bloccato ferma il
thread dell'esecutore, motivo per cui la rilevazione li salta già (`NETWORK_FSTYPES`); e un
`node_modules` su una share può essere quello di un collega. Su FUSE (sshfs, rclone, gvfs) uid e
mode li dichiara il demone. I dischi rimovibili locali (ext4, exfat, vfat sotto
`/media/<utente>/...`) sono ammessi: il loro rischio è lo scollegamento a metà, che `safe_tree`
registra come errore e non come danno.

## Consequences

- `decode_roots` sostituisce `is_relative_to(home)` con `root_refusal`; una radice rifiutata
  resta visibile con il motivo, come oggi `missing_roots`, invece di far cadere l'elenco. Una
  configurazione esistente con `~` diventa rifiutata: va migrata con un messaggio.
- La rilevazione automatica (`root_candidates.py`) resta dentro la home: una radice esterna nasce
  solo da una scelta esplicita dell'utente.
- Esecutore (R27, T077): `_inside_a_root` ricalcola i fatti sulla radice reale al momento
  dell'esecuzione, rileggendo `st_uid`, la catena degli antenati e `mountinfo`, e chiama la stessa
  funzione; un rifiuto è `ProtectedTarget`. Il piano registra `st_dev` della radice e l'esecutore lo
  confronta (S4): un altro disco montato sullo stesso path dà `TargetChanged`. Devdir e progetto
  devono essere dell'utente (S4).
- `safe_tree.py` resta invariato: non attraversa i mount, apre ogni livello con `O_NOFOLLOW` e
  confronta inode e device. Il perimetro nuovo si decide prima, `safe_tree` non lo conosce.
- `config_roots.py` passa a dipendere da un modulo `core/root_policy.py` testato per motivo
  (`tests/core/test_root_policy.py`), con un caso ammesso per ogni rifiuto vicino.

## Alternatives considered

- **Whitelist esplicita di prefissi** (`/mnt`, `/media`, `/data` configurabili). Scartata: sposta
  sull'utente la scelta del perimetro, e un prefisso aggiunto per comodità (`/`) riapre tutto.
- **Nessuna restrizione oltre la proprietà.** Scartata: un servizio sotto `/opt` o `/srv` è spesso
  dell'utente, e RNF-06 chiede che nessun percorso di sistema sia raggiungibile.
- **Solo `/mnt` e `/media`.** Scartata: esclude `/data`, `/work`, `/srv/...` dove molti montano il
  secondo disco, e non protegge da `/mnt/shared` scrivibile da tutti; il problema vero sono
  proprietà e antenati, non il nome del punto di mount.
- **Radici esterne ammesse con conferma `danger`.** Scartata: la conferma protegge l'azione, non
  la scelta del perimetro, e si abitua l'utente a digitare nomi.
- **Bind mount del disco in home** (funziona già oggi). Scartata come risposta a R26: richiede
  root e `fstab`, ma resta il ripiego documentabile.

## Rischi residui

- I prefissi di sistema sono una lista chiusa: un percorso come `/usr2` o `/nix` dell'utente
  passerebbe. `/nix` è di root e cade su `NOT_OWNED`, ma la lista va rivista per le distro.
- Fedora monta i rimovibili in `/run/media/<utente>`, che cade su `SYSTEM_PATH`: fuori dalla 1.x
  Ubuntu-first, da rivedere con un'eccezione nominata se arriva il pacchetto RPM.
- `vfat` ed exfat non hanno proprietari reali: `st_uid` viene dalle opzioni di mount, quindi su un
  disco rimovibile il controllo degli antenati dimostra poco.
- Fra la raccolta dei fatti e l'apertura del primo descrittore resta una finestra TOCTOU sugli
  antenati; la chiude solo il confronto `st_ino`/`st_dev` già in `safe_tree`.
- Un mount `bind` di un percorso di sistema sotto `/mnt/data/code` ha un `realpath` innocuo: lo
  ferma `safe_tree`, che salta i mount elencati in `mountinfo`, non questa regola.
