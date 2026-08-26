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

MIN_SESSION_SECRET_LENGTH = 32
"""Plancher de longueur de la clé de signature. `secrets.token_hex(32)`, la recette documentée, en rend 64 ; sous ce plancher, la clé se retrouve par force brute hors ligne et un jeton de session se forge alors sans connaître le mot de passe."""


def check_auth_config() -> None:
    """Refuse le démarrage de l'API sans de quoi authentifier une session d'administration.

    Le contrôle vit ici plutôt que dans les settings parce qu'il porte sur ce que l'API exerce : le pipeline et les scripts de maintenance lisent la même configuration sans jamais ouvrir de session, et n'ont donc pas à porter ces deux secrets. Le refus tombe au démarrage, où il se voit, et non à la première tentative de connexion.
    """
    if not settings.admin_hash:
        raise RuntimeError(
            "ADMIN_HASH est requis pour servir l'API : sans empreinte de mot de passe, aucune "
            "connexion d'administration n'aboutit et les écritures restent inaccessibles. "
            "Générer l'empreinte avec bcrypt (recette dans `.env.example`)."
        )
    if len(settings.session_secret) < MIN_SESSION_SECRET_LENGTH:
        raise RuntimeError(
            f"SESSION_SECRET doit faire au moins {MIN_SESSION_SECRET_LENGTH} caractères : il "
            "signe les jetons de session, et une clé plus courte se retrouve hors ligne. En "
            "tirer une avec `secrets.token_hex(32)` (recette dans `.env.example`)."
        )


def session_cookie_secure() -> bool:
    """Attribut `Secure` du cookie de session (transmis uniquement sur HTTPS), lu depuis la configuration."""
    return settings.cookie_secure


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
    """Confronte un mot de passe au hash bcrypt configuré. Sans hash configuré, ou si le hash est mal formé, aucune connexion n'aboutit.

    `bcrypt.checkpw` lève `ValueError` quand le hash n'est pas un hash bcrypt valide : un mauvais mot de passe reste un refus, pas une erreur serveur.
    """
    if not settings.admin_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode(), settings.admin_hash.encode())
    except ValueError:
        return False
