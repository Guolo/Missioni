# Missioni
Una semplice app per segnare le missioni tra una sede ed un altra di un Istituto Comprensivo in Trentino ed esportare le missioni con il modello standard provinciale Trentino

<img width="753" height="753" alt="Screenshot 2026-09-29 alle 17 02 20" src="https://github.com/user-attachments/assets/f4a0143c-34b9-42e1-add4-b27801878fcf" />

# Installazione & Utilizzo
Prerequisiti:  
[Docker](https://www.docker.com) e [Docker Compose](https://docs.docker.com/compose/) installati.

Crea un ```docker-compose.yml``` file:
```
services:
  missioni:
    image: alguolo/missioni:latest
    container_name: missioni-app
    ports:
      - "5002:5000"
    volumes:
      - ./data:/app/data
      - ./assets:/app/assets:ro
    env_file:
      - .env
    environment:
      - TZ=Europe/Rome
    restart: unless-stopped
```
Prima del primo avvio crea un ```.env``` file e compila con le tue informazioni:
```
nano .env
```
- example ```.env``` file:
```
TITOLO=Comprensivo Esempio
MATRICOLA=12345
COGNOME_NOME=Rossi Mario
QUALIFICA=C.S.
SEDE_SERVIZIO=Trento
SEDE_DOMICILIO=Trento
CODICE_LUOGO=1
MEZZO_PROPRIO=3
MOTIVAZIONE=Servizio tra plessi
SCUOLE=scuola1,scuola2,scuola3
SPECIFICA_ORARIO=true

#SESSION_COOKIE_SECURE=true
#FLASK_DEBUG
```
Ogni campo lasciato vuoto o assente dal `.env` non viene compilato nel PDF.
- `SPECIFICA_ORARIO`: se impostata a `false`, l'ora di inizio e di fine
  non vengono stampate nel PDF esportato. Di default è attivo.
- `SECRET_KEY`: chiave segreta usata per firmare le sessioni di accesso.
  Se non impostata, l'app ne genera una automaticamente al primo avvio
  e la salva in `data/secret_key.txt` (persistente grazie al volume
  Docker), così le sessioni restano valide anche dopo un riavvio.
  Consigliato impostarla esplicitamente in produzione.
- `SESSION_COOKIE_SECURE`: impostala a `true` se l'app è servita in
  HTTPS (fortemente consigliato, essendo accessibile da internet) per
  proteggere il cookie di sessione. Di default è `false`, per non
  impedire l'accesso se l'app viene provata senza HTTPS.
- `FLASK_DEBUG`: lascia assente o `false` in produzione. Il debug mode
  di Flask espone un debugger interattivo pericoloso se raggiungibile
  da internet.

I dati vengono salvati in `./data/missioni.db` (SQLite), che rimane
persistente anche se ricostruisci il container, grazie al volume
montato in `docker-compose.yml`. Nella stessa cartella viene salvata
anche la chiave di sessione generata automaticamente (se non impostata
via `.env`).

Avvia il docker compose:
```
docker compose up -d
```
L'immagine è costruita per più architetture - Docker utilizzerà in automatico la versione corretta in base al sistema (amd64 or arm64).

## Accesso

L'app, disponibile su http://localhost:5002, è protetta da login. Al primo avvio viene creato un utente
predefinito:

- utente: `admin`
- password: `admin`

**Cambia subito questa password** (o crea un nuovo utente ed elimina
`admin`) dalla pagina "Utenti", visibile nel menu in alto solo da
computer, dopo aver effettuato l'accesso.

## Esporta 

genera il "Foglio viaggio"
in PDF con tutte le missioni registrate.

<img width="1402" height="523" alt="Screenshot 2026-09-29 alle 17 24 37" src="https://github.com/user-attachments/assets/0bca107a-2dac-445e-962a-238c9774a4ba" />


Dopo l'esportazione, le missioni esportate non restano più nell'elenco
principale: vengono raccolte in una **cartella a discesa** ("Esportazione
del …") in fondo alla pagina Riepilogo. In questo modo, alla successiva
esportazione, quelle missioni non vengono incluse di nuovo e nel PDF
finiscono solo le missioni nuove.

<img width="735" height="284" alt="Screenshot 2026-09-29 alle 17 23 43" src="https://github.com/user-attachments/assets/d36ca973-e356-4139-888d-20a4fdf316fb" />


Ogni cartella di esportazione offre due azioni:

- **↺ Reimporta**: riporta le missioni nell'elenco principale, dove tornano
  modificabili e riesportabili. Utile se ti accorgi di un errore dopo
  aver esportato.
- **✕ Elimina**: cancella definitivamente quelle missioni dal database.
  L'operazione non è reversibile (viene chiesta una conferma).

## Usare un proprio Foglio viaggio (es. con l'intestazione della scuola)

L'immagine include già un "Foglio viaggio" standard, quindi l'app funziona
senza configurazioni aggiuntive. Se invece vuoi usare un modulo personalizzato,
per esempio con l'intestazione della tua scuola o con direttamente la tua firma:

1. Crea una cartella `assets` accanto al file `docker-compose.yml`.
2. Inserisci al suo interno il tuo PDF chiamandolo esattamente
   `foglio_viaggio_standard.pdf`.

4. Riavvia il container (le missioni presenti non verranno eliminate):

```bash
   docker compose up -d --force-recreate
```

Se nella cartella `assets` è presente `foglio_viaggio_standard.pdf`, l'app
usa il tuo file; altrimenti usa quello di default incluso nell'immagine.

**Nota:** l'app scrive i dati in posizioni fisse del modulo, quindi il tuo PDF
deve mantenere la stessa struttura e le stesse dimensioni del foglio standard
(tabella, colonne e formato pagina): puoi cambiare l'intestazione, il logo o
altri elementi grafici, ma non la disposizione delle celle.
