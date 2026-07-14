"""Taxonomie canonique des `doc_type` : enum, ensembles et familles.

Vocabulaire partagé de la couche canonique — la valeur de l'enum PostgreSQL `doc_type` de la table `publications`, ses sous-types d'article prioritaires à l'arbitrage, et le regroupement en familles pour la ventilation. Le mapping des nomenclatures sources vers cette taxonomie vit côté source (`domain/source_publications/doc_types.py`).
"""

from typing import Literal

DocType = Literal[
    "article",
    "conference_paper",
    "book",
    "book_chapter",
    "thesis",
    "ongoing_thesis",
    "preprint",
    "review",
    "editorial",
    "report",
    "peer_review",
    "other",
    "dataset",
    "software",
    "patent",
    "hdr",
    "memoir",
    "poster",
    "letter",
    "erratum",
    "retraction",
    "book_review",
    "data_paper",
    "proceedings",
    "media",
]
DOC_TYPES: tuple[DocType, ...] = (
    "article",
    "conference_paper",
    "book",
    "book_chapter",
    "thesis",
    "ongoing_thesis",
    "preprint",
    "review",
    "editorial",
    "report",
    "peer_review",
    "other",
    "dataset",
    "software",
    "patent",
    "hdr",
    "memoir",
    "poster",
    "letter",
    "erratum",
    "retraction",
    "book_review",
    "data_paper",
    "proceedings",
    "media",
)
DOC_TYPES_SET: frozenset[str] = frozenset(DOC_TYPES)

# Sous-types qui priment sur "article" générique : si une source prioritaire
# (typiquement CrossRef avec "journal-article") dit "article", mais qu'une
# source moins prioritaire (HAL, OA…) reconnaît un sous-type plus précis,
# on préfère le sous-type pour ne pas perdre l'information.
#
# CrossRef ne distingue pas ces sous-types (tout est "journal-article") ;
# HAL fait la distinction via ses combinaisons type_sous-type
# ("art_artrev" → "review", "art_bookreview" → "book_review", etc.).
# L'arbitrage vit dans `domain/publications/aggregation.py`
# (`arbitrate_doc_type_with_article_subtype`).
ARTICLE_SUBTYPES: frozenset[str] = frozenset(
    {
        "review",
        "book_review",
        "data_paper",
        "conference_paper",
        "editorial",
        "letter",
        "erratum",
        "retraction",
    }
)

# Famille → types fins. Mémoires/thèses en cours filtrés ailleurs, mais classés ici pour
# l'exhaustivité de la couverture de l'enum. L'ordre est celui d'affichage.
DOC_TYPE_FAMILIES: dict[str, tuple[str, ...]] = {
    "publications": ("article", "conference_paper", "book", "book_chapter", "review", "data_paper"),
    "preprints": ("preprint",),
    "theses": ("thesis", "ongoing_thesis", "hdr", "memoir"),
    "data": ("dataset", "software", "patent"),
    "misc": (
        "other",
        "media",
        "poster",
        "report",
        "erratum",
        "retraction",
        "peer_review",
        "editorial",
        "letter",
        "book_review",
        "proceedings",
    ),
}
