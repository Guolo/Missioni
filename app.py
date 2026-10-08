import io
import os
import secrets
import sqlite3
import time
import zipfile
from datetime import datetime, date, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    g,
    send_file,
    flash,
    session,
    abort,
)
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "missioni.db")
SECRET_KEY_PATH = os.path.join(os.path.dirname(__file__), "data", "secret_key.txt")


def _carica_secret_key():
    """Usa SECRET_KEY dal .env se impostata; altrimenti ne genera una e la
    salva in data/secret_key.txt, così le sessioni restano valide anche
    dopo un riavvio del container (senza dover configurare nulla)."""
    valore = os.environ.get("SECRET_KEY", "").strip()
    if valore:
        return valore
    os.makedirs(os.path.dirname(SECRET_KEY_PATH), exist_ok=True)
    if os.path.exists(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH, "r", encoding="utf-8") as f:
            salvata = f.read().strip()
            if salvata:
                return salvata
    nuova = secrets.token_hex(32)
    with open(SECRET_KEY_PATH, "w", encoding="utf-8") as f:
        f.write(nuova)
    return nuova


app.secret_key = _carica_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Se l'app è servita in HTTPS (consigliato, essendo esposta su internet),
    # imposta SESSION_COOKIE_SECURE=true nel .env.
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").strip().lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)

# Elenco delle scuole, configurabile nel .env come lista separata da virgole
# (es. SCUOLE=cles,livo,rumo). Se non impostata, viene usato l'elenco
# predefinito.
SCUOLE = [
    s.strip().lower()
    for s in os.environ.get("SCUOLE", "cles,livo,rumo").split(",")
    if s.strip()
]

# Testo mostrato accanto al titolo "Missioni" (es. TITOLO=IC B. Clesio):
# sempre nella schermata di login, e da computer anche nelle altre pagine
# (nascosto sotto ai 640px per non sovrapporsi al menu). Se non impostato,
# resta semplicemente "Missioni".
TITOLO = os.environ.get("TITOLO", "").strip()

# Se false (SPECIFICA_ORARIO=false nel .env), l'ora di inizio e di fine non
# vengono stampate nel PDF esportato. Di default (anche se la variabile non
# è presente) sono attive.
SPECIFICA_ORARIO = os.environ.get("SPECIFICA_ORARIO", "true").strip().lower() != "false"

# Dati del dipendente, letti dal file .env. Ogni campo lasciato vuoto (non
# presente nel .env) non viene compilato nel PDF esportato.
DATI_DIPENDENTE = {
    "matricola": os.environ.get("MATRICOLA", "").strip(),
    "cognome_nome": os.environ.get("COGNOME_NOME", "").strip(),
    "qualifica": os.environ.get("QUALIFICA", "").strip(),
    "sede_servizio": os.environ.get("SEDE_SERVIZIO", "").strip(),
    "sede_domicilio": os.environ.get("SEDE_DOMICILIO", "").strip(),
}

# Codice luogo e mezzo proprio (vedi legenda del modulo): se non impostati
# nel .env restano vuoti e le relative celle non vengono compilate.
CODICE_LUOGO = os.environ.get("CODICE_LUOGO", "").strip()
MEZZO_PROPRIO = os.environ.get("MEZZO_PROPRIO", "").strip()

# Testo della colonna "Motivazione" di ogni missione esportata. Se troppo
# lungo, va a capo in automatico (e, se serve, il font si riduce). Se non
# impostato resta vuoto e la cella non viene compilata.
MOTIVAZIONE = os.environ.get("MOTIVAZIONE", "").strip()

# Il modulo PDF viene cercato prima in "assets/" (cartella che l'utente può
# montare come volume per usare un proprio modulo, con priorità); se il file
# non c'è, si usa quello di default incluso nell'immagine in "assets_default/".
_BASE_DIR = os.path.dirname(__file__)
_TEMPLATE_NOME = "foglio_viaggio_standard.pdf"
_TEMPLATE_UTENTE = os.path.join(_BASE_DIR, "assets", _TEMPLATE_NOME)
_TEMPLATE_DEFAULT = os.path.join(_BASE_DIR, "assets_default", _TEMPLATE_NOME)
TEMPLATE_PDF_PATH = (
    _TEMPLATE_UTENTE if os.path.isfile(_TEMPLATE_UTENTE) else _TEMPLATE_DEFAULT
)

