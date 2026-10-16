# where-is-my-memory

Dopo qualche giorno di lavoro il computer rallenta e la RAM è quasi finita, anche se
sembra che non ci sia molto aperto. Quasi sempre la causa è qualcosa rimasto acceso:
container Docker di un progetto chiuso da giorni, server di sviluppo, sessioni di
terminale, programmi pesanti dimenticati in secondo piano.

where-is-my-memory per Ubuntu mostra cosa occupa la memoria, raggruppato per progetto e
per tipo, e distingue ciò che è in uso da ciò che è acceso ma fermo. Per ogni gruppo dice
quanta RAM si libererebbe e da quanto tempo non succede niente. Vive nella barra in alto
del desktop, con un'icona sempre visibile.

Per ora l'app mostra e non agisce: non chiude nulla, né da sola né su tuo comando.
Fermare processi e container, le notifiche e il report del disco sono in arrivo. Nel frattempo
la finestra ti dice cosa chiudere, e lo chiudi come fai di solito.

## Requisiti

- Ubuntu 24.04 con desktop GNOME
- Docker, solo se vuoi vedere anche i container

## Installazione

Il pacchetto si costruisce dalla cartella del progetto che hai ricevuto. Apri un terminale
in quella cartella ed esegui i comandi uno alla volta.

1. Installa gli strumenti per costruire il pacchetto:

   ```bash
   sudo apt install make git
   ```

2. Il pacchetto riporta chi l'ha costruito. Se non hai mai configurato `git`, indica nome
   ed email (servono solo a questo):

   ```bash
   git config --global user.name "Nome Cognome"
   git config --global user.email "nome@esempio.it"
   ```

3. Costruisci e installa:

   ```bash
   make deb
   sudo apt install ./dist/where-is-my-memory_0.1.0_all.deb
   ```

`apt` installa da solo le librerie necessarie. Come componenti consigliati aggiunge anche
l'estensione AppIndicator per l'icona nella barra e gli strumenti per Docker.

## Primo avvio

Esci dalla sessione e rientra: l'app parte da sola al login, con l'icona nella barra e la
finestra chiusa. Se non vuoi riavviare la sessione, lancia da terminale:

```bash
wimm --background
```

Il comando `wimm`, senza opzioni, apre direttamente la finestra.

Se dopo il login non vedi né l'icona né la finestra, l'app non è partita: lancia
`wimm --background` da terminale. Se invece la finestra si apre con un avviso in alto,
manca l'estensione per l'icona (vedi più avanti).

## L'icona nella barra

Un clic sinistro apre la finestra, o la porta davanti se è già aperta. Un clic destro apre
un menu con il riepilogo di RAM e disco, fino a 5 gruppi inattivi (un clic su un gruppo
apre la finestra su quel gruppo), "Silenzia notifiche per 1 h" ed "Esci". Il silenzio
avrà effetto quando arriveranno le notifiche.

Accanto all'icona compare un testo come "4,2 GB inattivi": è la memoria che si libererebbe
fermando ciò che non viene usato. Sotto i 100 MB il testo non c'è.

L'icona cambia aspetto con lo stato della macchina:

| Icona | Significato |
|---|---|
| Normale | RAM e disco hanno spazio a sufficienza |
| Avviso | RAM disponibile o spazio libero sul disco sotto il 15% |
| Critica | RAM disponibile o spazio libero sul disco sotto il 10% |

L'icona passa all'avviso anche se il monitoraggio dà errore per più cicli di fila. In quel
caso la prima voce del menu lo dice.

Chiudere la finestra non ferma l'app, che continua a controllare. Per uscire del tutto
usa "Esci" dal menu dell'icona o dal menu della finestra.

## Cosa mostra la finestra

- **Panoramica**: i gruppi di processi e container, con categoria, stato (in uso, inattivo
  oppure non misurabile), motivo dello stato e RAM occupata e recuperabile.
