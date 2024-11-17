# Database Dokumentasjon

## Oversikt
Systemet bruker SQLite-databaser for å lagre data. Hver funksjonalitet har sin egen databasefil under `database/` mappen.

## Databasestruktur

Feedback: Tabellen har kolonner som id, type, datetime, comment, innsender, status, og flere andre, med indekser på type, datetime, status, og innsender.
Login History: Tabellen har kolonner som id, user_id, login_time, og success, med indekser på user_id og login_time.
Strøing: Tabellen stroing_bestillinger har kolonner som id, bruker, bestillings_dato, onske_dato, kommentar, og status, med indekser på bruker, onske_dato, bestillings_dato, og status.
Tunbrøyting: Tabellen tunbroyting_bestillinger har kolonner som id, bruker, ankomst_dato, ankomst_tid, avreise_dato, avreise_tid, og abonnement_type, med indekser på bruker, ankomst_dato, avreise_dato, og abonnement_type.
Customer: Tabellen har kolonner som customer_id, lat, lon, subscription, type, og created_at, med indekser på customer_id og type.

### Customer Database (`customer.db`)
Lagrer kun informasjon om hyttenr, lat, long og abonnementstype.
sql
CREATE TABLE IF NOT EXISTS customer (
customer_id TEXT PRIMARY KEY,
lat REAL, -- Breddegrad
lon REAL, -- Lengdegrad
subscription TEXT, -- Abonnementstype (star_white, star_red, dot_white, admin)
type TEXT DEFAULT 'Customer', -- Kundetype (Customer, Admin, Other)
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)


Indekser:
- `idx_customer_id` på `customer_id`
- `idx_customer_type` på `type`

### Login History Database (`login_history.db`)
Sporer innloggingsforsøk.


### Login History Database (`login_history.db`)
Sporer innloggingsforsøk.

sql
CREATE TABLE IF NOT EXISTS login_history (
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id TEXT NOT NULL,
login_time TEXT NOT NULL,
success INTEGER NOT NULL DEFAULT 0
)

Indekser:
- `idx_login_user_id` på `user_id`
- `idx_login_time` på `login_time`

### Strøing Database (`stroing.db`)
Håndterer bestillinger for strøing.

sql
CREATE TABLE IF NOT EXISTS stroing_bestillinger (
id INTEGER PRIMARY KEY AUTOINCREMENT,
bruker TEXT,
bestillings_dato TEXT,
onske_dato TEXT,
kommentar TEXT,
status TEXT
)



Indekser:
- `idx_stroing_bruker` på `bruker`
- `idx_stroing_bestillings_dato` på `bestillings_dato`
- `idx_stroing_onske_dato` på `onske_dato`
- `idx_stroing_status` på `status`

### Tunbrøyting Database (`tunbroyting.db`)
Håndterer bestillinger for tunbrøyting.

sql
CREATE TABLE IF NOT EXISTS tunbroyting_bestillinger (
id INTEGER PRIMARY KEY,
bruker TEXT,
ankomst_dato DATE,
ankomst_tid TIME,
avreise_dato DATE,
avreise_tid TIME,
abonnement_type TEXT
)


Indekser:
- `idx_tunbroyting_bruker` på `bruker`
- `idx_tunbroyting_ankomst_dato` på `ankomst_dato`
- `idx_tunbroyting_avreise_dato` på `avreise_dato`
- `idx_tunbroyting_abonnement` på `abonnement_type`

### Feedback Database (`feedback.db`)
Håndterer tilbakemeldinger og varsler.

sql
CREATE TABLE IF NOT EXISTS feedback (
id INTEGER PRIMARY KEY,
type TEXT,
datetime TEXT,
comment TEXT,
innsender TEXT,
status TEXT,
status_changed_by TEXT,
status_changed_at TEXT,
hidden INTEGER DEFAULT 0,
is_alert INTEGER DEFAULT 0,
display_on_weather INTEGER DEFAULT 0,
expiry_date TEXT,
target_group TEXT
)


Indekser:
- `idx_feedback_type` på `type`
- `idx_feedback_datetime` på `datetime`
- `idx_feedback_status` på `status`
- `idx_feedback_innsender` på `innsender`

### Varsler i feedback-tabellen
Varsler lagres i feedback-tabellen med følgende felter:
- `is_alert`: Satt til 1 for varsler
- `type`: Starter med "Admin varsel:"
- `expiry_date`: Utløpsdato for varselet
- `target_group`: Målgruppe for varselet

## Migrasjoner
Databasemigrasjoner håndteres automatisk ved oppstart gjennom `utils/db/migrations.py`. 
Nye tabeller opprettes hvis de ikke eksisterer, og indekser oppdateres.

## Backup
*TODO: Dokumenter backup-rutiner*

## Feilsøking
Ved databasefeil, sjekk følgende:
1. At databasefilene eksisterer under `database/`
2. At alle tabeller har riktig struktur (bruk SQLite Browser)
3. Loggfiler for feilmeldinger under `logs/`

## Vedlikehold
*TODO: Dokumenter vedlikeholdsrutiner*
