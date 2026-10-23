"""Registre des sources bibliographiques : profil de chaque source et ordres de priorité.

Si une source est ajoutée ou supprimée, modifier ce fichier ET l'enum `source_type` en base (via une migration). Le test `tests/integration/test_scenarios.py::TestPgEnumsMatchDb` vérifie la cohérence. Le pipeline implémente le profil de chaque source dans son adaptateur.
"""

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import quote

from domain.errors import ValidationError
from domain.persons.identifiers import PersonIdentifierType


class Source(StrEnum):
    """Source bibliographique — les membres ont les libellés de l'enum PostgreSQL `source_type`."""

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
    ),
    Source.WOS: SourceProfile(label="WoS", harvested=True, doi_searchable=True, opt_in=True),
    Source.SCANR: SourceProfile(
        label="ScanR",
        harvested=True,
        doi_searchable=True,
        person_identifiers=frozenset({PersonIdentifierType.ORCID, PersonIdentifierType.IDREF}),
    ),
    # Son API se requête par NNT, pas par DOI.
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


# Toutes les sources, dans l'ordre conventionnel (chronologique d'intégration)
ALL_SOURCES: tuple[Source, ...] = tuple(Source)

# Sources comme set (pour les tests d'appartenance et les valeurs par défaut)
ALL_SOURCES_SET: frozenset[str] = frozenset(Source)

# Préfixe sous lequel une source se désigne dans une requête de lecture. Court, parce qu'il
# voyage dans une URL ; distinct du libellé de l'enum SQL, que `Source` contient.
SOURCE_FILTER_PREFIXES: dict[str, Source] = {
    "hal": Source.HAL,
    "oa": Source.OPENALEX,
    "scanr": Source.SCANR,
    "wos": Source.WOS,
    "theses": Source.THESES,
}

# Vocabulaire du filtre par source : un préfixe suffixé de la présence attendue. `hal_yes`
# retient les publications présentes dans HAL, `hal_no` les autres ; les deux ensemble ne
# contraignent rien. Valide le filtre `source_filter` des lectures ; une valeur hors
# vocabulaire est refusée.
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

# Registre des DOI, interrogé pour vérifier qu'un DOI existe. Il figure parmi les sources des recherches infructueuses, sans fournir d'enregistrements sources.
DOI_ORG = "doi_org"
LOOKUP_SOURCES: tuple[str, ...] = (*ALL_SOURCES, DOI_ORG)

# Couples (source, type d'identifiant) dont la source est le registre qui attribue l'identifiant. Un identifiant absent de son registre n'existe pas : l'échec de sa recherche est définitif.
REGISTRY_LOOKUPS: frozenset[tuple[str, str]] = frozenset(
    {(Source.HAL, "hal_id"), (Source.THESES, "nnt"), (DOI_ORG, "doi")}
)


# ── Ordres de priorité entre sources ─────────────────────────────

# Ordre général d'autorité des sources — utilisé partout où la
# question est « quelle source gagne ? ». Couvre :
#
# - l'agrégation multi-sources des métadonnées publication
#   (`refresh_from_sources` dans `pipeline/transformation/publications/consolidation.py`)
# - la résolution de `author_position` quand plusieurs sources
#   attestent une même contribution
# - l'ordre d'exécution des normaliseurs dans le pipeline
#
# theses.fr fait autorité sur les métadonnées de thèse ; CrossRef et DataCite
# sont les autorités officielles de l'enregistrement DOI
# pour leurs périmètres respectifs et passent juste après theses ;
# pour les documents hors-thèse la clé `theses` n'apparaît simplement pas dans
# les rows et l'ordre se réduit aux sources restantes. Crossref et DataCite ne
# se concurrencent pas : chaque RA fait autorité sur ses propres DOI.
SOURCE_PRIORITY: tuple[Source, ...] = (
    Source.THESES,
    Source.CROSSREF,
    Source.DATACITE,
    Source.HAL,
    Source.OPENALEX,
    Source.SCANR,
    Source.WOS,
)


# Sources qui peuvent apparaître comme clés du JSONB `structures.api_ids` : identifiants
# d'organisation côté sources externes, ou chaînes d'affiliation interrogées en texte (WoS,
# mots-clés DataCite). Sert de whitelist stricte au modèle JSONB `StructureApiIds` côté infra.
STRUCTURE_API_SOURCES: tuple[Source, ...] = (
    Source.OPENALEX,
    Source.WOS,
    Source.SCANR,
    Source.THESES,
    Source.DATACITE,
)


# ── Contrôle d'appartenance ──────────────────────────────────────


def require_known_source(source: str) -> None:
    """Vérifie qu'une source appartient au registre. Lève `ValidationError` sinon.

    Les colonnes `source` sont typées par l'enum Postgres `source_type` : une valeur hors registre y produit une erreur de coercition, dont le message ne nomme ni l'appelant ni le champ fautif.
    """
    if source not in ALL_SOURCES_SET:
        raise ValidationError(
            f"Source inconnue : {source!r}. Sources valides : {', '.join(sorted(ALL_SOURCES))}."
        )