# Coordinate della griglia del modulo "Foglio viaggio standard" (in punti,
# origine in alto a sinistra, come restituito da pdfplumber). Individuate
# analizzando le linee della tabella nel PDF originale.
PAGE_W, PAGE_H = 1191, 842

COLONNE_PDF = {
    "codice_luogo": (12.1, 52.3),
    "data": (52.3, 146.0),
    "tragitto": (146.0, 306.6),
}
COLONNE_PDF["ora_inizio"] = (601.0, 641.2)
COLONNE_PDF["ora_fine"] = (641.2, 681.3)
COLONNE_PDF["mezzo_proprio"] = (467.2, 507.3)
COLONNE_PDF["motivazione"] = (306.6, 467.2)

# Per ciascuno dei 3 blocchi della pagina, la coordinata Y (da pdfplumber)
# in cui termina l'intestazione delle colonne e inizia l'area dati, e la Y
# in cui termina l'intero blocco (usata per centrare verticalmente i campi
# che occupano l'intera altezza della cella: codice luogo, data, tragitto).
BLOCCHI_HEADER_BOTTOM = [183.5, 329.2, 474.9]
BLOCCHI_FULL_BOTTOM = [268.5, 414.2, 560.0]
RIGHE_PER_PAGINA = len(BLOCCHI_HEADER_BOTTOM)

FONT_CELLE_GRANDI = 17  # codice luogo, data, tragitto
FONT_CELLE_ORE = 11  # ora inizio, ora fine
PADDING_TRAGITTO = 8  # margine orizzontale per non toccare i bordi della cella tragitto
FONT_MOTIVAZIONE = 12  # dimensione massima del testo della motivazione
PADDING_MOTIVAZIONE = 8  # margine orizzontale nella cella motivazione
PADDING_VERTICALE_MOTIVAZIONE = 6  # margine verticale nella cella motivazione

# Coordinate (individuate con pdfplumber) della tabella di intestazione in
# cima alla pagina, con i dati del dipendente (Matricola, Cognome e Nome,
# Qualifica, Comune sede di servizio, Comune sede di Residenza/domicilio).
# "Mese e Anno" e "Codice Struttura" non vengono compilati.
COLONNE_INTESTAZIONE = {
    "mese_anno": (52.6, 173.1),
    "matricola": (173.1, 266.8),
    "cognome_nome": (266.8, 467.5),
    "qualifica": (467.5, 588.0),
    "sede_servizio": (654.9, 815.5),
    "sede_domicilio": (815.5, 976.2),
}
INTESTAZIONE_HEADER_BOTTOM = 62.4  # fine riga di etichette
INTESTAZIONE_FULL_BOTTOM = 110.2  # fine riga dati
FONT_INTESTAZIONE = 13
PADDING_INTESTAZIONE = 10  # margine orizzontale per non toccare i bordi cella

MESI_IT = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


def _centro_colonna(nome):
    x0, x1 = COLONNE_PDF[nome]
    return (x0 + x1) / 2


def _disegna_testo_adattato(c, testo, cx, cy, font_size_max, larghezza_max, font="Helvetica"):
    """Disegna testo centrato su (cx, cy), riducendo il font finché non
    entra in larghezza_max. Non disegna nulla se il testo è vuoto."""
    if not testo:
        return
    font_size = font_size_max
    while font_size > 6 and c.stringWidth(testo, font, font_size) > larghezza_max:
        font_size -= 0.5
    c.setFont(font, font_size)
    c.drawCentredString(cx, cy - font_size * 0.35, testo)


