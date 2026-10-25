"""Liste fermée des plateformes connues : HAL, PubMed Central, Zenodo, serveurs de preprints et plateformes d'éditeurs. Une plateforme connue porte le nom de la liste.

Une plateforme d'éditeurs enregistre sous son propre préfixe DOI les articles des revues qu'elle diffuse : le titulaire du préfixe et le nom que Crossref donne à ces DOI sont alors la plateforme, pas l'éditeur. Un serveur de preprints se reconnaît par la source OpenAlex de ses localisations.

Le préfixe 10.1101 est commun à bioRxiv, à medRxiv et aux revues de Cold Spring Harbor (*Genome Research*) : il ne désigne pas seul un serveur de preprints.
"""

from dataclasses import dataclass

from domain.platforms.platform import PlatformType
from domain.source_records.external_ids import ExternalIdType


@dataclass(frozen=True, slots=True)
class KnownPlatform:
    """Plateforme de la liste fermée : nom, type, préfixes DOI et sources OpenAlex, la principale en tête."""

    name: str
    platform_type: PlatformType
    doi_prefixes: frozenset[str] = frozenset()
    openalex_ids: tuple[str, ...] = ()


def _preprint_server(name: str, prefixes: set[str], openalex_ids: tuple[str, ...]) -> KnownPlatform:
    return KnownPlatform(name, PlatformType.PREPRINT_SERVER, frozenset(prefixes), openalex_ids)


def _publisher_platform(name: str, prefixes: set[str]) -> KnownPlatform:
    return KnownPlatform(name, PlatformType.PUBLISHER_PLATFORM, frozenset(prefixes))


HAL = KnownPlatform("HAL", PlatformType.REPOSITORY, openalex_ids=("S4306402512",))
"""L'archive ouverte HAL, que HAL décrit lui-même et qu'OpenAlex décrit comme une de ses sources."""

PUBMED_CENTRAL = KnownPlatform(
    "PubMed Central", PlatformType.REPOSITORY, openalex_ids=("S2764455111",)
)
"""L'archive de PubMed Central, que désigne aussi l'identifiant PMCID d'un document."""

ZENODO = KnownPlatform("Zenodo", PlatformType.REPOSITORY, openalex_ids=("S4306400562",))
"""L'archive ouverte Zenodo, du CERN."""

ARXIV = _preprint_server("arXiv", {"10.48550"}, ("S4306400194", "S4393918464"))
"""Le serveur de preprints arXiv, que désigne aussi l'identifiant arXiv d'un document."""

KNOWN_PLATFORMS: tuple[KnownPlatform, ...] = (
    HAL,
    PUBMED_CENTRAL,
    ZENODO,
    ARXIV,
    _preprint_server("bioRxiv", {"10.1101", "10.64898"}, ("S4306402567",)),
    _preprint_server("medRxiv", {"10.1101", "10.64898"}, ("S3005729997",)),
    _preprint_server("SSRN", {"10.2139"}, ("S4210172589",)),
    _preprint_server("Research Square", {"10.21203"}, ("S4306525896", "S4306402450")),
    _preprint_server("Preprints.org", {"10.20944"}, ("S6309402219",)),
    _preprint_server("ChemRxiv", {"10.26434"}, ("S4393918830",)),
    _preprint_server("Authorea", {"10.22541"}, ("S4363604296",)),
    _preprint_server("OSF Preprints", {"10.31219"}, ("S4306401127",)),
    _preprint_server("PsyArXiv", {"10.31234"}, ("S4306401687",)),
    _preprint_server("SocArXiv", {"10.31235"}, ("S4306401238",)),
    _preprint_server("EarthArXiv", {"10.31223"}, ("S4306401273", "S4306402614")),
    _preprint_server("AfricArXiv", set(), ("S4306402219",)),
    _preprint_server("BioHackrXiv", set(), ("S4306402587",)),
    _preprint_server("MindRxiv", set(), ("S4306401745",)),
    _preprint_server("ECSarXiv", set(), ("S4306402531",)),
    _preprint_server("SportRxiv", set(), ("S4306402352",)),
    _preprint_server("Arabixiv", set(), ("S4306400047",)),
    _preprint_server("EdArXiv", set(), ("S4306402530",)),
    _preprint_server("EcoEvoRxiv", set(), ("S4306402488",)),
    _publisher_platform("Cairn", {"10.3917"}),
    _publisher_platform("OpenEdition", {"10.4000"}),
    _publisher_platform("Érudit", {"10.7202"}),
    _publisher_platform("Persée", {"10.3406"}),
    _publisher_platform("SciELO", {"10.1590", "10.4067", "10.7476"}),
    _publisher_platform("Prairial", {"10.35562"}),
    _publisher_platform("Episciences", {"10.46298", "10.23638"}),
    _publisher_platform("Centre Mersenne", {"10.5802"}),
    _publisher_platform("Project MUSE", {"10.1353"}),
    _publisher_platform("Université de Bordeaux", {"10.20870"}),
)

PMC_ARTICLE_URL = "https://www.ncbi.nlm.nih.gov/pmc/articles/{}/"
"""Page d'un article de PubMed Central, à compléter par son PMCID."""

IDENTIFIER_COPIES: tuple[tuple[ExternalIdType, str, KnownPlatform], ...] = (
    (ExternalIdType.ARXIV_ID, "https://arxiv.org/abs/{}", ARXIV),
    (ExternalIdType.PMCID, PMC_ARTICLE_URL, PUBMED_CENTRAL),
)
"""Copie ouverte que désigne un identifiant de document : type d'identifiant, URL à compléter par sa valeur, plateforme."""

_BY_OPENALEX_ID = {i: p for p in KNOWN_PLATFORMS for i in p.openalex_ids}
_PUBLISHER_PLATFORM_PREFIXES = frozenset(
    prefix
    for p in KNOWN_PLATFORMS
    if p.platform_type is PlatformType.PUBLISHER_PLATFORM
    for prefix in p.doi_prefixes
)


def known_platform_of_source(openalex_id: str) -> KnownPlatform | None:
    """Plateforme de la liste dont `openalex_id` est une source OpenAlex."""
    return _BY_OPENALEX_ID.get(openalex_id)


def is_publisher_platform_prefix(prefix: str) -> bool:
    """Vrai quand `prefix` est le préfixe DOI d'une plateforme d'éditeurs."""
    return prefix in _PUBLISHER_PLATFORM_PREFIXES


def preprint_servers_of_prefix(prefix: str) -> tuple[KnownPlatform, ...]:
    """Serveurs de preprints dont `prefix` est un préfixe DOI, dans l'ordre de la liste."""
    return tuple(
        p
        for p in KNOWN_PLATFORMS
        if p.platform_type is PlatformType.PREPRINT_SERVER and prefix in p.doi_prefixes
    )
