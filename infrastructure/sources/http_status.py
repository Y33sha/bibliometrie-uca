"""Levée d'une erreur de statut sur une requête vers une source.

Plusieurs API de sources attendent leur identifiant en paramètre de requête : la clé OpenAlex, l'adresse annoncée à Unpaywall. Le message porte le seul statut, si bien qu'un appelant peut journaliser l'erreur telle quelle.

Les adapters qui l'attrapent lisent le statut sur la réponse ; le contexte de la requête — source et lot — vient du `label` que chaque appelant passe au helper HTTP.
"""

from __future__ import annotations

import httpx


def raise_for_status(response: httpx.Response) -> None:
    """Lève `httpx.HTTPStatusError` si le statut n'est pas un succès.

    Le type levé est celui d'httpx, que les adapters de sources attrapent nommément et dont ils lisent `response.status_code`. Le message porte le statut et sa phrase-raison.
    """
    if response.is_success:
        return
    raise httpx.HTTPStatusError(
        f"HTTP {response.status_code} {response.reason_phrase}",
        request=response.request,
        response=response,
    )
