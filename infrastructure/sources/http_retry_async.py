"""
Helper générique pour les requêtes HTTP async avec retry + backoff exponentiel.

Variante async de `infrastructure.sources.http_retry.http_request_with_retry`, utilisée par les extracteurs et scripts du pipeline qui lancent plusieurs requêtes en parallèle via `asyncio.gather`.

Stratégie identique à la variante sync :
  - retry sur HTTP 429 (Too Many Requests)
  - retry sur les erreurs réseau (httpx.RequestError)
  - retry sur JSONDecodeError
  - optionnellement retry sur body vide

Le `httpx.AsyncClient` est passé en paramètre pour être partagé entre toutes les coroutines d'un même run (connexions HTTP poolées).
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx

from infrastructure.sources.circuit_breaker import get_current_breaker

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
    timeout: float = 30.0,  # noqa: ASYNC109 — wrapper httpx, le timeout est passé au client
    max_retries: int = 3,
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

    Circuit-breaker : si un `SourceCircuitBreaker` est posé (ContextVar, cf.
    `infrastructure.sources.circuit_breaker`), on court-circuite quand il a tripé
    (`SourceUnavailableError`), on lui compte les échecs 429/5xx/réseau et on le
    remet à zéro au succès. Les 4xx (404…) ne comptent pas (résultat normal).

    Lève la dernière exception rencontrée si max_retries est atteint.
    """
    breaker = get_current_breaker()
    if breaker is not None:
        breaker.check()  # court-circuite si la source a déjà tripé

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
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                # 5xx = source en panne → compte pour le breaker ; 4xx (404…) =
                # résultat normal (non trouvé), on ne compte pas. On propage dans
                # les deux cas (comportement inchangé).
                if breaker is not None and 500 <= resp.status_code < 600:
                    breaker.record_failure()
                raise
            if retry_on_empty_body and not resp.text.strip():
                logger.warning(
                    f"Body vide {label} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(wait)
                continue
            if breaker is not None:
                breaker.record_success()
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
                if breaker is not None:
                    breaker.record_failure()
                raise
            logger.warning(
                f"Erreur réseau {label}: {e} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            await asyncio.sleep(wait)

    # Boucle épuisée : 429 répétés ou JSON invalide répété → échec source.
    if breaker is not None:
        breaker.record_failure()
    logger.error(f"Échec après {max_retries} tentatives {label}")
    if last_error:
        raise last_error
    return {}
