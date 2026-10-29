"""Limiteurs de débit en mémoire, sur la connexion et sur les exports.

Fenêtre fixe par client : au plus `max_attempts` appels par `window_seconds`, puis 429. L'état vit dans le processus, un compteur par client, en défense en profondeur du plafond réseau du reverse-proxy.

Deux compteurs indépendants : un export refusé laisse la connexion possible. Sur la connexion, le plafond ralentit la recherche du mot de passe par essais. Sur les exports, il borne le coût d'une rafale ; le plafond de lignes borne celui d'un appel.
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

# Assez haut pour l'administration, qui se connecte en une ou deux tentatives ; assez bas pour rendre la force brute impraticable.
_LOGIN_MAX_ATTEMPTS = 10
_LOGIN_WINDOW_SECONDS = 300
# Un export se demande à la main : quelques-uns par séance de travail, jamais vingt en cinq minutes. Le plafond laisse passer l'usage humain et arrête la rafale.
_EXPORT_MAX_ATTEMPTS = 20
_EXPORT_WINDOW_SECONDS = 300
# Une navigation humaine procède par rafales : une page à facettes compose plusieurs dizaines d'appels, un aller-retour dans l'administration autant. Le plafond laisse passer ce rythme et borne le parcours automatique, qui l'enchaîne sans pause.
_READ_MAX_REQUESTS = 1200
_READ_WINDOW_SECONDS = 300
# Plafond du nombre de compteurs suivis : borne la mémoire même sous un flot d'adresses variées.
_MAX_KEYS = 4096
# Instant du dernier signalement, par pair de proxy non déclaré. Un déploiement qui oublie le réglage garde longtemps le symptôme : le signalement se répète, à intervalle espacé, et se trouve au journal le jour où la cause se cherche.
# La table est bornée comme celle des compteurs : sous un flot d'adresses variées, la plus anciennement signalée cède sa place.
_WARN_INTERVAL_SECONDS = 3600.0
_MAX_WARNED_PEERS = 64
_warned_peers: OrderedDict[str, float] = OrderedDict()


class FixedWindowRateLimiter:
    """Compteur à fenêtre fixe par clé, sans dépendance externe.

    Les compteurs sont rangés par ouverture de fenêtre, du plus ancien au plus récent ; une fenêtre qui repart passe en queue. La purge des fenêtres écoulées s'arrête ainsi au premier compteur vivant, et la place se fait en retirant le premier, dont la fenêtre expire avant les autres.

    Sous un flot d'adresses distinctes, le compteur d'un client peut partir avant la fin de sa fenêtre, et lui rendre ses tentatives : le plafond de mémoire prime sur l'exactitude. Le plafond du reverse-proxy reste la première défense.
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
        """Enregistre une tentative pour la clé, et rend vrai si elle reste sous le plafond."""
        now = self._clock()
        counter = self._hits.get(key)

        if counter is None:
            self._make_room(now)
            self._hits[key] = (now, 1)
            return 1 <= self._max

        start, count = counter
        if now - start >= self._window:
            # La fenêtre repart : le compteur passe en queue, derrière les fenêtres ouvertes avant la sienne ; le retirer d'abord le déplace.
            del self._hits[key]
            self._hits[key] = (now, 1)
            return 1 <= self._max

        # Fenêtre en cours : seul le décompte change, et réassigner une clé connue lui garde son rang.
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
    """Signale une requête qui contient un en-tête de proxy dont le serveur ASGI a écarté la valeur.

    Le `ProxyHeadersMiddleware` d'uvicorn réécrit l'adresse du client d'après `X-Forwarded-For` quand le pair de la connexion figure dans `FORWARDED_ALLOW_IPS`, et pose alors un port nul. Un en-tête avec un port non nul désigne donc un pair non déclaré : la vraie adresse du client se perd, et le plafond compte tous les clients ensemble.

    Le message nomme le pair, valeur à ajouter à `FORWARDED_ALLOW_IPS`. Il paraît au plus une fois par heure et par pair, tant que des requêtes de ce pair arrivent.
    """
    if "x-forwarded-for" not in request.headers or request.client is None:
        return
    if request.client.port == 0:
        return
    peer = request.client.host
    now = time.monotonic()
    dernier = _warned_peers.get(peer)
    if dernier is not None and now - dernier < _WARN_INTERVAL_SECONDS:
        return
    if dernier is None and len(_warned_peers) >= _MAX_WARNED_PEERS:
        _warned_peers.popitem(last=False)
    _warned_peers[peer] = now
    _warned_peers.move_to_end(peer)
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
    """Client identifié par l'adresse de connexion de la requête.

    Le serveur ASGI lit `X-Forwarded-For` en amont (`ProxyHeadersMiddleware` d'uvicorn) : seulement si le pair figure dans `FORWARDED_ALLOW_IPS`, de droite à gauche en écartant les proxys déclarés, et il réécrit l'adresse du client. Relire l'en-tête ici croirait une valeur que tout appelant compose : une valeur différente à chaque tentative ouvrirait un compteur neuf.

    Un réglage absent ou trop étroit se signale au journal (`_warn_if_proxy_header_ignored`). Sans proxy déclaré, l'adresse est celle du dernier maillon réseau : les clients derrière un même proxy partagent un compteur.
    """
    _warn_if_proxy_header_ignored(request)
    return request.client.host if request.client else "unknown"


