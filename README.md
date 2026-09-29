# Missioni
Una semplice app per segnare le missioni tra una sede ed un altra di un Istituto Comprensivo in Trentino ed esportare le missioni con il modello standard provinciale Trentino

<img width="753" height="753" alt="Screenshot 2026-09-29 alle 17 02 20" src="https://github.com/user-attachments/assets/f4a0143c-34b9-42e1-add4-b27801878fcf" />

# Installation & Usage
Prerequisiti:  
[Docker](https://www.docker.com) and [Docker Compose](https://docs.docker.com/compose/) installed on your system.

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
  non vengono stampate nel PDF esportato. Se assente o impostata a
  qualsiasi altro valore, sono attive (comportamento predefinito).
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
