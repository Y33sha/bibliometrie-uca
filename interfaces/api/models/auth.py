"""Re-export des DTOs Auth.

Les modèles vivent désormais dans `application.auth.dtos` (chantier `CODE_typage-projections-strict` Phase 4 : sweep DTO par feature). Ce module reste pour les imports historiques `from interfaces.api.models import LoginRequest, AuthCheckResponse`.
"""

from application.auth.dtos import AuthCheckResponse, LoginRequest

__all__ = ["AuthCheckResponse", "LoginRequest"]
