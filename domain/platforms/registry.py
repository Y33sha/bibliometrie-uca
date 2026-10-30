"""Liste fermée des plateformes connues : archives ouvertes, serveurs de preprints et plateformes d'éditeurs. Une plateforme reconnue prend le nom de la liste."""

from dataclasses import dataclass
from urllib.parse import urlsplit

from domain.platforms.platform import PlatformType
from domain.publications.identifiers import clean_doi, is_hal_host
from domain.source_records.identifiers import SourceIdentifierType
from domain.urls import is_host, url_host


@dataclass(frozen=True, slots=True)
class KnownPlatform:
    """Plateforme de la liste fermée."""

    name: str
    platform_type: PlatformType
    doi_prefixes: frozenset[str] = frozenset()
    openalex_ids: tuple[str, ...] = ()
    """Sources OpenAlex, la principale en tête."""
    hosts: tuple[str, ...] = ()
    """Hôtes de la plateforme. Un hôte vaut pour ses sous-domaines. Il peut se compléter d'un début de chemin (`ncbi.nlm.nih.gov/pmc`)."""


def _preprint_server(
    name: str, prefixes: set[str], openalex_ids: tuple[str, ...], hosts: tuple[str, ...] = ()
) -> KnownPlatform:
    return KnownPlatform(
        name, PlatformType.PREPRINT_SERVER, frozenset(prefixes), openalex_ids, hosts
    )


def _publisher_platform(
    name: str, prefixes: set[str], openalex_ids: tuple[str, ...] = (), hosts: tuple[str, ...] = ()
) -> KnownPlatform:
    return KnownPlatform(
        name, PlatformType.PUBLISHER_PLATFORM, frozenset(prefixes), openalex_ids, hosts
    )


def _repository(
    name: str, openalex_ids: tuple[str, ...], hosts: tuple[str, ...] = ()
) -> KnownPlatform:
    return KnownPlatform(name, PlatformType.REPOSITORY, openalex_ids=openalex_ids, hosts=hosts)


HAL = _repository(
    "HAL", ("S4306402512", "S4406922276", "S4406922393", "S4406922470", "S4377196329")
)
"""L'archive ouverte HAL. OpenAlex range aussi des copies de HAL sous des sources de portails. Ses hôtes sont les portails HAL (`is_hal_host`)."""

PUBMED_CENTRAL = _repository(
    "PubMed Central",
    ("S2764455111", "S4306400806"),
    ("ncbi.nlm.nih.gov/pmc", "pmc.ncbi.nlm.nih.gov", "europepmc.org"),
)
"""L'archive de PubMed Central, que désigne aussi l'identifiant PMCID d'un document. La source OpenAlex de son miroir Europe PMC donne surtout des adresses de PubMed Central."""

ZENODO = _repository("Zenodo", ("S4306400562",), ("zenodo.org",))
"""L'archive ouverte Zenodo, du CERN."""

ARXIV = _preprint_server("arXiv", {"10.48550"}, ("S4306400194", "S4393918464"), ("arxiv.org",))
"""Le serveur de preprints arXiv, que désigne aussi l'identifiant arXiv d'un document."""

KNOWN_PLATFORMS: tuple[KnownPlatform, ...] = (
    HAL,
    PUBMED_CENTRAL,
    ZENODO,
    _repository("Figshare", ("S4377196282",), ("figshare.com",)),
    _repository("CERN Document Server", ("S4306402195",), ("cds.cern.ch",)),
    ARXIV,
    # Le préfixe 10.1101 couvre aussi les revues de Cold Spring Harbor (*Genome Research*).
    _preprint_server("bioRxiv", {"10.1101", "10.64898"}, ("S4306402567",), ("biorxiv.org",)),
    _preprint_server("medRxiv", {"10.1101", "10.64898"}, ("S3005729997",), ("medrxiv.org",)),
    _preprint_server("SSRN", {"10.2139"}, ("S4210172589",), ("ssrn.com",)),
    _preprint_server(
        "Research Square", {"10.21203"}, ("S4306525896", "S4306402450"), ("researchsquare.com",)
    ),
    _preprint_server("Preprints.org", {"10.20944"}, ("S6309402219",), ("preprints.org",)),
    _preprint_server("ChemRxiv", {"10.26434"}, ("S4393918830",), ("chemrxiv.org",)),
    _preprint_server("Authorea", {"10.22541"}, ("S4363604296",), ("authorea.com",)),
    # Les URL d'osf.io désignent plusieurs serveurs de preprints sans les distinguer : seule la source OpenAlex les départage.
    _preprint_server("OSF Preprints", {"10.31219"}, ("S4306401127",)),
    _preprint_server("PsyArXiv", {"10.31234"}, ("S4306401687",)),
    _preprint_server("SocArXiv", {"10.31235"}, ("S4306401238",)),
    _preprint_server(
        "EarthArXiv", {"10.31223"}, ("S4306401273", "S4306402614"), ("eartharxiv.org",)
    ),
    _preprint_server("AfricArXiv", set(), ("S4306402219",)),
    _preprint_server("BioHackrXiv", set(), ("S4306402587",)),
    _preprint_server("MindRxiv", set(), ("S4306401745",)),
    _preprint_server("ECSarXiv", set(), ("S4306402531",)),
    _preprint_server("SportRxiv", set(), ("S4306402352",)),
    _preprint_server("Arabixiv", set(), ("S4306400047",)),
    _preprint_server("EdArXiv", set(), ("S4306402530",)),
    _preprint_server("EcoEvoRxiv", set(), ("S4306402488",)),
    _publisher_platform("Cairn", {"10.3917"}, hosts=("cairn.info",)),
    _publisher_platform(
        "OpenEdition",
        {"10.4000"},
        ("S4306402281", "S4306401026"),
        ("openedition.org", "calenda.org", "hypotheses.org"),
    ),
    _publisher_platform("Érudit", {"10.7202"}, hosts=("erudit.org",)),
    _publisher_platform("Persée", {"10.3406"}, hosts=("persee.fr",)),
    _publisher_platform(
        "SciELO", {"10.1590", "10.4067", "10.7476"}, hosts=("scielo.br", "scielo.org", "scielo.cl")
    ),
    _publisher_platform("Prairial", {"10.35562"}),
    _publisher_platform("Episciences", {"10.46298", "10.23638"}, hosts=("episciences.org",)),
    _publisher_platform("Centre Mersenne", {"10.5802"}, hosts=("centre-mersenne.org",)),
    _publisher_platform("Project MUSE", {"10.1353"}, hosts=("muse.jhu.edu",)),
    _publisher_platform("Université de Bordeaux", {"10.20870"}),
)

