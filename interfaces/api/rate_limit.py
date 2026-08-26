"""Limiteurs de débit en mémoire, posés sur la connexion et sur les exports.

Fenêtre fixe par client : au plus `max_attempts` appels par `window_seconds`, au-delà l'appel rend 429. L'état vit dans le processus (un compteur par clé client), en défense en profondeur du rate limiting réseau du reverse-proxy.

Deux usages, deux compteurs indépendants — un export refusé ne doit pas empêcher de se connecter. Sur la connexion, le plafond ralentit le devinage de mot de passe. Sur les exports, il borne le coût d'une rafale : le plafond de lignes borne celui d'un appel, pas celui de mille.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable

from fastapi import HTTPException, Request

# Généreux pour ne pas gêner l'admin (une connexion tient en 1-2 tentatives), assez bas pour
# rendre le bruteforce impraticable.
_LOGIN_MAX_ATTEMPTS = 10
_LOGIN_WINDOW_SECONDS = 300
# Un export se demande à la main, en cliquant : quelques-uns par session de travail, jamais
# vingt en cinq minutes. Le plafond laisse passer l'usage humain et arrête la rafale.
_EXPORT_MAX_ATTEMPTS = 20
_EXPORT_WINDOW_SECONDS = 300
# Plafond du nombre de compteurs suivis : borne la mémoire même sous un flot d'adresses variées.
_MAX_KEYS = 4096


class FixedWindowRateLimiter:
    """Compteur à fenêtre fixe par clé, sans dépendance externe.

    Les compteurs sont rangés par ordre d'ouverture de fenêtre, du plus ancien au plus récent : une fenêtre qui repart passe en queue. Cet ordre sert deux fois — la purge des fenêtres écoulées s'arrête au premier compteur encore vivant, et faire de la place quand rien n'est écoulé revient à retirer le premier, dont la fenêtre allait de toute façon expirer avant les autres.

    L'éviction a un prix, assumé : sous un flot d'adresses distinctes, le compteur d'un client peut être retiré avant la fin de sa fenêtre, ce qui lui rend ses tentatives. Un plafond qui borne la mémoire ne peut pas en même temps garantir le suivi de tous les clients ; entre laisser la table croître sans fin et perdre en précision sous flot, la mémoire prime — le plafond de tentatives est une défense en profondeur, celle du reverse-proxy tient devant.
    """

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
        self._hits: OrderedDict[str, tuple[float, int]] = OrderedDict()

    def _discard_expired(self, now: float) -> None:
        """Retire les compteurs dont la fenêtre est écoulée.

        S'arrête au premier compteur encore vivant : l'ordre garantit que les suivants le sont aussi.
        """
        while self._hits:
            key, (start, _) = next(iter(self._hits.items()))
            if now - start < self._window:
                return
            del self._hits[key]

    def _make_room(self, now: float) -> None:
        """Ramène la table sous son plafond avant d'y ajouter un compteur."""
        if len(self._hits) < self._max_keys:
            return
        self._discard_expired(now)
        while self._hits and len(self._hits) >= self._max_keys:
            self._hits.popitem(last=False)

    def allow(self, key: str) -> bool:
        """Enregistre une tentative pour `key` et renvoie `True` si elle reste sous le plafond."""
        now = self._clock()
        counter = self._hits.get(key)

        if counter is None:
            self._make_room(now)
            self._hits[key] = (now, 1)
            return 1 <= self._max

        start, count = counter
        if now - start >= self._window:
            # La fenêtre repart : le compteur reprend son rang à la fin, derrière les fenêtres
            # ouvertes avant la sienne. Le retirer d'abord est ce qui le déplace.
            del self._hits[key]
            self._hits[key] = (now, 1)
            return 1 <= self._max

        # Fenêtre en cours : seul le décompte change, et réassigner une clé connue lui laisse
        # son rang — l'ordre des débuts de fenêtre est préservé sans rien déplacer.
        self._hits[key] = (start, count + 1)
        return count + 1 <= self._max

    def reset(self) -> None:
        """Vide l'état enregistré (tous les compteurs de fenêtre)."""
        self._hits.clear()


_login_limiter = FixedWindowRateLimiter(_LOGIN_MAX_ATTEMPTS, _LOGIN_WINDOW_SECONDS)
_export_limiter = FixedWindowRateLimiter(_EXPORT_MAX_ATTEMPTS, _EXPORT_WINDOW_SECONDS)


def reset_rate_limiters() -> None:
    """Vide les compteurs de tous les limiteurs (isolation entre tests)."""
    _login_limiter.reset()
    _export_limiter.reset()


def _client_key(request: Request) -> str:
    """Identifie le client par l'adresse de connexion portée par la requête.

    `X-Forwarded-For` n'est pas lu ici. Le serveur ASGI s'en charge en amont (`ProxyHeadersMiddleware` d'uvicorn) : il ne consulte l'en-tête que si le pair de la connexion figure dans `FORWARDED_ALLOW_IPS`, remonte la liste des maillons de droite à gauche en écartant les proxys déclarés, et réécrit l'adresse du client dans la requête. Le relire à ce niveau reviendrait à croire une valeur que tout appelant compose : une valeur différente à chaque tentative ouvrirait un compteur neuf, et le plafond ne retiendrait rien.

    Sans proxy déclaré, l'adresse est celle du dernier maillon réseau — les clients derrière un même proxy partagent alors un compteur.
    """
    return request.client.host if request.client else "unknown"


def _rate_limited(limiter: FixedWindowRateLimiter, detail: str) -> Callable[[Request], None]:
    """Dépendance FastAPI qui rejette en 429 les appels dépassant le plafond de `limiter`, par IP."""

    def dependency(request: Request) -> None:
        if not limiter.allow(_client_key(request)):
            raise HTTPException(status_code=429, detail=detail)

    return dependency


login_rate_limit = _rate_limited(
    _login_limiter, "Trop de tentatives de connexion. Réessayez plus tard."
)
export_rate_limit = _rate_limited(
    _export_limiter, "Trop d'exports demandés. Réessayez dans quelques minutes."
)