def _disegna_intestazione(c, mese_anno=""):
    """Compila i dati del dipendente in cima alla pagina, in base al .env,
    oltre al campo "Mese e Anno" (calcolato dalle missioni esportate)."""
    centro_verticale_top = (INTESTAZIONE_HEADER_BOTTOM + INTESTAZIONE_FULL_BOTTOM) / 2
    cy = PAGE_H - centro_verticale_top
    valori = dict(DATI_DIPENDENTE, mese_anno=mese_anno)
    for campo, (x0, x1) in COLONNE_INTESTAZIONE.items():
        cx = (x0 + x1) / 2
        larghezza_max = (x1 - x0) - PADDING_INTESTAZIONE
        _disegna_testo_adattato(
            c, valori.get(campo, ""), cx, cy, FONT_INTESTAZIONE, larghezza_max
        )


def _mese_anno_it(giorno):
    """Converte YYYY-MM-DD (o YYYY-MM) in 'Mese Anno', es. 'Settembre 2026'."""
    anno, mese = giorno.split("-")[:2]
    return f"{MESI_IT[int(mese) - 1].capitalize()} {anno}"


def _disegna_tragitto(c, cx, centro_verticale_top, testo, font="Helvetica"):
    """Disegna il tragitto (es. "Cles - Livo") centrato nella cella. Se il
    testo non entra su una riga, va a capo su tre righe (scuola / - /
    scuola); solo se anche così un nome di scuola non entra in larghezza,
    riduce il font finché non ci sta."""
    larghezza_max = (COLONNE_PDF["tragitto"][1] - COLONNE_PDF["tragitto"][0]) - PADDING_TRAGITTO

    # Prova su una sola riga, al font pieno.
    if c.stringWidth(testo, font, FONT_CELLE_GRANDI) <= larghezza_max:
        baseline_top = centro_verticale_top + FONT_CELLE_GRANDI * 0.35
        c.setFont(font, FONT_CELLE_GRANDI)
        c.drawCentredString(cx, PAGE_H - baseline_top, testo)
        return

    # Non entra su una riga: la spezza in scuola / - / scuola.
    if " - " in testo:
        parte_a, parte_b = testo.split(" - ", 1)
    else:
        parte_a, parte_b = testo, ""

    font_size = FONT_CELLE_GRANDI
    while font_size > 6 and (
        c.stringWidth(parte_a, font, font_size) > larghezza_max
        or c.stringWidth(parte_b, font, font_size) > larghezza_max
    ):
        font_size -= 0.5

    interlinea = font_size * 1.3
    c.setFont(font, font_size)
    baseline_centrale = centro_verticale_top + font_size * 0.35
    c.drawCentredString(cx, PAGE_H - (baseline_centrale - interlinea), parte_a)
    c.drawCentredString(cx, PAGE_H - baseline_centrale, "-")
    c.drawCentredString(cx, PAGE_H - (baseline_centrale + interlinea), parte_b)


def _spezza_parola(c, parola, font, font_size, larghezza_max):
    """Spezza una parola più larga della cella in più pezzi che ci stanno."""
    pezzi = []
    corrente = ""
    for carattere in parola:
        if corrente and c.stringWidth(corrente + carattere, font, font_size) > larghezza_max:
            pezzi.append(corrente)
            corrente = carattere
        else:
            corrente += carattere
    if corrente:
        pezzi.append(corrente)
    return pezzi


def _testo_a_capo(c, testo, font, font_size, larghezza_max):
    """Divide il testo in righe che entrano in larghezza_max, andando a capo
    tra le parole. Una singola parola troppo lunga viene spezzata."""
    righe = []
    corrente = ""
    for parola in testo.split():
        candidata = f"{corrente} {parola}".strip()
        if c.stringWidth(candidata, font, font_size) <= larghezza_max:
            corrente = candidata
            continue
        if corrente:
            righe.append(corrente)
            corrente = ""
        if c.stringWidth(parola, font, font_size) <= larghezza_max:
            corrente = parola
        else:
            pezzi = _spezza_parola(c, parola, font, font_size, larghezza_max)
            righe.extend(pezzi[:-1])
            corrente = pezzi[-1]
    if corrente:
        righe.append(corrente)
    return righe