PMC_ARTICLE_URL = "https://www.ncbi.nlm.nih.gov/pmc/articles/{}/"
"""Page d'un article de PubMed Central, à compléter par son PMCID."""

IDENTIFIER_COPIES: dict[SourceIdentifierType, str] = {
    SourceIdentifierType.ARXIV_ID: "https://arxiv.org/abs/{}",
    SourceIdentifierType.PMCID: PMC_ARTICLE_URL,
}
"""Copie ouverte que désigne un identifiant de document : URL à compléter par sa valeur, par type d'identifiant."""

_BY_OPENALEX_ID = {i: p for p in KNOWN_PLATFORMS for i in p.openalex_ids}
_PUBLISHER_PLATFORM_PREFIXES = frozenset(
    prefix
    for p in KNOWN_PLATFORMS
    if p.platform_type is PlatformType.PUBLISHER_PLATFORM
    for prefix in p.doi_prefixes
)
_PLATFORMS_OF_PREFIX: dict[str, list[KnownPlatform]] = {}
for _platform in KNOWN_PLATFORMS:
    for _prefix in _platform.doi_prefixes:
        _PLATFORMS_OF_PREFIX.setdefault(_prefix, []).append(_platform)
# Préfixe DOI d'une seule plateforme.
_BY_PREFIX = {prefix: ps[0] for prefix, ps in _PLATFORMS_OF_PREFIX.items() if len(ps) == 1}


def known_platform_of_source(openalex_id: str) -> KnownPlatform | None:
    """Renvoie la plateforme de la liste dont `openalex_id` est une source OpenAlex."""
    return _BY_OPENALEX_ID.get(openalex_id)


def _matches(url: str, host: str) -> bool:
    domain, _, path = host.partition("/")
    return is_host(url, domain) and (not path or urlsplit(url).path.lower().startswith(f"/{path}"))


def known_platform_of_url(url: str) -> KnownPlatform | None:
    """Renvoie la plateforme de la liste désignée par `url` : par son hôte, à défaut par le préfixe d'une URL doi.org propre à une seule plateforme."""
    host = url_host(url)
    if not host:
        return None
    if is_hal_host(host):
        return HAL
    for platform in KNOWN_PLATFORMS:
        if any(_matches(url, h) for h in platform.hosts):
            return platform
    if is_host(url, "doi.org") and (doi := clean_doi(url)):
        return _BY_PREFIX.get(doi.partition("/")[0])
    return None


def known_platform_of_copy(url: str, openalex_id: str | None) -> KnownPlatform | None:
    """Renvoie la plateforme de la liste d'une copie : celle de son URL, à défaut celle de sa source OpenAlex."""
    if known := known_platform_of_url(url):
        return known
    return known_platform_of_source(openalex_id) if openalex_id else None


def is_publisher_platform_prefix(prefix: str) -> bool:
    """Vrai si `prefix` est le préfixe DOI d'une plateforme d'éditeurs. Une telle plateforme enregistre sous son préfixe les articles des revues diffusées : le titulaire du préfixe est la plateforme."""
    return prefix in _PUBLISHER_PLATFORM_PREFIXES


def preprint_servers_of_prefix(prefix: str) -> tuple[KnownPlatform, ...]:
    """Renvoie les serveurs de preprints dont `prefix` est un préfixe DOI, dans l'ordre de la liste."""
    return tuple(
        p
        for p in KNOWN_PLATFORMS
        if p.platform_type is PlatformType.PREPRINT_SERVER and prefix in p.doi_prefixes
    )
