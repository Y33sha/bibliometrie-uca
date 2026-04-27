"""Constantes liées aux sources bibliographiques.

Source unique de vérité côté Python pour la liste des sources et les
ordres de priorité entre sources.

Si une source est ajoutée ou supprimée, modifier ce fichier ET
l'enum source_type en base (via une migration).
Le test test_normalize.py::TestSourcesEnum vérifie la cohérence.
"""

# Toutes les sources, dans l'ordre conventionnel (chronologique d'intégration)
ALL_SOURCES = ("hal", "openalex", "wos", "scanr", "theses", "crossref")

# Sources comme set (pour les tests d'appartenance et les valeurs par défaut)
ALL_SOURCES_SET = frozenset(ALL_SOURCES)

# Sources bibliographiques (hors theses.fr, qui a un traitement spécifique)
BIBLIO_SOURCES = ("hal", "openalex", "wos", "scanr", "crossref")
BIBLIO_SOURCES_SET = frozenset(BIBLIO_SOURCES)


def _to_sql(sources: tuple) -> str:
    """Construit une clause SQL IN à partir d'un tuple de sources."""
    return "(" + ", ".join(f"'{s}'" for s in sources) + ")"


# Sources avec des auteurs exploitables (noms, identifiants, affiliations)
AUTHOR_SOURCES = ALL_SOURCES
AUTHOR_SOURCES_SQL = _to_sql(AUTHOR_SOURCES)

# Sources où les noms d'auteurs sont structurés dans source_persons (last_name, first_name).
# OpenAlex est exclu : les noms viennent de source_authorships.raw_author_name.
SOURCES_WITH_STRUCTURED_NAMES = tuple(s for s in ALL_SOURCES if s != "openalex")
SOURCES_WITH_STRUCTURED_NAMES_SQL = _to_sql(SOURCES_WITH_STRUCTURED_NAMES)


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
SOURCE_PRIORITY: tuple[str, ...] = ("theses", "crossref", "scanr", "hal", "openalex", "wos")

# Ordre spécifique pour le marqueur `is_corresponding`. Inversé par
# rapport à `SOURCE_PRIORITY` : WoS marque explicitement le
# "reprint_author" dans ses métadonnées, OpenAlex l'infère, HAL
# repose sur un code MARC `crp` peu systématiquement rempli. Priorité
# à la source la plus fiable sur *ce champ précis*.
#
# Theses et ScanR sont absents : ils n'alimentent pas ce champ
# (pas de notion de corresponding author pour une thèse, ScanR ne
# renseigne pas).
SOURCE_PRIORITY_IS_CORRESPONDING: tuple[str, ...] = ("wos", "openalex", "hal")


def source_case_sql(priorities: tuple[str, ...], col: str = "sa.source") -> str:
    """Construit un fragment SQL `CASE <col> WHEN 's1' THEN 1 ... END`
    à partir d'un tuple de sources, pour poser une priorité dans un
    `ORDER BY` ou un `array_agg(... ORDER BY ...)`.

    Utilisé pour que les ordres de priorité vivent dans `domain/sources.py`
    comme constantes Python plutôt que dupliqués en SQL.
    """
    whens = " ".join(f"WHEN '{s}' THEN {i + 1}" for i, s in enumerate(priorities))
    return f"CASE {col} {whens} END"
