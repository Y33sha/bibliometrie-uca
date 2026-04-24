"""
Helper générique pour les requêtes HTTP async avec retry + backoff exponentiel.

Variante async de `infrastructure.api_retry.http_request_with_retry`,
utilisée par les extracteurs et scripts du pipeline qui lancent plusieurs
requêtes en parallèle via `asyncio.gather` (§2.14 du ROADMAP).

Stratégie identique à la variante sync :
  - retry sur HTTP 429 (Too Many Requests)
  - retry sur les erreurs réseau (httpx.RequestError)
  - retry sur JSONDecodeError
  - optionnellement retry sur body vide

Le `httpx.AsyncClient` est passé en paramètre pour être partagé entre
toutes les coroutines d'un même run (connexions HTTP poolées).
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx

logger = logging.getLogger(__name__)


async def http_request_with_retry_async(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
    auth: tuple | None = None,
    timeout: float = 30.0,
    max_retries: int = 5,
    initial_backoff: float = 1.0,
    retry_on_empty_body: bool = False,
    label: str = "",
) -> dict:
    """Effectue une requête HTTP async avec retry et backoff exponentiel.

    Stratégie :
      - status 429 → pause `initial_backoff * 2^attempt` puis retry
      - httpx.RequestError → pause puis retry (sauf au dernier essai, où on raise)
      - JSONDecodeError → pause puis retry
      - body vide (si retry_on_empty_body) → pause puis retry
      - autres erreurs HTTP → raise_for_status() immédiat
      - succès → retourne response.json()

    `label` : chaîne courte (ex: "DOI 10.xxx") insérée dans les logs
    pour distinguer les requêtes concurrentes.

    Lève la dernière exception rencontrée si max_retries est atteint.
    """
    last_error: Exception | None = None
    for attempt in range(max_retries):
        wait = initial_backoff * (2**attempt)
        try:
            resp = await client.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
                auth=auth,
                timeout=timeout,
            )
            if resp.status_code == 429:
                logger.warning(
                    f"429 Too Many Requests {label} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            if retry_on_empty_body and not resp.text.strip():
                logger.warning(
                    f"Body vide {label} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait)
                continue
            return resp.json()
        except json.JSONDecodeError as e:
            last_error = e
            logger.warning(
                f"JSON invalide {label} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            await asyncio.sleep(wait)
        except httpx.RequestError as e:
            last_error = e
            if attempt == max_retries - 1:
                raise
            logger.warning(
                f"Erreur réseau {label}: {e} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            await asyncio.sleep(wait)

    logger.error(f"Échec après {max_retries} tentatives {label}")
    if last_error:
        raise last_error
    return {}
