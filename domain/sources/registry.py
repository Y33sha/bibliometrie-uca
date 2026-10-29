"""Registre des sources bibliographiques : profil de chaque source et ordre d'autorité."""

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import quote

from domain.errors import ValidationError
from domain.persons.identifiers import AttributionStatus, PersonIdentifierType


class Source(StrEnum):
    """Source bibliographique. Reflet du type PostgreSQL `source_type`."""

    HAL = "hal"
    OPENALEX = "openalex"
    WOS = "wos"
    SCANR = "scanr"
    THESES = "theses"
    CROSSREF = "crossref"
    DATACITE = "datacite"


@dataclass(frozen=True, slots=True)
class SourceProfile:
    """Ce que le pipeline fait d'une source."""

    # Nom sous lequel la source se donne à lire, dans le journal comme à l'écran (servi par `/api/sources`).
    label: str
    # Moissonnée par la phase `harvest`, sur les critères d'affiliation du périmètre.
    harvested: bool = False
    # Interrogée par DOI à la phase `fetch_missing`.
    doi_searchable: bool = False
    # Identifiants de personne que la phase `harvest_by_person` cherche dans la source. Vide : la phase ne l'interroge pas.
    person_identifiers: frozenset[PersonIdentifierType] = frozenset()
    # Agence d'enregistrement que la source représente, sous son nom dans `doi_prefixes.ra`. Seuls les DOI de cette agence y sont cherchés.
    registration_agency: str | None = None
    # Interrogée sur option (`--include-wos`) : son crédit d'API est limité.
    opt_in: bool = False
    # Moissonnée par le mode quotidien, depuis le dernier moissonnage quotidien réussi.
    incremental: bool = False
    # Compile les enregistrements d'autres sources (dépôts HAL, Crossref, PubMed). Un enregistrement source de cette source vaut par les liens et les identifiants qu'il cite.
    aggregator: bool = False


PROFILES: dict[Source, SourceProfile] = {
    Source.HAL: SourceProfile(
        label="HAL",
        harvested=True,
        doi_searchable=True,
        person_identifiers=frozenset(
            {PersonIdentifierType.ORCID, PersonIdentifierType.IDHAL, PersonIdentifierType.IDREF}
        ),
        incremental=True,
    ),
    Source.OPENALEX: SourceProfile(
        label="OpenAlex",
        harvested=True,
        doi_searchable=True,
        person_identifiers=frozenset({PersonIdentifierType.ORCID}),
        aggregator=True,
    ),
    Source.WOS: SourceProfile(label="WoS", harvested=True, doi_searchable=True, opt_in=True),
    Source.SCANR: SourceProfile(
        label="ScanR",
        harvested=True,
        doi_searchable=True,
        person_identifiers=frozenset({PersonIdentifierType.ORCID, PersonIdentifierType.IDREF}),
        aggregator=True,
    ),
    # Son API se requête par NNT.
    Source.THESES: SourceProfile(label="theses.fr", harvested=True),
    # Interrogé par DOI et par personne, sans moissonnage.
    Source.CROSSREF: SourceProfile(
        label="Crossref",
        doi_searchable=True,
        person_identifiers=frozenset({PersonIdentifierType.ORCID}),
        registration_agency="Crossref",
    ),
    Source.DATACITE: SourceProfile(
        label="DataCite",
        harvested=True,
        doi_searchable=True,
        person_identifiers=frozenset({PersonIdentifierType.ORCID}),
        registration_agency="DataCite",
    ),
}

SOURCE_LABELS: dict[str, str] = {source: profile.label for source, profile in PROFILES.items()}

# Statuts d'un identifiant de personne RH qui la font interroger par la phase `harvest_by_person`.
SEARCHED_IDENTIFIER_STATUSES: frozenset[AttributionStatus] = frozenset(
    {AttributionStatus.CONFIRMED, AttributionStatus.AUTHENTICATED}
)


def source_label(source: str) -> str:
    """Nom lisible d'une source. Une clé inconnue se rend telle quelle."""
    return SOURCE_LABELS.get(source, source)


