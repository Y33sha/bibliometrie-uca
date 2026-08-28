"""Comparaison d'une URL à un domaine, par son hôte.

`is_host` analyse l'URL et confronte son hôte au domaine visé, sous-domaines compris. Une URL dépourvue de schéma est acceptée : `doi.org/10.1234/x` porte bien l'hôte `doi.org`.
"""

from urllib.parse import urlparse


def url_host(url: str | None) -> str | None:
    """Hôte de l'URL, en minuscules ; None quand l'URL n'en porte pas."""
    if not url:
        return None
    candidate = url.strip()
    if not candidate:
        return None
    if not urlparse(candidate).netloc:
        candidate = f"//{candidate}"
    try:
        return urlparse(candidate).hostname
    except ValueError:
        return None


def is_host(url: str | None, *domains: str) -> bool:
    """Vrai quand l'hôte de l'URL vaut l'un des `domains` ou en est un sous-domaine.

    Les domaines sont attendus en minuscules. `is_host("https://dx.doi.org/10.1234/x", "doi.org")` vaut vrai ; `is_host("https://exemple.fr/?ref=doi.org/10.1234/x", "doi.org")` vaut faux.
    """
    host = url_host(url)
    if not host:
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)
