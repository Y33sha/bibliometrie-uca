"""Limiteurs de débit en mémoire, posés sur la connexion et sur les exports.

Fenêtre fixe par client : au plus `max_attempts` appels par `window_seconds`, au-delà l'appel rend 429. L'état vit dans le processus (un compteur par clé client), en défense en profondeur du rate limiting réseau du reverse-proxy.

Deux usages, deux compteurs indépendants — un export refusé ne doit pas empêcher de se connecter. Sur la connexion, le plafond ralentit le devinage de mot de passe. Sur les exports, il borne le coût d'une rafale : le plafond de lignes borne celui d'un appel, pas celui de mille.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator

from fastapi import HTTPException, Request

from infrastructure.settings import settings

logger = logging.getLogger(__name__)

# Généreux pour ne pas gêner l'admin (une connexion tient en 1-2 tentatives), assez bas pour
# rendre le bruteforce impraticable.
_LOGIN_MAX_ATTEMPTS = 10
_LOGIN_WINDOW_SECONDS = 300
# Un export se demande à la main, en cliquant : quelques-uns par session de travail, jamais
# vingt en cinq minutes. Le plafond laisse passer l'usage humain et arrête la rafale.
_EXPORT_MAX_ATTEMPTS = 20
_EXPORT_WINDOW_SECONDS = 300
# Une navigation humaine procède par rafales : une page à facettes compose plusieurs dizaines
# d'appels, et un aller-retour dans l'écran d'administration en enchaîne autant. Le plafond
# laisse passer ce rythme et borne le parcours automatique, qui l'enchaîne sans pause.
_READ_MAX_REQUESTS = 1200
_READ_WINDOW_SECONDS = 300
# Plafond du nombre de compteurs suivis : borne la mémoire même sous un flot d'adresses variées.
_MAX_KEYS = 4096
# Adresses déjà signalées comme pair de proxy non déclaré : un avertissement par adresse suffit.
# Bornée, comme la table des compteurs — sous un flot d'adresses variées, les suivantes se taisent.
_MAX_WARNED_PEERS = 64
_warned_peers: set[str] = set()


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
_read_limiter = FixedWindowRateLimiter(_READ_MAX_REQUESTS, _READ_WINDOW_SECONDS)


def reset_rate_limiters() -> None:
    """Vide les compteurs de tous les limiteurs et la mémoire des pairs signalés (isolation entre tests)."""
    _login_limiter.reset()
    _export_limiter.reset()
    _read_limiter.reset()
    _warned_peers.clear()


def _warn_if_proxy_header_ignored(request: Request) -> None:
    """Signale une requête portant un en-tête de proxy dont le serveur ASGI a écarté la valeur.

    `ProxyHeadersMiddleware` d'uvicorn réécrit l'adresse du client à partir de `X-Forwarded-For` quand le pair de la connexion figure dans `FORWARDED_ALLOW_IPS`, et pose alors un port nul — l'information étant perdue. Un en-tête présent en regard d'un port non nul désigne donc un pair que le serveur tient pour quelconque : la vraie adresse du client se perd, et le plafond de tentatives compte tous les clients dans un même seau.

    Le message nomme le pair, valeur à porter dans `FORWARDED_ALLOW_IPS`.
    """
    if "x-forwarded-for" not in request.headers or request.client is None:
        return
    if request.client.port == 0:
        return
    peer = request.client.host
    if peer in _warned_peers or len(_warned_peers) >= _MAX_WARNED_PEERS:
        return
    _warned_peers.add(peer)
    logger.warning(
        "proxy_headers_ignored",
        extra={
            "peer": peer,
            "detail": (
                f"Une requête porte X-Forwarded-For depuis {peer}, adresse absente de "
                "FORWARDED_ALLOW_IPS : le serveur écarte l'en-tête et le plafond de tentatives "
                f"compte tous les clients ensemble. Déclarer {peer} ou son réseau."
            ),
        },
    )


def _client_key(request: Request) -> str:
    """Identifie le client par l'adresse de connexion portée par la requête.

    `X-Forwarded-For` n'est pas lu ici. Le serveur ASGI s'en charge en amont (`ProxyHeadersMiddleware` d'uvicorn) : il ne consulte l'en-tête que si le pair de la connexion figure dans `FORWARDED_ALLOW_IPS`, remonte la liste des maillons de droite à gauche en écartant les proxys déclarés, et réécrit l'adresse du client dans la requête. Le relire à ce niveau reviendrait à croire une valeur que tout appelant compose : une valeur différente à chaque tentative ouvrirait un compteur neuf, et le plafond ne retiendrait rien.

    Un réglage absent ou trop étroit se signale au journal plutôt que de dégrader en silence (`_warn_if_proxy_header_ignored`).

    Sans proxy déclaré, l'adresse est celle du dernier maillon réseau — les clients derrière un même proxy partagent alors un compteur.
    """
    _warn_if_proxy_header_ignored(request)
    return request.client.host if request.client else "unknown"


def _rate_limited(limiter: FixedWindowRateLimiter, detail: str) -> Callable[[Request], None]:
    """Dépendance FastAPI qui rejette en 429 les appels dépassant le plafond de `limiter`, par IP."""

    def dependency(request: Request) -> None:
        if not limiter.allow(_client_key(request)):
            raise HTTPException(status_code=429, detail=detail)

    return dependency


def read_allowed(request: Request) -> bool:
    """Vrai tant que l'adresse du client reste sous le plafond de lectures.

    S'adresse au middleware qui couvre toutes les lectures, là où les dépendances de route ne couvrent que les points d'entrée qui les déclarent.
    """
    return _read_limiter.allow(_client_key(request))


login_rate_limit = _rate_limited(
    _login_limiter, "Trop de tentatives de connexion. Réessayez plus tard."
)
export_rate_limit = _rate_limited(
    _export_limiter, "Trop d'exports demandés. Réessayez dans quelques minutes."
)


# ── Simultanéité des exports ──────────────────────────────────────
#
# Un export compose sa réponse en mémoire avant de l'envoyer : la requête s'exécute d'un coup, et
# les lignes tiennent en mémoire tant que le corps part. Le plafond de lignes borne ce qu'un export
# coûte, le plafond de fréquence ce qu'une rafale coûte à un client ; celui-ci borne ce que le
# processus porte à un instant donné, quel que soit le nombre de clients.

_export_slots = threading.BoundedSemaphore(settings.max_concurrent_exports)


class ExportSlot:
    """Droit de mener un export, rendu quand son envoi s'achève.

    La restitution suit l'envoi et non la fin du traitement : la mémoire reste prise tant que le corps de la réponse part, et le cycle de vie des dépendances s'achève avant. `stream_owns` marque le passage de ce droit au flux, qui le rend alors lui-même.
    """

    def __init__(self) -> None:
        self._held = False
        self.stream_owns = False

    def acquire(self) -> bool:
        """Prend un droit sans attendre. `False` si aucun n'est libre."""
        self._held = _export_slots.acquire(blocking=False)
        return self._held

    def release(self) -> None:
        """Rend le droit, une fois. Un second appel ne fait rien."""
        if self._held:
            self._held = False
            _export_slots.release()


def export_slot() -> Iterator[ExportSlot]:
    """Dépendance FastAPI : réserve un droit d'export, ou rend 503.

    Le refus dit une indisponibilité passagère, non un quota dépassé — d'où un statut distinct de celui du plafond de fréquence.

    À la sortie, le droit n'est rendu que si le flux ne l'a pas repris : une erreur survenue avant la construction de la réponse ne doit pas immobiliser un droit, et un envoi en cours ne doit pas le voir disparaître sous lui.
    """
    slot = ExportSlot()
    if not slot.acquire():
        raise HTTPException(
            status_code=503,
            detail="Trop d'exports en cours. Réessayez dans un instant.",
            headers={"Retry-After": "30"},
        )
    try:
        yield slot
    finally:
        if not slot.stream_owns:
            slot.release()


def releasing(chunks: Iterator[str], slot: ExportSlot) -> Iterator[str]:
    """Parcourt les blocs d'un export et rend le droit quand le parcours s'achève, abandon compris."""
    slot.stream_owns = True
    try:
        yield from chunks
    finally:
        slot.release()


def reset_export_slots() -> None:
    """Rétablit un jeu de droits neuf, au nombre que la configuration porte (isolation entre tests)."""
    global _export_slots
    _export_slots = threading.BoundedSemaphore(settings.max_concurrent_exports)
