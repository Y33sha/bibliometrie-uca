"""Registre des sources bibliographiques : profil de chaque source et ordre d'autorité."""

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import quote

from domain.documents.identifiers import hal_id_url
from domain.persons.identifiers import PersonIdentifierType


class Source(StrEnum):
    """Source bibliographique. Reflet du type PostgreSQL `source_type`."""

    HAL = "hal"
    OPENALEX = "openalex"
    WOS = "wos"
    SCANR = "scanr"
    OPS = "ops"
    THESES = "theses"
    CROSSREF = "crossref"
    DATACITE = "datacite"
    INSPIRE = "inspire"


@dataclass(frozen=True, slots=True)
class SourceProfile:
    """Traitement d'une source par le pipeline."""

    label: str
    """Nom affiché de la source, dans le journal comme à l'écran (servi par `/api/sources`)."""
    harvested: bool = False
    """Moissonnée par la phase `harvest`, sur les critères d'affiliation du périmètre."""
    doi_searchable: bool = False
    """Interrogée par DOI à la phase `fetch_missing`."""
    person_identifiers: frozenset[PersonIdentifierType] = frozenset()
    """Identifiants de personne cherchés dans la source par la phase `harvest_by_person`. Vide : la phase ignore la source."""
    registration_agency: str | None = None
    """Agence d'enregistrement représentée par la source, sous son nom dans `doi_prefixes.ra`. Seuls les DOI de cette agence sont cherchés dans la source."""
    opt_in: bool = False
    """Interrogée sur option (`--include-wos`) : son crédit d'API est limité."""
    incremental: bool = False
    """Moissonnée par le mode quotidien, depuis le dernier moissonnage quotidien réussi."""
    aggregator: bool = False
    """Compile les enregistrements d'autres sources (dépôts HAL, Crossref, PubMed). Un enregistrement source de cette source vaut par les liens et les identifiants cités."""
    distinct_works: bool = False
    """Deux enregistrements sources de la source désignent deux œuvres distinctes : une famille de brevets OPS par invention. Chacun est une ancre de la réconciliation, comme un DOI."""
    structure_ids: str | None = None
    """Nature des identifiants de structure de la source, affichée par le formulaire des structures (servi par `/api/sources/structure-ids`). Seules les sources qui la déclarent ont une clé dans `structures.api_ids`."""


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
        structure_ids="institution lineage IDs",
    ),
    Source.WOS: SourceProfile(
        label="WoS",
        harvested=True,
        doi_searchable=True,
        opt_in=True,
        structure_ids="Organization-Enhanced",
    ),
    Source.SCANR: SourceProfile(
        label="ScanR",
        harvested=True,
        doi_searchable=True,
        person_identifiers=frozenset({PersonIdentifierType.ORCID, PersonIdentifierType.IDREF}),
        aggregator=True,
        structure_ids="SIREN",
    ),
    # Familles de brevets INPADOC de l'API OPS de l'Office européen des brevets.
    Source.OPS: SourceProfile(
        label="OPS",
        harvested=True,
        distinct_works=True,
        structure_ids="noms des déposants",
    ),
    # Son API se requête par NNT.
    Source.THESES: SourceProfile(label="theses.fr", harvested=True, structure_ids="PPN IdRef"),
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
        structure_ids="mots-clés d'affiliation",
    ),
    # Base disciplinaire de la physique des hautes énergies, moissonnée par institution.
    Source.INSPIRE: SourceProfile(
        label="INSPIRE-HEP",
        harvested=True,
        structure_ids="numéros d'institution, à défaut noms d'affiliation",
    ),
}

DOI_ORG = "doi_org"
"""Registre des DOI, interrogé pour vérifier qu'un DOI existe. Il figure parmi les sources des recherches infructueuses, sans fournir d'enregistrements sources."""
LOOKUP_SOURCES: tuple[str, ...] = (*Source, DOI_ORG)

