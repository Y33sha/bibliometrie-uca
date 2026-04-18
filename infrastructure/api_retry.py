"""
Helper générique pour les requêtes HTTP avec retry + backoff exponentiel.

Encapsule le pattern commun aux extracteurs :
  - retry sur HTTP 429 (Too Many Requests)
  - retry sur les erreurs réseau (RequestException)
  - optionnellement retry sur body vide (certaines API comme WoS renvoient
    parfois un body vide sans 429, typiquement sous rate-limit silencieux)

Les scripts d'extraction utilisent ce module au lieu de dupliquer la logique.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)


def http_request_with_retry(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
    auth: tuple | None = None,
    timeout: int = 30,
    max_retries: int = 5,
    initial_backoff: float = 1.0,
    retry_on_empty_body: bool = False,
    label: str = "",
) -> dict:
    """Effectue une requête HTTP avec retry et backoff exponentiel.

    Stratégie :
      - status 429 → pause `initial_backoff * 2^attempt` puis retry
      - RequestException → pause puis retry (sauf au dernier essai, où on raise)
      - body vide (si retry_on_empty_body) → pause puis retry
      - autres erreurs HTTP → raise_for_status() immédiat
      - succès → retourne response.json()

    `label` : chaîne courte (ex: "year 2024, rec 100") insérée dans les
    logs pour distinguer les requêtes en parallèle.

    Lève la dernière exception rencontrée si max_retries est atteint sans
    succès (RequestException ou HTTPError).
    """
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
                raise
            logger.warning(
                f"Erreur réseau {label}: {e} — attente {wait}s (tentative {attempt + 1}/{max_retries})"
            )
            time.sleep(wait)

    logger.error(f"Échec après {max_retries} tentatives {label}")
    if last_error:
        raise last_error
    return {}
