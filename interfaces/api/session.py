"""Session admin : émission, lecture et expiration du jeton, vérification du mot de passe.

Le jeton est un payload signé HMAC-SHA256 avec `session_secret`, de la forme `<payload>.<signature>`. Le format du payload — l'utilisateur et l'instant d'émission — ne sort pas de ce module : `issue_token` le compose, `read_session` le défait et rend l'utilisateur. Ses appelants ne connaissent que le jeton opaque et le nom qui en sort.

`routers/auth.py` émet le jeton à la connexion et le pose en cookie ; le middleware d'`app.py` le relit pour garder les écritures et nommer l'auteur des événements d'audit.
"""

import hashlib
import hmac
import time

import bcrypt

from infrastructure.settings import settings

SESSION_MAX_AGE = 86400 * 7  # 7 jours

_PAYLOAD_SEPARATOR = "|"


def _sign(payload: str) -> str:
    return hmac.new(settings.session_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue_token(admin_user: str) -> str:
    """Jeton de session signé pour `admin_user`, horodaté de l'instant d'émission."""
    payload = f"{admin_user}{_PAYLOAD_SEPARATOR}{int(time.time())}"
    return f"{payload}.{_sign(payload)}"


def read_session(token: str) -> str | None:
    """Utilisateur porté par un jeton, ou `None` si la signature ne tient pas, si la forme est illisible ou si `SESSION_MAX_AGE` est passé."""
    if not token or "." not in token:
        return None
    payload, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    admin_user, separator, issued_at = payload.rpartition(_PAYLOAD_SEPARATOR)
    if not separator:
        return None
    try:
        if time.time() - int(issued_at) > SESSION_MAX_AGE:
            return None
    except ValueError:
        return None
    return admin_user


def check_password(password: str) -> bool:
    """Confronte un mot de passe au hash bcrypt configuré. Sans hash configuré, aucune connexion n'aboutit."""
    if not settings.admin_hash:
        return False
    return bcrypt.checkpw(password.encode(), settings.admin_hash.encode())
