"""Comparaison d'une URL à un domaine, par son hôte."""

from urllib.parse import urlparse, urlsplit


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


def is_on_site(url: str, site: str) -> bool:
    """Vrai si l'URL est sur `site` : un domaine, éventuellement complété d'un début de chemin (`ncbi.nlm.nih.gov/pmc`). Le domaine vaut pour ses sous-domaines."""
    domain, _, path = site.partition("/")
    return is_host(url, domain) and (not path or urlsplit(url).path.lower().startswith(f"/{path}"))
