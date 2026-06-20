"""Registre des sources bibliographiques : liste, ordres de priorité, helpers.

Source unique de vérité côté Python pour la liste des sources et les ordres de
priorité entre sources.

Si une source est ajoutée ou supprimée, modifier ce fichier ET l'enum
`source_type` en base (via une migration). Le test
`tests/integration/test_scenarios.py::TestSourcesEnum` vérifie la cohérence.
"""

# Toutes les sources, dans l'ordre conventionnel (chronologique d'intégration)
ALL_SOURCES = ("hal", "openalex", "wos", "scanr", "theses", "crossref")

# Sources comme set (pour les tests d'appartenance et les valeurs par défaut)
ALL_SOURCES_SET = frozenset(ALL_SOURCES)

# Sources interrogeables par DOI pour le cross-import (`fetch_missing_doi`).
# Theses absent car son API ne se requête pas par DOI mais par NNT.
DOI_SEARCHABLE_SOURCES = ("hal", "openalex", "wos", "scanr", "crossref")
DOI_SEARCHABLE_SOURCES_SET = frozenset(DOI_SEARCHABLE_SOURCES)


def _to_sql(sources: tuple[str, ...]) -> str:
    """Construit une clause SQL IN à partir d'un tuple de sources."""
    return "(" + ", ".join(f"'{s}'" for s in sources) + ")"


# Sources avec des auteurs exploitables (noms, identifiants, affiliations)
AUTHOR_SOURCES = ALL_SOURCES
AUTHOR_SOURCES_SQL = _to_sql(AUTHOR_SOURCES)

# ── Ordres de priorité entre sources ─────────────────────────────

# Ordre général d'autorité des sources — utilisé partout où la
# question est « quelle source gagne ? ». Couvre :
#
# - l'agrégation multi-sources des métadonnées publication
#   (`refresh_from_sources` dans `application/publications.py`)
# - la résolution de `author_position` quand plusieurs sources
#   attestent une même authorship
# - l'ordre d'exécution des normalizers dans le pipeline
#   (theses en premier → son autorité métadonnées est appliquée
#   avant tout enrichissement)
#
# theses.fr fait autorité sur les métadonnées de thèse ; CrossRef est
# l'autorité officielle de l'enregistrement DOI (métadonnées éditeur
# canoniques) et passe en 2e après theses ; pour les documents hors-thèse
# la clé `theses` n'apparaît simplement pas dans les rows et l'ordre se
# réduit aux sources restantes.
SOURCE_PRIORITY: tuple[str, ...] = ("theses", "crossref", "hal", "openalex", "scanr", "wos")


# Sources qui peuvent apparaître comme clés du JSONB `structures.api_ids`
# (identifiants d'organisation côté sources externes). Crossref absent :
# pas de notion d'identifiant structure côté Crossref. Sert de whitelist
# stricte au modèle JSONB `StructureApiIds` côté infra.
STRUCTURE_API_SOURCES: tuple[str, ...] = ("openalex", "wos", "scanr", "theses", "hal")
STRUCTURE_API_SOURCES_SET: frozenset[str] = frozenset(STRUCTURE_API_SOURCES)

# `is_corresponding` n'a pas d'ordre de priorité : il s'agrège en `bool_or`
# (vrai si au moins une source l'atteste). Audit prod : le FALSE des sources est
# une absence de signal (champ booléen défaut FALSE), pas une non-correspondance
# explicite — aucune source n'émet de FALSE à écraser, donc l'union ne risque
# pas de « true indu ».


def source_case_sql(priorities: tuple[str, ...], col: str = "sa.source") -> str:
    """Construit un fragment SQL `CASE <col> WHEN 's1' THEN 1 ... END`
    à partir d'un tuple de sources, pour poser une priorité dans un
    `ORDER BY` ou un `array_agg(... ORDER BY ...)`.

    Utilisé pour que les ordres de priorité vivent dans `domain/sources/`
    comme constantes Python plutôt que dupliqués en SQL.
    """
    whens = " ".join(f"WHEN '{s}' THEN {i + 1}" for i, s in enumerate(priorities))
    return f"CASE {col} {whens} END"