- **Disco**: la vista è presente ma non ancora attiva, arriva in una prossima versione.
- **Sistema**: i processi che servono al desktop e al sistema, solo elencati e mai
  modificabili, con il motivo per cui sono protetti.

## Senza l'estensione AppIndicator

Su Ubuntu l'icona nella barra dipende dall'estensione AppIndicator di GNOME. Se è
disattivata o manca, l'app funziona lo stesso. Dopo circa 10 secondi dall'avvio apre la
finestra anche con `--background` e mostra in alto un avviso che spiega cosa manca. Nelle
Impostazioni di Ubuntu, alla voce Estensioni, puoi attivarla. Quando l'icona compare,
l'avviso sparisce.

## I tuoi file

L'app salva solo dati suoi, nelle cartelle standard dell'utente:

| Cartella | Contenuto |
|---|---|
| `~/.config/where-is-my-memory/` | le preferenze |
| `~/.local/state/where-is-my-memory/` | dimensioni della finestra e altri dati di stato, come da quanto tempo un gruppo è fermo |
| `~/.cache/where-is-my-memory/` | dati temporanei che l'app può ricostruire |

## Disinstallazione

```bash
sudo apt remove where-is-my-memory
```

I tuoi file nelle tre cartelle sopra restano anche con `apt remove` e con `apt purge`,
perché sono dati tuoi. Per cancellarli elimina le cartelle a mano. Se l'app è in
esecuzione, usa prima "Esci" dal menu dell'icona.

`apt remove` lascia il file di avvio automatico in `/etc/xdg/autostart/`, come per ogni
file di configurazione di sistema: `sudo apt purge where-is-my-memory` toglie anche quello.
Le librerie installate insieme all'app restano; `sudo apt autoremove` toglie quelle che
nessun altro programma usa.

## Domande frequenti

**Perché il browser mostra "attività non misurabile"?**
Dall'esterno non si può sapere se una scheda di Firefox o Chrome è in uso: il browser non
lo rende visibile. L'app lo dice invece di indovinare. La memoria del browser è comunque
conteggiata e visibile.

**Un server avviato nel terminale di VS Code non compare tra i server di sviluppo. Perché?**
Per scelta di progetto, tutto ciò che discende da VS Code è contato dentro il gruppo
dell'editor. Un server lanciato dal terminale integrato quindi non ha un gruppo suo, ma la
sua memoria è inclusa in quella di VS Code. Lanciato da un terminale normale, appare come
server a sé.

**I programmi aperti in una sessione SSH risultano fra i processi di sistema. Perché?**
Per prudenza, i processi nati da una sessione SSH, o da un tmux avviato da lì, sono
trattati come protetti. Compaiono nella vista Sistema e non nella Panoramica.

**Mi serve per quello che lancio su altre macchine, collegato in remoto?**
No. L'app guarda solo il computer su cui è installata. Ciò che gira su un server remoto
occupa la memoria del server, non la tua, e l'app non lo vede.

## Per chi sviluppa

Servono Ubuntu 24.04, Python di sistema 3.12 o successivo, uv e i pacchetti apt
`python3-gi`, `python3-psutil`, `python3-docker`, `gir1.2-gtk-4.0`, `gir1.2-adw-1`.

| Comando | Cosa fa |
|---|---|
| `make setup` | crea l'ambiente virtuale e sincronizza le dipendenze con uv |
| `make test` | esegue i test senza integrazione, interfaccia e D-Bus |
| `make test-all` | esegue tutti i test su bus e display privati |
| `make lint` | controlla Ruff, formato e tipi con mypy |
| `make run` | avvia l'app in modalità sviluppo con `scripts/dev_run.sh` |
| `make deb` | costruisce il pacchetto in `dist/` |
| `make test-deb` | installa il pacchetto in un container Ubuntu 24.04 e verifica installazione e rimozione |

La specifica di riferimento è `assets/SPECIFICHE.md`. Licenza GPL-3.0-or-later, testo
completo in `LICENSE`.
