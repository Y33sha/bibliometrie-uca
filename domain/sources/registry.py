"""Registre des sources bibliographiques : liste et ordres de priorité.

Source unique de vérité côté Python pour la liste des sources et les ordres de priorité entre sources.

Si une source est ajoutée ou supprimée, modifier ce fichier ET l'enum `source_type` en base (via une migration). Le test `tests/integration/test_scenarios.py::TestSourcesEnum` vérifie la cohérence.
"""

from enum import StrEnum

from domain.errors import ValidationError


class Source(StrEnum):
    """Source bibliographique — les membres portent les libellés de l'enum PostgreSQL `source_type`."""

    HAL = "hal"
    OPENALEX = "openalex"
    WOS = "wos"
    SCANR = "scanr"
    THESES = "theses"
    CROSSREF = "crossref"
    DATACITE = "datacite"


# Toutes les sources, dans l'ordre conventionnel (chronologique d'intégration)
ALL_SOURCES: tuple[Source, ...] = tuple(Source)

# Sources comme set (pour les tests d'appartenance et les valeurs par défaut)
ALL_SOURCES_SET: frozenset[str] = frozenset(Source)

# Préfixe sous lequel une source se désigne dans une requête de lecture. Court, parce qu'il
# voyage dans une URL ; distinct du libellé de l'enum SQL, que `Source` porte.
SOURCE_FILTER_PREFIXES: dict[str, Source] = {
    "hal": Source.HAL,
    "oa": Source.OPENALEX,
    "scanr": Source.SCANR,
    "wos": Source.WOS,
    "theses": Source.THESES,
}

# Vocabulaire du filtre par source : un préfixe suffixé de la présence attendue. `hal_yes`
# retient les publications que HAL porte, `hal_no` les autres ; les deux ensemble ne
# contraignent rien. Valide le filtre `source_filter` des lectures ; une valeur hors
# vocabulaire est refusée.
SOURCE_FILTER_VALUES: frozenset[str] = frozenset(
    f"{prefixe}_{presence}" for prefixe in SOURCE_FILTER_PREFIXES for presence in ("yes", "no")
)

# Sources interrogeables par DOI pour le cross-import (`fetch_missing_doi`).
# Theses absent car son API ne se requête pas par DOI mais par NNT.
DOI_SEARCHABLE_SOURCES: tuple[Source, ...] = (
    Source.HAL,
    Source.OPENALEX,
    Source.WOS,
    Source.SCANR,
    Source.CROSSREF,
    Source.DATACITE,
)

# Sources avec des auteurs exploitables (noms, identifiants, affiliations)
AUTHOR_SOURCES = ALL_SOURCES

# ── Ordres de priorité entre sources ─────────────────────────────

# Ordre général d'autorité des sources — utilisé partout où la
# question est « quelle source gagne ? ». Couvre :
#
# - l'agrégation multi-sources des métadonnées publication
#   (`refresh_from_sources` dans `application/services/publications/core.py`)
# - la résolution de `author_position` quand plusieurs sources
#   attestent une même authorship
# - l'ordre d'exécution des normalizers dans le pipeline
#   (theses en premier → son autorité métadonnées est appliquée
#   avant tout enrichissement)
#
# theses.fr fait autorité sur les métadonnées de thèse ; CrossRef et DataCite
# sont les autorités officielles de l'enregistrement DOI (métadonnées
# canoniques) pour leurs périmètres respectifs et passent juste après theses ;
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


# Sources qui peuvent apparaître comme clés du JSONB `structures.api_ids`
# (identifiants d'organisation côté sources externes). Crossref absent :
# pas de notion d'identifiant structure côté Crossref. Sert de whitelist
# stricte au modèle JSONB `StructureApiIds` côté infra.
STRUCTURE_API_SOURCES: tuple[Source, ...] = (
    Source.OPENALEX,
    Source.WOS,
    Source.SCANR,
    Source.THESES,
    Source.HAL,
)
STRUCTURE_API_SOURCES_SET: frozenset[str] = frozenset(STRUCTURE_API_SOURCES)


# ── Contrôle d'appartenance ──────────────────────────────────────


def require_known_source(source: str) -> None:
    """Vérifie qu'une source appartient au registre. Lève `ValidationError` sinon.

    Les colonnes `source` sont typées par l'enum Postgres `source_type` : une valeur hors registre y produit une erreur de coercition, dont le message ne nomme ni l'appelant ni le champ fautif.
    """
    if source not in ALL_SOURCES_SET:
        raise ValidationError(
            f"Source inconnue : {source!r}. Sources valides : {', '.join(sorted(ALL_SOURCES))}."
        )
