"""Écriture des URL sortantes sans les identifiants qu'elles portent.

Plusieurs API de sources attendent leur identifiant en paramètre de requête : la clé OpenAlex, l'adresse annoncée à Unpaywall. L'URL entière se retrouve alors dans le message de l'erreur que lève httpx sur un statut d'échec, et l'appelant qui journalise cette erreur écrit l'identifiant en clair — un 403 sur une clé révoquée suffit.

`redact_url` rend l'URL privée de la valeur de ses paramètres, en gardant leurs noms : elle dit ce qui a été demandé sans dire avec quoi. Retirer les valeurs toutes ensemble, plutôt que celles d'une liste de noms réputés sensibles, évite qu'un paramètre ajouté plus tard passe au travers.

`raise_for_status` remplace `httpx.Response.raise_for_status` sur le chemin des requêtes vers les sources : même exception, même statut, message assaini. C'est le seul endroit où naît une erreur de statut, donc le seul à devoir connaître cette précaution — les appelants journalisent l'exception telle quelle.
"""

from __future__ import annotations

import urllib.parse

import httpx

REDACTED = "***"


def redact_url(url: str | httpx.URL) -> str:
    """URL dont les valeurs des paramètres de requête, et l'information d'authentification de l'hôte s'il y en a une, sont remplacées par `***`."""
    parts = urllib.parse.urlsplit(str(url))

    netloc = parts.netloc
    if parts.username is not None:
        host = parts.hostname or ""
        netloc = f"{REDACTED}@{host}:{parts.port}" if parts.port else f"{REDACTED}@{host}"

    query = parts.query
    if query:
        names = [name for name, _ in urllib.parse.parse_qsl(query, keep_blank_values=True)]
        query = "&".join(f"{name}={REDACTED}" for name in names)

    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def raise_for_status(response: httpx.Response) -> None:
    """Lève `httpx.HTTPStatusError` si le statut n'est pas un succès, avec une URL assainie dans le message.

    Le type d'exception est celui d'httpx, que les adapters de sources attrapent nommément ; seul le message change. Il est composé ici plutôt que retouché après coup : un message d'httpx dont la forme évoluerait échapperait à une substitution, et emporterait l'identifiant avec lui.
    """
    if response.is_success:
        return
    raise httpx.HTTPStatusError(
        f"HTTP {response.status_code} {response.reason_phrase} sur {redact_url(response.url)}",
        request=response.request,
        response=response,
    )
