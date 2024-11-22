"""
Dependencies:
- Database: feedback
- Related modules: 
  - utils.services.feedback_utils
  - utils.services.alert_utils
- Shared tables:
  - feedback
"""

   # Felles kolonner
   - id
   - type
   - datetime
   - comment
   - customer_id
   - status
   - status_changed_by
   - status_changed_at
   - hidden

Hovedformål
Modulen håndterer all funksjonalitet relatert til tilbakemeldinger (feedback) i systemet, inkludert lagring, henting, visning og analyse av tilbakemeldinger.
Hovedkomponenter
Grunnleggende Feedback-håndtering

def save_feedback()  # Lagrer ny feedback i databasen
def get_feedback()   # Henter feedback fra databasen
def update_feedback_status()  # Oppdaterer status på eksisterende feedback
def delete_feedback()  # Sletter feedback fra databasen

Vedlikeholdsreaksjoner
def save_maintenance_reaction()  # Lagrer reaksjoner på vedlikehold (😊, 😐, 😡)
def get_maintenance_reactions()  # Henter vedlikeholdsreaksjoner
def calculate_maintenance_stats()  # Beregner statistikk for vedlikeholdsreaksjoner

Visningskomponenter
def display_feedback_dashboard()  # Viser dashboard med feedback-oversikt
def display_maintenance_summary()  # Viser sammendrag av vedlikeholdsreaksjoner
def display_reaction_statistics()  # Viser statistikk over reaksjoner
def display_daily_maintenance_rating()  # Viser daglig vurderingsskjema

Nøkkelfunksjoner
Støtter ulike typer feedback (Avvik, Generell tilbakemelding, Forslag)
Håndterer tidssoner og datoformatering
Tilbyr eksport av data (CSV, Excel)
Genererer visualiseringer og statistikk
Støtter filtrering og sortering av feedback
Integrerer med strøing-modulen for spesifikk feedback
Datastruktur
Feedback lagres med følgende hovedfelter:
id
type
datetime
comment
customer_id
status
status_changed_by
status_changed_at
hidden
Avhengigheter
Database: feedback
Moduler:
utils.services.feedback_utils
utils.services.alert_utils
Eksterne biblioteker: pandas, plotly, streamlit