def _rate_limited(limiter: FixedWindowRateLimiter, detail: str) -> Callable[[Request], None]:
    """Dépendance FastAPI qui rejette en 429 les appels qui dépassent le plafond du limiteur, par adresse IP."""

    def dependency(request: Request) -> None:
        if not limiter.allow(_client_key(request)):
            raise HTTPException(status_code=429, detail=detail)

    return dependency


def read_allowed(request: Request) -> bool:
    """Vrai tant que l'adresse du client reste sous le plafond de lectures.

    Sert le middleware qui couvre toutes les lectures ; les dépendances de route couvrent seulement les routes qui les déclarent.
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
# Un export garde ses lignes en mémoire tant que le corps part : la requête s'exécute d'un coup. Le plafond de lignes borne le coût d'un export, le plafond de fréquence celui d'une rafale d'un client ; celui-ci borne la mémoire du processus à un instant donné, quel que soit le nombre de clients.

_export_slots = threading.BoundedSemaphore(settings.max_concurrent_exports)


class ExportSlot:
    """Droit de mener un export, rendu quand son envoi s'achève.

    La restitution suit l'envoi, après la fin du traitement : la mémoire reste prise tant que le corps de la réponse part, et le cycle de vie des dépendances s'achève avant. `stream_owns` marque le passage de ce droit au flux, qui le rend alors lui-même.
    """

    def __init__(self) -> None:
        self._held_from: threading.BoundedSemaphore | None = None
        self.stream_owns = False

    def acquire(self) -> bool:
        """Prend un droit sans attendre. `False` si aucun n'est libre."""
        if _export_slots.acquire(blocking=False):
            self._held_from = _export_slots
        return self._held_from is not None

    def release(self) -> None:
        """Rend le droit au jeu dont il a été pris, une fois. Un second appel ne fait rien."""
        if self._held_from is not None:
            self._held_from.release()
            self._held_from = None


def export_slot() -> Iterator[ExportSlot]:
    """Dépendance FastAPI : réserve un droit d'export, ou rend 503.

    Le refus signale une indisponibilité passagère, d'où un statut distinct de celui du plafond de fréquence.

    À la sortie, le droit est rendu si le flux ne l'a pas repris : une erreur avant la construction de la réponse libère le droit, et un envoi en cours garde le sien.
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
    """Rétablit un jeu de droits neuf, au nombre que la configuration fixe (isolation entre tests)."""
    global _export_slots
    _export_slots = threading.BoundedSemaphore(settings.max_concurrent_exports)
