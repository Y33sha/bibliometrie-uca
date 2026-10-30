"""Erreur de statut d'une réponse de source.

Le message donne seulement le statut, sans l'URL, et se journalise tel quel : plusieurs API attendent un identifiant en paramètre de requête (clé OpenAlex, adresse annoncée à Unpaywall).
"""

from __future__ import annotations

import httpx2


def raise_for_status(response: httpx2.Response) -> None:
    """Lève `httpx2.HTTPStatusError` pour une réponse en échec, avec le statut et sa phrase-raison pour message."""
    if response.is_success:
        return
    raise httpx2.HTTPStatusError(
        f"HTTP {response.status_code} {response.reason_phrase}",
        request=response.request,
        response=response,
    )
