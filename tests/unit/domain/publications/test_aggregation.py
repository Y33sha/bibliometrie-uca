"""Tests de l'agrégation cross-source (`domain.publications.aggregation.refresh_from_sources`).

Cible la priorité donnée aux enregistrements canoniques sur les formes secondaires convergées
(`secondary_ids`) : le titre et les autres scalaires viennent du parent, pas d'une pièce ; les
listes restent unionnées.
"""

from domain.publications.aggregation import refresh_from_sources
from domain.publications.publication import Publication
from domain.source_publications.source_publication import SourcePublication


def _sp(**overrides) -> SourcePublication:
    defaults = dict(
        id=1,
        source="datacite",
        source_id="s",
        title="Titre",
        pub_year=2020,
        doc_type="dataset",
        doi="10.parent/set",
        journal_id=None,
        container_title=None,
        language=None,
        oa_status=None,
        is_retracted=None,
        abstract=None,
        countries=(),
        keywords=(),
        urls=(),
        topics=None,
        biblio=None,
        meta=None,
    )
    defaults.update(overrides)
    return SourcePublication(**defaults)  # type: ignore[arg-type]


def _pub() -> Publication:
    return Publication(id=10, title="obsolète", pub_year=2020)


# `openalex` prioritaire sur `datacite` : sans dépriorisation, la pièce OpenAlex gagnerait le titre.
_PRIORITY = ("openalex", "datacite")


def test_parent_wins_title_over_higher_priority_secondary_piece():
    parent = _sp(id=1, source="datacite", title="Jeu de données phénotypiques", keywords=("blé",))
    piece = _sp(id=2, source="openalex", title="README_data.txt", keywords=("supplément",))

    pub = _pub()
    refresh_from_sources(
        pub, [piece, parent], source_priority=_PRIORITY, secondary_ids=frozenset({2})
    )

    # Le parent (canonique) gagne le titre malgré la priorité de source de la pièce.
    assert pub.title == "Jeu de données phénotypiques"
    # Les mots-clés restent unionnés toutes sources confondues.
    assert set(pub.keywords) == {"blé", "supplément"}


def test_secondary_fills_scalar_absent_on_parent():
    # Le parent n'a pas d'abstract : la pièce, reléguée, comble quand même le champ vide.
    parent = _sp(id=1, source="datacite", abstract=None)
    piece = _sp(id=2, source="openalex", abstract="Description du jeu de données")

    pub = _pub()
    refresh_from_sources(
        pub, [piece, parent], source_priority=_PRIORITY, secondary_ids=frozenset({2})
    )
    assert pub.abstract == "Description du jeu de données"


def test_without_secondary_ids_source_priority_decides():
    # Comportement par défaut inchangé : sans dépriorisation, la source prioritaire gagne le titre.
    parent = _sp(id=1, source="datacite", title="Jeu de données phénotypiques")
    piece = _sp(id=2, source="openalex", title="README_data.txt")

    pub = _pub()
    refresh_from_sources(pub, [piece, parent], source_priority=_PRIORITY)
    assert pub.title == "README_data.txt"
