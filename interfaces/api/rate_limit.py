"""Limiteur de débit en mémoire, appliqué à l'endpoint de connexion (anti-bruteforce).

Fenêtre fixe par client : au plus `max_attempts` tentatives par `window_seconds`, au-delà l'appel rend 429. L'état vit dans le processus (un compteur par clé client) ; il suffit à ralentir le devinage de mot de passe sur l'unique compte admin, en défense en profondeur du rate limiting réseau du reverse-proxy.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import HTTPException, Request

# Généreux pour ne pas gêner l'admin (une connexion tient en 1-2 tentatives), assez bas pour
# rendre le bruteforce impraticable.
_MAX_ATTEMPTS = 10
_WINDOW_SECONDS = 300
# Plafond du nombre de clés suivies : borne la mémoire même sous un flot d'IP variées.
_MAX_KEYS = 4096


class FixedWindowRateLimiter:
    """Compteur à fenêtre fixe par clé, sans dépendance externe."""

    def __init__(
        self,
        max_attempts: int,
        window_seconds: float,
        *,
        max_keys: int = _MAX_KEYS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._hits: dict[str, tuple[float, int]] = {}

    def _prune(self, now: float) -> None:
        """Retire les fenêtres expirées ; borne la mémoire sous un flot de clés distinctes."""
        expired = [k for k, (start, _) in self._hits.items() if now - start >= self._window]
        for k in expired:
            del self._hits[k]

    def allow(self, key: str) -> bool:
        """Enregistre une tentative pour `key` et renvoie `True` si elle reste sous le plafond."""
        now = self._clock()
        if len(self._hits) >= self._max_keys:
            self._prune(now)
        start, count = self._hits.get(key, (now, 0))
        if now - start >= self._window:
            start, count = now, 0
        count += 1
        self._hits[key] = (start, count)
        return count <= self._max

    def reset(self) -> None:
        """Vide l'état enregistré (tous les compteurs de fenêtre)."""
        self._hits.clear()


_login_limiter = FixedWindowRateLimiter(_MAX_ATTEMPTS, _WINDOW_SECONDS)


def reset_login_limiter() -> None:
    """Réinitialise le limiteur de connexion global (isolation entre tests)."""
    _login_limiter.reset()


def _client_key(request: Request) -> str:
    """Identifie le client par IP : premier maillon de `X-Forwarded-For` (posé par le reverse-proxy) sinon IP de connexion directe."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def login_rate_limit(request: Request) -> None:
    """Dépendance FastAPI : rejette en 429 les tentatives de connexion au-delà du plafond par IP."""
    if not _login_limiter.allow(_client_key(request)):
        raise HTTPException(
            status_code=429, detail="Trop de tentatives de connexion. Réessayez plus tard."
        )