_SOURCE_LABELS: dict[str, str] = {
    **{source: profile.label for source, profile in PROFILES.items()},
    DOI_ORG: "doi.org",
}


def source_label(source: str) -> str:
    """Renvoie le nom affiché d'une source de `LOOKUP_SOURCES`.

    Raises:
        KeyError: source inconnue.
    """
    return _SOURCE_LABELS[source]


def source_record_url(source: str, source_id: str) -> str:
    """Renvoie le lien vers l'enregistrement source sur le portail de sa source.

    L'hôte est écrit ici, et l'identifiant est encodé : il ne peut ni changer d'hôte ni ajouter de paramètre.

    Raises:
        ValueError: source inconnue.
    """
    path = quote(source_id, safe=":")
    match Source(source):
        case Source.HAL:
            return hal_id_url(path)
        case Source.OPENALEX:
            return f"https://openalex.org/{path}"
        case Source.WOS:
            return f"https://www.webofscience.com/wos/woscc/full-record/{path}"
        case Source.SCANR:
            # Un identifiant ScanR peut contenir des `/` (`doi/10.1234/…`) : ils sont encodés aussi.
            return f"https://scanr.enseignementsup-recherche.gouv.fr/publications/{quote(source_id, safe='')}"
        case Source.OPS:
            # Identifiant : numéro de la priorité la plus ancienne de la famille.
            return f"https://worldwide.espacenet.com/patent/search?q={quote(f'pr="{source_id}"', safe='')}"
        case Source.THESES:
            return f"https://theses.fr/{path}"
        case Source.CROSSREF | Source.DATACITE:
            return f"https://doi.org/{quote(source_id, safe='/:')}"
        case Source.INSPIRE:
            return f"https://inspirehep.net/literature/{path}"


HARVESTED_SOURCES: tuple[Source, ...] = tuple(s for s, p in PROFILES.items() if p.harvested)
DOI_SEARCHABLE_SOURCES: tuple[Source, ...] = tuple(
    s for s, p in PROFILES.items() if p.doi_searchable
)
PERSON_SEARCHED_SOURCES: tuple[Source, ...] = tuple(
    s for s, p in PROFILES.items() if p.person_identifiers
)
AGGREGATOR_SOURCES: frozenset[Source] = frozenset(s for s, p in PROFILES.items() if p.aggregator)

DISTINCT_WORK_SOURCES: frozenset[Source] = frozenset(
    s for s, p in PROFILES.items() if p.distinct_works
)
"""Sources dont chaque enregistrement source est une œuvre distincte (`SourceProfile.distinct_works`)."""


SOURCE_PRIORITY: tuple[Source, ...] = (
    Source.THESES,
    Source.OPS,
    Source.CROSSREF,
    Source.DATACITE,
    Source.HAL,
    Source.INSPIRE,
    Source.OPENALEX,
    Source.SCANR,
    Source.WOS,
)
"""Ordre d'autorité des sources, pour l'agrégation des métadonnées, la position d'auteur et l'ordre des normaliseurs. theses.fr fait autorité sur les thèses, OPS sur les brevets. Crossref et DataCite font chacun autorité sur leurs propres DOI. INSPIRE-HEP passe avant OpenAlex : ses listes d'auteurs sont complètes et vérifiées."""


STRUCTURE_API_SOURCES: tuple[Source, ...] = tuple(s for s, p in PROFILES.items() if p.structure_ids)
"""Sources admises comme clés de `structures.api_ids` : identifiant d'organisation dans la source, ou chaîne d'affiliation interrogée en texte (WoS, mots-clés DataCite)."""


def structure_ids_label(source: Source) -> str:
    """Renvoie le libellé des identifiants de structure d'une source de `STRUCTURE_API_SOURCES` : « theses.fr (PPN IdRef) »."""
    profile = PROFILES[source]
    return f"{profile.label} ({profile.structure_ids})"
