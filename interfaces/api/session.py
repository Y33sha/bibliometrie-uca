"""Session admin : émission, lecture et expiration du jeton, vérification du mot de passe.

Le jeton a la forme `<utilisateur>|<instant d'émission>.<signature>`, signé HMAC-SHA256 avec `session_secret`. Seul ce module connaît ce format.

`routers/auth.py` émet le jeton à la connexion et le pose en cookie ; `deps.py` le relit et cherche son utilisateur et ses rôles dans `ops.users`.
"""

import hashlib
import hmac
import time

import bcrypt

from infrastructure.settings import settings

SESSION_MAX_AGE = 86400 * 7  # 7 jours

MIN_SESSION_SECRET_LENGTH = 32
"""Longueur minimale de la clé de signature : une clé plus courte se retrouve par force brute hors ligne, et permet de forger un jeton."""


def check_auth_config() -> None:
    """Refuse le démarrage de l'API sans `ADMIN_HASH` ou avec un `SESSION_SECRET` trop court.

    Le contrôle est propre à l'API : le pipeline et les scripts lisent la même configuration sans ouvrir de session.
    """
    if not settings.admin_hash.get_secret_value():
        raise RuntimeError(
            "ADMIN_HASH est requis pour servir l'API : sans empreinte de mot de passe, aucune "
            "connexion d'administration n'aboutit et les écritures restent inaccessibles. "
            "Générer l'empreinte avec bcrypt (recette dans `.env.example`)."
        )
    if len(settings.session_secret.get_secret_value()) < MIN_SESSION_SECRET_LENGTH:
        raise RuntimeError(
            f"SESSION_SECRET doit faire au moins {MIN_SESSION_SECRET_LENGTH} caractères : il "
            "signe les jetons de session, et une clé plus courte se retrouve hors ligne. En "
            "tirer une avec `secrets.token_hex(32)` (recette dans `.env.example`)."
        )


def session_cookie_secure() -> bool:
    """Renvoie l'attribut `Secure` du cookie de session (transmis uniquement sur HTTPS), lu depuis la configuration."""
    return settings.cookie_secure


_PAYLOAD_SEPARATOR = "|"


def _sign(payload: str) -> str:
    key = settings.session_secret.get_secret_value().encode()
    return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()


def issue_token(admin_user: str) -> str:
    """Renvoie un jeton de session signé pour `admin_user`, horodaté de l'instant d'émission."""
    payload = f"{admin_user}{_PAYLOAD_SEPARATOR}{int(time.time())}"
    return f"{payload}.{_sign(payload)}"


def read_session(token: str) -> str | None:
    """Renvoie l'utilisateur du jeton, ou `None` si la signature est fausse, la forme illisible ou `SESSION_MAX_AGE` dépassé."""
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


def check_username(username: str) -> bool:
    """Confronte un nom d'utilisateur à celui configuré, en temps indépendant du nombre de caractères justes."""
    return hmac.compare_digest(username.encode(), settings.admin_user.encode())


def check_password(password: str) -> bool:
    """Confronte un mot de passe au hash bcrypt configuré. Sans hash, ou avec un hash mal formé (`ValueError` de `bcrypt.checkpw`), la réponse est un refus."""
    admin_hash = settings.admin_hash.get_secret_value()
    if not admin_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode(), admin_hash.encode())
    except ValueError:
        return False