def _disegna_motivazione(c, header_bottom, full_bottom, testo, font="Helvetica"):
    """Disegna la motivazione centrata (orizzontalmente e verticalmente) nella
    cella, andando a capo in automatico. Se anche così le righe non entrano
    in altezza, riduce il font finché non ci stanno."""
    if not testo:
        return
    x0, x1 = COLONNE_PDF["motivazione"]
    cx = (x0 + x1) / 2
    larghezza_max = (x1 - x0) - PADDING_MOTIVAZIONE
    altezza_max = (full_bottom - header_bottom) - PADDING_VERTICALE_MOTIVAZIONE

    font_size = FONT_MOTIVAZIONE
    while True:
        righe = _testo_a_capo(c, testo, font, font_size, larghezza_max)
        interlinea = font_size * 1.2
        if len(righe) * interlinea <= altezza_max or font_size <= 5:
            break
        font_size -= 0.5

    c.setFont(font, font_size)
    centro_top = (header_bottom + full_bottom) / 2
    altezza_blocco = len(righe) * interlinea
    # Baseline della prima riga (coordinate con origine in alto).
    primo_baseline_top = centro_top - altezza_blocco / 2 + font_size * 0.9
    for i, riga_testo in enumerate(righe):
        c.drawCentredString(cx, PAGE_H - (primo_baseline_top + i * interlinea), riga_testo)


def _disegna_riga(c, indice_blocco, riga):
    header_bottom = BLOCCHI_HEADER_BOTTOM[indice_blocco]
    full_bottom = BLOCCHI_FULL_BOTTOM[indice_blocco]

    # Campi grandi: centrati sia orizzontalmente che verticalmente
    # nell'intera altezza della cella (dall'intestazione al bordo inferiore).
    centro_verticale_top = (header_bottom + full_bottom) / 2
    baseline_top_grandi = centro_verticale_top + FONT_CELLE_GRANDI * 0.35
    y_grandi = PAGE_H - baseline_top_grandi
    c.setFont("Helvetica", FONT_CELLE_GRANDI)
    c.drawCentredString(_centro_colonna("codice_luogo"), y_grandi, str(riga.get("codice_luogo", "")))
    c.drawCentredString(_centro_colonna("data"), y_grandi, riga.get("data", ""))
    _disegna_tragitto(c, _centro_colonna("tragitto"), centro_verticale_top, riga.get("tragitto", ""))
    _disegna_motivazione(c, header_bottom, full_bottom, riga.get("motivazione", ""))

    # Ora inizio / ora fine: invariati, vicino alla riga di intestazione.
    # Se SPECIFICA_ORARIO è disattivata, non vengono stampati.
    baseline_top_ore = header_bottom + 14 + FONT_CELLE_ORE
    y_ore = PAGE_H - baseline_top_ore
    c.setFont("Helvetica", FONT_CELLE_ORE)
    if SPECIFICA_ORARIO:
        c.drawCentredString(_centro_colonna("ora_inizio"), y_ore, riga.get("ora_inizio", ""))
        c.drawCentredString(_centro_colonna("ora_fine"), y_ore, riga.get("ora_fine", ""))
    c.drawCentredString(_centro_colonna("mezzo_proprio"), y_ore, MEZZO_PROPRIO)


def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS esportazioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            creata_il TEXT NOT NULL   -- formato YYYY-MM-DD HH:MM:SS
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS missioni (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giorno TEXT NOT NULL,   -- formato YYYY-MM-DD
            ora TEXT NOT NULL,      -- formato HH:MM
            scuola TEXT NOT NULL,
            esportazione_id INTEGER REFERENCES esportazioni(id)
        )
        """
    )
    # Migrazione per database creati con versioni precedenti dell'app, che
    # non avevano ancora la colonna esportazione_id.
    colonne = [r[1] for r in conn.execute("PRAGMA table_info(missioni)").fetchall()]
    if "esportazione_id" not in colonne:
        conn.execute("ALTER TABLE missioni ADD COLUMN esportazione_id INTEGER REFERENCES esportazioni(id)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS utenti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        )
        """
    )
    # Utente predefinito al primo avvio: admin/admin. Va rinominato o
    # comunque va cambiata la password dalla pagina "Utenti" prima di
    # esporre l'app su internet.
    if conn.execute("SELECT COUNT(*) FROM utenti").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO utenti (username, password_hash) VALUES (?, ?)",
            ("admin", generate_password_hash("admin")),
        )

    conn.commit()
    conn.close()


