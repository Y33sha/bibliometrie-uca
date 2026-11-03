"""Comparaison d'une URL à un domaine, par son hôte. Fragments d'en-tête HTTP `Link`."""

import re
from urllib.parse import urlparse, urlsplit

_LINK_HEADER_END = re.compile(r">[,;]?\s*$")
"""Fin d'une adresse dans un en-tête HTTP `Link` : `<https://orcid.org/…>; rel="author"`."""


def is_link_header_fragment(url: str) -> bool:
    """Vrai si `url` est une adresse recopiée d'un en-tête HTTP `Link`, avec le `>` qui la ferme. Elle désigne une page liée au document : profil d'un auteur, page de navigation d'un entrepôt."""
    return bool(_LINK_HEADER_END.search(url))


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


def _host_in(host: str, domain: str) -> bool:
    """Vrai si `host` est `domain` ou l'un de ses sous-domaines."""
    return host == domain or host.endswith(f".{domain}")


def is_host(url: str | None, *domains: str) -> bool:
    """Vrai si l'hôte de l'URL est l'un des `domains`, en minuscules, ou l'un de leurs sous-domaines."""
    host = url_host(url)
    if not host:
        return False
    return any(_host_in(host, domain) for domain in domains)


def is_on_site(url: str, site: str) -> bool:
    """Vrai si l'URL est sur `site` : un domaine, éventuellement complété d'un début de chemin (`ncbi.nlm.nih.gov/pmc`). Le domaine vaut pour ses sous-domaines."""
    return on_site(url_host(url), urlsplit(url).path, site)


def on_site(host: str | None, path: str, site: str) -> bool:
    """Vrai si l'URL d'hôte `host` (`url_host`) et de chemin `path` (`urlsplit`) est sur `site`, comme `is_on_site`. Sert à comparer une URL analysée une fois à plusieurs sites."""
    if not host:
        return False
    domain, _, site_path = site.partition("/")
    return _host_in(host, domain) and (not site_path or path.lower().startswith(f"/{site_path}"))
