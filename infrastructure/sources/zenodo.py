"""Adapter HTTP pour `application.ports.pipeline.zenodo_resolver.ZenodoResolver`.

Le format des DOI Zenodo et l'erreur du contrat sont dans `domain.sources.zenodo`.
"""

import os
import time

import requests

from domain.sources.zenodo import ZENODO_DOI_RE, ZenodoResolutionError
from infrastructure.observability.log import setup_logger
from infrastructure.sources.api_limits import ZENODO_DELAY

logger = setup_logger("zenodo", os.path.join(os.path.dirname(__file__), "logs"))

_MAX_RETRIES = 3
_INITIAL_BACKOFF = 2  # secondes
_last_request_time = 0.0


class HttpZenodoResolver:
    """Adapter HTTP pour `application.ports.pipeline.zenodo_resolver.ZenodoResolver`.

    L'URL de base de l'API est injectée au constructeur (12-factor : les
    backing services sont paramétrés par config, pas par constante en
    dur). Les call sites récupèrent la valeur depuis
    `get_api_base_urls(cur)["zenodo"]`.
    """

    def __init__(self, api_base: str) -> None:
        self._api_base = api_base

    def resolve_concept_doi(self, doi: str) -> str | None:
        return resolve_zenodo_concept_doi(doi, api_base=self._api_base)


def _fetch_zenodo_record(doi: str, *, api_base: str) -> dict[str, object] | None:
    """Récupère le record JSON de l'API Zenodo pour un DOI.

    Retourne `None` si le DOI n'est pas un DOI Zenodo ou si le record est
    introuvable/supprimé (404, 410). Lève `ZenodoResolutionError` en cas
    d'erreur temporaire (429 épuisé, timeout, autre statut), pour que
    l'appelant puisse décider de retenter plus tard. Délai de politesse +
    retry avec backoff exponentiel sur 429.
    """
    match = ZENODO_DOI_RE.search(doi)
    if not match:
        return None

    record_id = match.group(1)
    backoff = _INITIAL_BACKOFF

    global _last_request_time
    for attempt in range(_MAX_RETRIES):
        try:
            elapsed = time.time() - _last_request_time
            if elapsed < ZENODO_DELAY:
                time.sleep(ZENODO_DELAY - elapsed)

            resp = requests.get(f"{api_base}/{record_id}", timeout=10, allow_redirects=True)
            _last_request_time = time.time()
            if resp.status_code == 429:
                wait = backoff * (2**attempt)
                logger.info(f"Zenodo 429 pour {doi}, attente {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code in (410, 404):
                logger.warning(f"Zenodo API {resp.status_code} pour {doi}")
                return None

            if resp.status_code != 200:
                logger.warning(f"Zenodo API {resp.status_code} pour {doi}")
                raise ZenodoResolutionError(f"HTTP {resp.status_code}")

            return resp.json()

        except requests.exceptions.RequestException as e:
            logger.warning(f"Erreur API Zenodo pour {doi}: {e}")
            raise ZenodoResolutionError(str(e)) from e

    logger.warning(f"Zenodo API : abandon après {_MAX_RETRIES} tentatives pour {doi}")
    raise ZenodoResolutionError(f"rate-limited après {_MAX_RETRIES} tentatives")


def resolve_zenodo_concept_doi(doi: str, *, api_base: str) -> str | None:
    """Résout un DOI Zenodo (concept ou version) vers son concept DOI.

    Lit le champ `conceptdoi` du record (l'identifiant stable, agnostique aux
    versions). Retourne `None` si le record n'expose pas de concept DOI (dépôt
    non versionné) ou si le DOI n'est pas un DOI Zenodo. Lève
    `ZenodoResolutionError` en cas d'erreur temporaire (rate-limit, timeout).
    """
    data = _fetch_zenodo_record(doi, api_base=api_base)
    if data is None:
        return None
    concept = data.get("conceptdoi")
    return concept if isinstance(concept, str) and concept else None