@app.template_filter("data_it")
def data_it(value):
    """Converte YYYY-MM-DD in D/M/YYYY (senza zeri iniziali)."""
    d = datetime.strptime(value, "%Y-%m-%d")
    return f"{d.day}/{d.month}/{d.year}"


@app.template_filter("ora_it")
def ora_it(value):
    """Converte HH:MM in H.MM (senza zero iniziale sull'ora)."""
    h, m = value.split(":")
    return f"{int(h)}.{m}"


# ---------- Autenticazione, CSRF e blocco tentativi falliti ----------

TENTATIVI_LOGIN = {}
MAX_TENTATIVI = 5
BLOCCO_SECONDI = 5 * 60


def _ip_richiesta():
    intestazione = request.headers.get("X-Forwarded-For", "")
    if intestazione:
        return intestazione.split(",")[0].strip()
    return request.remote_addr or "sconosciuto"


def _login_bloccato(ip):
    tentativi = [t for t in TENTATIVI_LOGIN.get(ip, []) if time.time() - t < BLOCCO_SECONDI]
    TENTATIVI_LOGIN[ip] = tentativi
    return len(tentativi) >= MAX_TENTATIVI


def _registra_tentativo_fallito(ip):
    TENTATIVI_LOGIN.setdefault(ip, []).append(time.time())


def _azzera_tentativi(ip):
    TENTATIVI_LOGIN.pop(ip, None)


def login_required(view):
    """Richiede una sessione autenticata; altrimenti reindirizza al login."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def _csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


@app.context_processor
def _inserisci_csrf_token():
    return {"csrf_token": _csrf_token}


@app.context_processor
def _inserisci_titolo():
    return {"titolo": TITOLO}


@app.before_request
def _verifica_csrf():
    """Protegge tutte le richieste POST da CSRF: ogni form deve includere
    il campo nascosto csrf_token con lo stesso valore della sessione."""
    if request.method == "POST":
        atteso = session.get("csrf_token")
        ricevuto = request.form.get("csrf_token")
        if not atteso or not ricevuto or not secrets.compare_digest(atteso, ricevuto):
            abort(400)


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("index"))

    errore = None
    if request.method == "POST":
        ip = _ip_richiesta()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if _login_bloccato(ip):
            errore = "Troppi tentativi falliti. Riprova tra qualche minuto."
        else:
            db = get_db()
            utente = db.execute(
                "SELECT * FROM utenti WHERE username = ? COLLATE NOCASE", (username,)
            ).fetchone()
            if utente and check_password_hash(utente["password_hash"], password):
                _azzera_tentativi(ip)
                session.clear()
                session.permanent = True
                session["user_id"] = utente["id"]
                session["username"] = utente["username"]
                destinazione = request.form.get("next") or ""
                # Accetta solo percorsi interni all'app (mai un URL esterno).
                if not destinazione.startswith("/") or destinazione.startswith("//"):
                    destinazione = url_for("index")
                return redirect(destinazione)
            _registra_tentativo_fallito(ip)
            errore = "Nome utente o password non validi."

    return render_template(
        "login.html", errore=errore, next=request.args.get("next", "")
    )


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    db = get_db()
    missioni = db.execute(
        "SELECT * FROM missioni WHERE esportazione_id IS NULL "
        "ORDER BY giorno DESC, ora DESC"
    ).fetchall()
    oggi = date.today().isoformat()
    ora_attuale = datetime.now().strftime("%H:%M")
    return render_template(
        "index.html",
        missioni=missioni,
        scuole=SCUOLE,
        oggi=oggi,
        ora_attuale=ora_attuale,
    )


@app.route("/aggiungi", methods=["POST"])
@login_required
def aggiungi():
    giorno = request.form["giorno"]
    ora = request.form["ora"]
    scuola = request.form["scuola"]
    if scuola not in SCUOLE:
        return "Scuola non valida", 400
    db = get_db()
    db.execute(
        "INSERT INTO missioni (giorno, ora, scuola) VALUES (?, ?, ?)",
        (giorno, ora, scuola),
    )
    db.commit()
    flash(f"{scuola.capitalize()} · {ora}", "successo")
    return redirect(url_for("index"))


@app.route("/modifica/<int:missione_id>", methods=["POST"])
@login_required
def modifica(missione_id):
    db = get_db()
    giorno = request.form["giorno"]
    ora = request.form["ora"]
    scuola = request.form["scuola"]
    if scuola not in SCUOLE:
        return "Scuola non valida", 400
    db.execute(
        "UPDATE missioni SET giorno = ?, ora = ?, scuola = ? WHERE id = ?",
        (giorno, ora, scuola, missione_id),
    )
    db.commit()
    return redirect(url_for("index"))


@app.route("/elimina/<int:missione_id>", methods=["POST"])
@login_required
def elimina(missione_id):
    db = get_db()
    db.execute("DELETE FROM missioni WHERE id = ?", (missione_id,))
    db.commit()
    return redirect(url_for("index"))


def _etichetta_esportazione(creata_il, molteplice):
    """Etichetta 'del D/M/YYYY' per una cartella di esportazione; se nello
    stesso giorno ci sono più esportazioni, aggiunge l'ora per distinguerle."""
    data_label = data_it(creata_il[:10])
    if molteplice:
        return f"{data_label} {creata_il[11:16]}"
    return data_label


