"""DTOs Auth — body de login et réponse du check de session.

Pas de port query associé : l'auth ne lit pas la DB, elle vérifie un cookie HMAC en mémoire (cf. `interfaces/api/deps.py`). Le router instancie directement.
"""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthCheckResponse(BaseModel):
    authenticated: bool