def source_record_url(source: str, source_id: str, oa_status: str | None = None) -> str:
    """Lien vers l'enregistrement source sur le portail de sa source. Lève `ValueError` pour une source inconnue.

    L'hôte est écrit ici, et l'identifiant est encodé : il ne peut ni changer d'hôte ni ajouter de paramètre. Un dépôt HAL `dumas-` est servi par DUMAS. Une thèse HAL `tel-` est servie par theses.hal.science, sauf en accès fermé (`oa_status`).
    """
    path = quote(source_id, safe=":")
    match Source(source):
        case Source.HAL:
            if source_id.startswith("dumas-"):
                return f"https://dumas.ccsd.cnrs.fr/{path}"
            if source_id.startswith("tel-") and oa_status != "closed":
                return f"https://theses.hal.science/{path}"
            return f"https://hal.science/{path}"
        case Source.OPENALEX:
            return f"https://openalex.org/{path}"
        case Source.WOS:
            return f"https://www.webofscience.com/wos/woscc/full-record/{path}"
        case Source.SCANR:
            # Un identifiant ScanR peut contenir des `/` (`doi/10.1234/…`) : ils sont encodés aussi.
            return f"https://scanr.enseignementsup-recherche.gouv.fr/publications/{quote(source_id, safe='')}"
        case Source.THESES:
            return f"https://theses.fr/{path}"
        case Source.CROSSREF | Source.DATACITE:
            return f"https://doi.org/{quote(source_id, safe='/:')}"


# Toutes les sources, dans leur ordre d'intégration.
ALL_SOURCES: tuple[Source, ...] = tuple(Source)
ALL_SOURCES_SET: frozenset[str] = frozenset(Source)

# Préfixe d'une source dans un filtre de lecture, court parce qu'il figure dans une URL.
SOURCE_FILTER_PREFIXES: dict[str, Source] = {
    "hal": Source.HAL,
    "oa": Source.OPENALEX,
    "scanr": Source.SCANR,
    "wos": Source.WOS,
    "theses": Source.THESES,
}

# Valeurs du filtre `source_filter` des lectures : un préfixe suivi de la présence attendue. `hal_yes` retient les publications présentes dans HAL, `hal_no` les autres.
SOURCE_FILTER_VALUES: frozenset[str] = frozenset(
    f"{prefixe}_{presence}" for prefixe in SOURCE_FILTER_PREFIXES for presence in ("yes", "no")
)

HARVESTED_SOURCES: tuple[Source, ...] = tuple(s for s, p in PROFILES.items() if p.harvested)
DOI_SEARCHABLE_SOURCES: tuple[Source, ...] = tuple(
    s for s, p in PROFILES.items() if p.doi_searchable
)
PERSON_SEARCHED_SOURCES: tuple[Source, ...] = tuple(
    s for s, p in PROFILES.items() if p.person_identifiers
)
AGGREGATOR_SOURCES: frozenset[Source] = frozenset(s for s, p in PROFILES.items() if p.aggregator)

# Registre des DOI, interrogé pour vérifier qu'un DOI existe. Il figure parmi les sources des recherches infructueuses, sans fournir d'enregistrements sources.
DOI_ORG = "doi_org"
LOOKUP_SOURCES: tuple[str, ...] = (*ALL_SOURCES, DOI_ORG)

# Couples (source, type d'identifiant) dont la source est le registre qui attribue l'identifiant. Un identifiant absent de son registre n'existe pas : l'échec de sa recherche est définitif.
REGISTRY_LOOKUPS: frozenset[tuple[str, str]] = frozenset(
    {(Source.HAL, "hal_id"), (Source.THESES, "nnt"), (DOI_ORG, "doi")}
)


# Ordre d'autorité des sources, pour l'agrégation des métadonnées, la position d'auteur et l'ordre des normaliseurs.
# theses.fr fait autorité sur les thèses. Crossref et DataCite font chacun autorité sur leurs propres DOI.
SOURCE_PRIORITY: tuple[Source, ...] = (
    Source.THESES,
    Source.CROSSREF,
    Source.DATACITE,
    Source.HAL,
    Source.OPENALEX,
    Source.SCANR,
    Source.WOS,
)


# Sources admises comme clés de `structures.api_ids` : identifiant d'organisation dans la source, ou chaîne d'affiliation interrogée en texte (WoS, mots-clés DataCite).
STRUCTURE_API_SOURCES: tuple[Source, ...] = (
    Source.OPENALEX,
    Source.WOS,
    Source.SCANR,
    Source.THESES,
    Source.DATACITE,
)


def require_known_source(source: str) -> None:
    """Lève `ValidationError` pour une source hors du registre. Le message nomme la source, que l'erreur PostgreSQL sur `source_type` tait."""
    if source not in ALL_SOURCES_SET:
        raise ValidationError(
            f"Source inconnue : {source!r}. Sources valides : {', '.join(sorted(ALL_SOURCES))}."
        )