@app.route("/riepilogo")
@login_required
def riepilogo():
    db = get_db()

    righe_pendenti = db.execute(
        "SELECT * FROM missioni WHERE esportazione_id IS NULL "
        "ORDER BY giorno DESC, ora ASC"
    ).fetchall()
    accoppiate = _accoppia_per_giorno(righe_pendenti)
    giorni_ordinati = sorted(accoppiate.items(), key=lambda x: x[0], reverse=True)

    esportazioni_righe = db.execute(
        "SELECT e.id AS esportazione_id, e.creata_il AS creata_il, m.* "
        "FROM esportazioni e JOIN missioni m ON m.esportazione_id = e.id "
        "ORDER BY e.id DESC"
    ).fetchall()

    esportazioni = {}
    for r in esportazioni_righe:
        gruppo = esportazioni.setdefault(
            r["esportazione_id"], {"creata_il": r["creata_il"], "righe": []}
        )
        gruppo["righe"].append(r)

    conteggio_date = {}
    for gruppo in esportazioni.values():
        data_sola = gruppo["creata_il"][:10]
        conteggio_date[data_sola] = conteggio_date.get(data_sola, 0) + 1

    cartelle = []
    for eid in sorted(esportazioni.keys(), reverse=True):
        gruppo = esportazioni[eid]
        molteplice = conteggio_date[gruppo["creata_il"][:10]] > 1
        cartelle.append(
            {
                "id": eid,
                "etichetta": _etichetta_esportazione(gruppo["creata_il"], molteplice),
                "giorni": sorted(
                    _accoppia_per_giorno(gruppo["righe"]).items(), key=lambda x: x[0]
                ),
            }
        )

    return render_template(
        "riepilogo.html", giorni=giorni_ordinati, cartelle=cartelle
    )


@app.route("/reimporta/<int:esportazione_id>", methods=["POST"])
@login_required
def reimporta(esportazione_id):
    """Riporta le missioni di una cartella di esportazione allo stato
    precedente (non esportate) ed elimina la cartella, ormai vuota."""
    db = get_db()
    db.execute(
        "UPDATE missioni SET esportazione_id = NULL WHERE esportazione_id = ?",
        (esportazione_id,),
    )
    db.execute("DELETE FROM esportazioni WHERE id = ?", (esportazione_id,))
    db.commit()
    return redirect(url_for("riepilogo"))


@app.route("/elimina_esportazione/<int:esportazione_id>", methods=["POST"])
@login_required
def elimina_esportazione(esportazione_id):
    """Elimina definitivamente dal database le missioni di una cartella di
    esportazione, insieme alla cartella stessa."""
    db = get_db()
    db.execute("DELETE FROM missioni WHERE esportazione_id = ?", (esportazione_id,))
    db.execute("DELETE FROM esportazioni WHERE id = ?", (esportazione_id,))
    db.commit()
    return redirect(url_for("riepilogo"))


