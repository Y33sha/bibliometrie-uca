"""Comparaison d'une URL à un domaine, par son hôte."""

from urllib.parse import urlparse


def url_host(url: str | None) -> str | None:
    """Renvoie l'hôte de l'URL, en minuscules, ou `None`. Une URL sans schéma (`doi.org/10.1234/x`) est acceptée."""
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
    """Vrai si l'hôte de l'URL est l'un des `domains`, en minuscules, ou l'un de leurs sous-domaines."""
    host = url_host(url)
    if not host:
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)
