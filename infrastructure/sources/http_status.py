"""Levée d'une erreur de statut sur une requête vers une source, sans exposer la requête.

Plusieurs API de sources attendent leur identifiant en paramètre de requête : la clé OpenAlex, l'adresse annoncée à Unpaywall. Le message que compose `httpx.Response.raise_for_status` porte l'URL entière, paramètres compris, et l'appelant qui journalise l'erreur écrit l'identifiant en clair — un 403 sur une clé révoquée suffit.

Le message se réduit donc au statut. Rien n'est perdu : les adapters qui attrapent l'erreur lisent le statut sur la réponse et n'ont jamais regardé le message, et les trois endroits qui le journalisent écrivent déjà de quelle source et de quel lot il s'agit — le nom d'hôte n'y ajoute rien, et le chemin pas davantage, chaque appelant passant un `label` qui situe sa requête.
"""

from __future__ import annotations

import httpx


def raise_for_status(response: httpx.Response) -> None:
    """Lève `httpx.HTTPStatusError` si le statut n'est pas un succès.

    Remplace la méthode d'httpx sur le chemin des requêtes vers les sources. Le type levé est le sien, que les adapters attrapent nommément et dont ils lisent `response.status_code` ; seul le message change.
    """
    if response.is_success:
        return
    raise httpx.HTTPStatusError(
        f"HTTP {response.status_code} {response.reason_phrase}",
        request=response.request,
        response=response,
    )