def _accoppia_per_giorno(righe):
    """Raggruppa le righe per giorno e le accoppia in ordine di ora
    (andata/ritorno). Restituisce un dict {giorno: [(a, b), ...]}, con
    b=None per l'ultima missione di un giorno con un numero dispari di
    missioni (coppia incompleta/spaiata)."""
    per_giorno = {}
    for m in righe:
        per_giorno.setdefault(m["giorno"], []).append(m)

    risultato = {}
    for giorno, missioni_giorno in per_giorno.items():
        ordinate = sorted(missioni_giorno, key=lambda r: r["ora"])
        coppie = []
        i = 0
        while i < len(ordinate):
            a = ordinate[i]
            b = ordinate[i + 1] if i + 1 < len(ordinate) else None
            coppie.append((a, b))
            i += 2
        risultato[giorno] = coppie
    return risultato


def _giorni_con_numero_dispari(righe):
    """Restituisce l'elenco ordinato dei giorni che hanno un numero dispari
    di missioni registrate, per cui l'accoppiamento andata/ritorno non
    torna e l'esportazione non può procedere."""
    conteggi = {}
    for m in righe:
        conteggi[m["giorno"]] = conteggi.get(m["giorno"], 0) + 1
    return sorted(g for g, n in conteggi.items() if n % 2 != 0)


def _costruisci_righe_esportazione(missioni):
    """Raggruppa le missioni per giorno e le accoppia due a due in tragitti
    (andata/ritorno). Presuppone che ogni giorno abbia un numero pari di
    missioni: va validato a monte con _giorni_con_numero_dispari."""
    accoppiate = _accoppia_per_giorno(missioni)
    righe = []
    for giorno in sorted(accoppiate.keys()):
        for a, b in accoppiate[giorno]:
            righe.append(
                {
                    "codice_luogo": CODICE_LUOGO,
                    "data": data_it(giorno),
                    "tragitto": f"{a['scuola'].capitalize()} - {b['scuola'].capitalize()}",
                    "motivazione": MOTIVAZIONE,
                    "ora_inizio": ora_it(a["ora"]),
                    "ora_fine": ora_it(b["ora"]),
                }
            )
    return righe


def _genera_pdf_esportazione(righe, mese_anno=""):
    writer = PdfWriter()
    gruppi = [
        righe[i : i + RIGHE_PER_PAGINA]
        for i in range(0, len(righe), RIGHE_PER_PAGINA)
    ] or [[]]

    for gruppo in gruppi:
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
        _disegna_intestazione(c, mese_anno)
        for indice, riga in enumerate(gruppo):
            _disegna_riga(c, indice, riga)
        c.showPage()
        c.save()
        buf.seek(0)

        overlay_reader = PdfReader(buf)
        pagina_base = PdfReader(TEMPLATE_PDF_PATH).pages[0]
        pagina_base.merge_page(overlay_reader.pages[0])
        writer.add_page(pagina_base)

    template_reader = PdfReader(TEMPLATE_PDF_PATH)
    if len(template_reader.pages) > 1:
        writer.add_page(template_reader.pages[1])

    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out


