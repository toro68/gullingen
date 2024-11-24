from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from utils.core.config import format_date, TZ

# Fargekonstanter
GREEN = "#03b01f"
RED = "#db0000"
GRAY = "#C0C0C0"
ORANGE = "#FFA500"

@dataclass
class MapBooking:
    """Representerer en tunbrøytingsbestilling for kartvisning"""
    customer_id: str
    ankomst_dato: datetime
    avreise_dato: Optional[datetime]
    abonnement_type: str
    is_active: bool = True
    
    def to_dict(self) -> dict:
        return {
            "customer_id": self.customer_id,
            "ankomst_dato": format_date(self.ankomst_dato, "display", "date"),
            "avreise_dato": format_date(self.avreise_dato, "display", "date") if self.avreise_dato else None,
            "abonnement_type": self.abonnement_type,
            "is_active": self.is_active
        }

    def get_marker_style(self, config) -> dict:
        """Returnerer markørstil for kartet"""
        if not self.is_active:
            return {
                "size": 8,
                "color": GRAY,
                "symbol": "circle"
            }
            
        # For aktive bestillinger
        if self.abonnement_type == "Årsabonnement":
            return {
                "size": 12,
                "color": GREEN,
                "symbol": "circle"
            }
        else:  # Ukentlig ved bestilling
            return {
                "size": 12,
                "color": RED,
                "symbol": "circle"
            }

    def is_active_for_date(self, current_date: datetime) -> bool:
        """Sjekker om bestillingen er aktiv for en gitt dato"""
        current_date = current_date.date()
        
        if self.abonnement_type == "Årsabonnement":
            return True
            
        arrival = self.ankomst_dato.date()
        departure = self.avreise_dato.date() if self.avreise_dato else None
        
        if departure:
            return arrival <= current_date <= departure
        return arrival == current_date

@dataclass
class ValidationResult:
    """Representerer resultatet av en validering"""
    is_valid: bool
    errors: List[str] = None
    warnings: List[str] = None
    data: Dict[str, Any] = None

    def __post_init__(self):
        self.errors = self.errors or []
        self.warnings = self.warnings or []
        self.data = self.data or {}

    def add_error(self, error: str):
        """Legger til en feilmelding"""
        if self.errors is None:
            self.errors = []
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str):
        """Legger til en advarsel"""
        if self.warnings is None:
            self.warnings = []
        self.warnings.append(warning)
