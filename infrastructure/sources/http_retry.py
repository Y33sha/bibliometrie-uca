"""
Helper générique pour les requêtes HTTP avec retry + backoff exponentiel.

Encapsule le pattern commun aux extracteurs :
  - retry sur HTTP 429 (Too Many Requests)
  - retry sur les erreurs réseau (RequestException)
  - optionnellement retry sur body vide (certaines API comme WoS renvoient parfois un body vide sans 429, typiquement sous rate-limit silencieux)

Les scripts d'extraction utilisent ce module au lieu de dupliquer la logique.
"""

import logging
import time

import requests

from infrastructure.sources.circuit_breaker import get_current_breaker

logger = logging.getLogger(__name__)


def _counts_as_source_failure(error: Exception) -> bool:
    """Un échec qui suggère que la source est indisponible (budget/panne) : 5xx ou
    réseau/timeout. Les 4xx (404 « non trouvé »…) sont des résultats normaux, non
    comptés par le circuit-breaker."""
    if isinstance(error, requests.exceptions.HTTPError) and error.response is not None:
        return error.response.status_code >= 500
    return True


def http_request_with_retry(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
    auth: tuple | None = None,
    timeout: int = 30,
    max_retries: int = 3,
    initial_backoff: float = 1.0,
    retry_on_empty_body: bool = False,
    label: str = "",
) -> dict:
    """Effectue une requête HTTP avec retry et backoff exponentiel.

    Stratégie :
      - status 429 → pause `initial_backoff * 2^attempt` puis retry
      - RequestException → pause puis retry (sauf au dernier essai, où on raise)
      - body vide (si retry_on_empty_body) → pause puis retry
      - succès → retourne response.json()

    `max_retries=3` (2,4,8s avec backoff 2) : 3 tentatives suffisent, attendre 16
    ou 32s pour un document est inutile.

    Circuit-breaker : si un `SourceCircuitBreaker` est posé (ContextVar), on
    court-circuite quand il a tripé, on lui compte les échecs 429/5xx/réseau (pas
    les 4xx) et on le remet à zéro au succès.

    `label` : chaîne courte (ex: "year 2024, rec 100") insérée dans les logs.

    Lève la dernière exception rencontrée si max_retries est atteint sans succès.
    """
    breaker = get_current_breaker()
    if breaker is not None:
        breaker.check()  # court-circuite si la source a déjà tripé

    last_error: Exception | None = None
    for attempt in range(max_retries):
        wait = initial_backoff * (2**attempt)
        try:
            resp = requests.request(
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
                time.sleep(wait)
                continue
            resp.raise_for_status()
            if retry_on_empty_body and not resp.text.strip():
                logger.warning(
                    f"Body vide {label} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
                )
                time.sleep(wait)
                continue
            if breaker is not None:
                breaker.record_success()
            return resp.json()
        except requests.exceptions.JSONDecodeError as e:
            last_error = e
            logger.warning(
                f"JSON invalide {label} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            time.sleep(wait)
        except requests.RequestException as e:
            last_error = e
            if attempt == max_retries - 1:
                # HTTPError (4xx/5xx) ⊂ RequestException : seuls 5xx/réseau comptent.
                if breaker is not None and _counts_as_source_failure(e):
                    breaker.record_failure()
                raise
            logger.warning(
                f"Erreur réseau {label}: {e} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            time.sleep(wait)

    # Boucle épuisée : 429 répétés ou JSON invalide répété → échec source.
    if breaker is not None:
        breaker.record_failure()
    logger.error(f"Échec après {max_retries} tentatives {label}")
    if last_error:
        raise last_error
    return {}