@app.route("/esporta", methods=["POST"])
@login_required
def esporta():
    db = get_db()
    missioni = db.execute(
        "SELECT * FROM missioni WHERE esportazione_id IS NULL "
        "ORDER BY giorno ASC, ora ASC"
    ).fetchall()

    if not missioni:
        flash("Non ci sono missioni da esportare.")
        return redirect(url_for("riepilogo"))

    giorni_dispari = _giorni_con_numero_dispari(missioni)
    if giorni_dispari:
        elenco = ", ".join(data_it(g) for g in giorni_dispari)
        flash(
            "Impossibile esportare: numero dispari di missioni nei giorni "
            f"{elenco}. Ogni giorno deve avere un numero pari di missioni "
            "(andata e ritorno)."
        )
        return redirect(url_for("riepilogo"))

    # Raggruppa le missioni da esportare per mese (YYYY-MM): ogni mese
    # genera un foglio viaggio separato, con il campo "Mese e Anno" compilato.
    per_mese = {}
    for m in missioni:
        chiave_mese = m["giorno"][:7]  # YYYY-MM
        per_mese.setdefault(chiave_mese, []).append(m)

    pdf_per_mese = {}
    for chiave_mese, missioni_mese in sorted(per_mese.items()):
        righe = _costruisci_righe_esportazione(missioni_mese)
        mese_anno = _mese_anno_it(chiave_mese)
        pdf_per_mese[chiave_mese] = _genera_pdf_esportazione(righe, mese_anno)

    # Solo dopo aver generato con successo i PDF, marca le missioni come
    # esportate raggruppandole in una nuova cartella di esportazione: non
    # verranno più riproposte tra quelle esportabili finché non vengono
    # reimportate o eliminate.
    creata_il = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute("INSERT INTO esportazioni (creata_il) VALUES (?)", (creata_il,))
    esportazione_id = cur.lastrowid
    db.executemany(
        "UPDATE missioni SET esportazione_id = ? WHERE id = ?",
        [(esportazione_id, m["id"]) for m in missioni],
    )
    db.commit()

    if len(pdf_per_mese) == 1:
        (chiave_mese, pdf_buf), = pdf_per_mese.items()
        nome_file = f"foglio_viaggio_{chiave_mese}.pdf"
        return send_file(
            pdf_buf,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=nome_file,
        )

    # Più mesi: raggruppa i singoli PDF in un unico archivio zip.
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for chiave_mese, pdf_buf in pdf_per_mese.items():
            zf.writestr(f"foglio_viaggio_{chiave_mese}.pdf", pdf_buf.read())
    zip_buf.seek(0)
    nome_file = f"fogli_viaggio_{date.today().isoformat()}.zip"
    return send_file(
        zip_buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=nome_file,
    )


@app.route("/utenti")
@login_required
def utenti():
    db = get_db()
    lista = db.execute("SELECT id, username FROM utenti ORDER BY username").fetchall()
    return render_template("utenti.html", utenti=lista)


@app.route("/utenti/aggiungi", methods=["POST"])
@login_required
def aggiungi_utente():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    if not username or not password:
        flash("Inserisci nome utente e password.")
    elif len(password) < 6:
        flash("La password deve avere almeno 6 caratteri.")
    else:
        db = get_db()
        esiste = db.execute(
            "SELECT 1 FROM utenti WHERE username = ? COLLATE NOCASE", (username,)
        ).fetchone()
        if esiste:
            flash(f"Esiste già un utente chiamato «{username}».")
        else:
            db.execute(
                "INSERT INTO utenti (username, password_hash) VALUES (?, ?)",
                (username, generate_password_hash(password)),
            )
            db.commit()
    return redirect(url_for("utenti"))


@app.route("/utenti/<int:utente_id>/password", methods=["POST"])
@login_required
def modifica_password_utente(utente_id):
    password = request.form.get("password", "")
    if len(password) < 6:
        flash("La password deve avere almeno 6 caratteri.")
    else:
        db = get_db()
        db.execute(
            "UPDATE utenti SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), utente_id),
        )
        db.commit()
        flash("Password aggiornata.")
    return redirect(url_for("utenti"))


@app.route("/utenti/<int:utente_id>/elimina", methods=["POST"])
@login_required
def elimina_utente(utente_id):
    db = get_db()
    totale = db.execute("SELECT COUNT(*) AS n FROM utenti").fetchone()["n"]
    if totale <= 1:
        flash("Non puoi eliminare l'unico utente rimasto.")
        return redirect(url_for("utenti"))

    db.execute("DELETE FROM utenti WHERE id = ?", (utente_id,))
    db.commit()

    if session.get("user_id") == utente_id:
        # L'utente ha eliminato se stesso: chiude la sessione.
        session.clear()
        return redirect(url_for("login"))
    return redirect(url_for("utenti"))


init_db()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "false").strip().lower() == "true"
    app.run(host="0.0.0.0", port=5000, debug=debug)
