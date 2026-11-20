"""Phase `relations`, tâche `link_notices` : reconstruction à chaque run des relations des publications avec leurs errata et leurs avis (correction, rétractation, préoccupation).

Errata et avis de rétractation sont hors des publications (`OUT_OF_SCOPE_DOC_TYPES`) : chaque relation part de la publication concernée et vise le DOI de l'avis. Les relations viennent de quatre signaux, par ordre de priorité :

- mises à jour et relations Crossref déclarées par la publication (`updated_by`, `relation`) ;
- mises à jour Crossref déclarées par l'avis (`update_to`) vers le DOI de la publication ;
- référence de l'article corrigé en fin de titre WoS de l'avis (`wos_corrected_article`) ;
- titre de l'avis : titre de la publication à la suite de « Erratum: », à condition qu'un seul candidat ait ce titre.

Le type de l'avis l'emporte sur le type de mise à jour déclaré (`notice_relation`) : Elsevier déclare ses avis de rétractation comme des errata.
"""

from __future__ import annotations

import logging
from typing import NamedTuple

from sqlalchemy import Connection, bindparam, text

from domain.documents.doc_types import DocType
from domain.normalize import normalize_text
from domain.publications.relations import (
    NOTICE_RELATION_TYPES,
    NOTICE_SUBJECT_RELATIONS,
    RelationType,
    extract_crossref_relations,
    extract_crossref_update_relations,
    inverse_relation,
    notice_relation,
)
from domain.source_records.keys import DISCRIMINANT_TITLE_MIN_LENGTH
from domain.source_records.notices import wos_corrected_article
from domain.source_records.source_extras import SourceExtra
from domain.sources.registry import Source
from domain.types import JsonValue
from infrastructure.db.jsonb import Jsonb
from infrastructure.db.source_record_identifiers import source_record_doi_sql
from infrastructure.sql_fragments import has_source_extra, in_clause
from pipeline.graph import Task, in_transaction
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.publications.relations.rebuild import (
    TITLE_MATCH_YEAR_WINDOW,
    UNIQUE_SUBSTANTIVE_CANDIDATE,
    RelationEdge,
    TitleMatch,
    fetch_publications_by_doi,
    rebuild_relations,
    relations_metrics,
)

_NOTICE_DOC_TYPES = (DocType.ERRATUM.value, DocType.RETRACTION.value)


class NoticeRecord(NamedTuple):
    """Enregistrement source d'un erratum ou d'un avis de rétractation."""

    id: int
    source: str
    doi: str | None
    """DOI de l'avis, cible des relations."""
    doc_type: str
    title: str
    title_normalized: str | None
    publication_year: int | None
    source_extras: dict[str, JsonValue] | None


class DeclaringPublication(NamedTuple):
    """Enregistrement source Crossref rattaché à une publication, qui déclare des mises à jour ou des relations."""

    publication_id: int
    source_extras: dict[str, JsonValue]


_NOTICE_RECORDS_SQL = text(f"""
    SELECT sr.id, sr.source::text AS source, sr.doc_type::text AS doc_type, sr.title,
           sr.title_normalized, sr.publication_year, sr.source_extras,
           {source_record_doi_sql("sr")} AS doi
    FROM source_records sr
    WHERE sr.doc_type::text IN {in_clause(_NOTICE_DOC_TYPES)} AND sr.is_matchable
""")
"""Enregistrements sources des errata et des avis, avec leur DOI (`source_record_doi_sql`). Un avis écarté de la réconciliation (`is_matchable`), tel le doublon retiré d'un corrigendum, est ignoré."""

_DECLARING_PUBLICATIONS_SQL = text(f"""
    SELECT sr.publication_id, sr.source_extras
    FROM source_records sr
    WHERE sr.source = '{Source.CROSSREF.value}' AND sr.publication_id IS NOT NULL
      AND ({has_source_extra(SourceExtra.RELATION)}
           OR {has_source_extra(SourceExtra.UPDATE_TO)}
           OR {has_source_extra(SourceExtra.UPDATED_BY)})
""")

_REFERENCE_YEAR_WINDOW = 1
"""Écart d'années toléré entre l'article corrigé et l'année de sa référence dans le titre d'un erratum WoS."""

_CANDIDATE_PARENT = f"""
        SELECT c.id AS child_id, p.id AS parent_id, p.doi AS parent_doi,
               (p.doc_type::text NOT IN ('{DocType.PREPRINT.value}', '{DocType.DATASET.value}'))
                   AS substantive
        FROM child c
        JOIN publications p
          ON length(p.title_normalized) > {DISCRIMINANT_TITLE_MIN_LENGTH}
"""
"""Début de la CTE `candidate` : publications à titre assez long. Un preprint ou un jeu de données, autre forme de l'article, reste candidat sans être substantiel."""

_REFERENCE_MATCHES_SQL = text(f"""
    WITH child AS (
        SELECT * FROM jsonb_to_recordset(:children) AS c (id int, t text, y int)
    ),
    candidate AS (
        {_CANDIDATE_PARENT}
         AND p.title_normalized = c.t
         AND p.publication_year BETWEEN c.y - {_REFERENCE_YEAR_WINDOW} AND c.y + {_REFERENCE_YEAR_WINDOW}
    ),
    {UNIQUE_SUBSTANTIVE_CANDIDATE}
""").bindparams(bindparam("children", type_=Jsonb))
"""Erratum WoS → article corrigé : titre identique au titre lu dans la référence, article publié à un an près de l'année de la référence. Garde d'ambiguïté : un seul candidat substantiel."""

_TITLE_MATCHES_SQL = text(f"""
    WITH child AS (
        SELECT * FROM jsonb_to_recordset(:children) AS c (id int, t text, y int)
    ),
    candidate AS (
        {_CANDIDATE_PARENT}
         AND p.publication_year BETWEEN c.y - {TITLE_MATCH_YEAR_WINDOW} AND c.y
         AND right(c.t, length(p.title_normalized)) = p.title_normalized
    ),
    {UNIQUE_SUBSTANTIVE_CANDIDATE}
""").bindparams(bindparam("children", type_=Jsonb))
"""Erratum → article corrigé : titre de l'article suffixe du titre de l'erratum, article publié dans [année − 2 … année]. Garde d'ambiguïté : un seul candidat substantiel."""


def fetch_notice_records(conn: Connection) -> list[NoticeRecord]:
    """Renvoie les enregistrements sources des errata et des avis de rétractation."""
    return [
        NoticeRecord(
            r.id,
            r.source,
            r.doi,
            r.doc_type,
            r.title,
            r.title_normalized,
            r.publication_year,
            r.source_extras,
        )
        for r in conn.execute(_NOTICE_RECORDS_SQL)
    ]


def notice_types(notices: list[NoticeRecord]) -> dict[str, str]:
    """Renvoie le type de chaque avis, par DOI : `retraction` dès qu'un de ses enregistrements sources est de ce type, `erratum` sinon."""
    types: dict[str, str] = {}
    for notice in notices:
        if notice.doi and types.get(notice.doi) != DocType.RETRACTION:
            types[notice.doi] = notice.doc_type
    return types


def _publication_relation(notice_type: str | None) -> RelationType:
    """Renvoie la relation d'une publication vers un avis de ce type."""
    return notice_relation(RelationType.HAS_CORRECTION, None, notice_type)


def build_publication_declared_edges(
    publications: list[DeclaringPublication], types: dict[str, str]
) -> list[RelationEdge]:
    """Construit les arêtes déclarées par les publications. Le type de l'avis cible, connu par son DOI, corrige le type déclaré."""
    edges: list[RelationEdge] = []
    for publication in publications:
        declared = extract_crossref_relations(
            publication.source_extras
        ) + extract_crossref_update_relations(publication.source_extras)
        edges.extend(
            RelationEdge(
                publication.publication_id,
                notice_relation(relation, None, types.get(doi)).value,
                doi,
                Source.CROSSREF.value,
            )
            for relation, doi in declared
            if relation in NOTICE_RELATION_TYPES
        )
    return edges


def notice_declared_targets(notices: list[NoticeRecord]) -> list[str]:
    """Renvoie les DOI des œuvres déclarées mises à jour par les avis."""
    return sorted(
        {
            doi
            for notice in notices
            for relation, doi in extract_crossref_update_relations(notice.source_extras)
            if relation in NOTICE_SUBJECT_RELATIONS
        }
    )


def build_notice_declared_edges(
    notices: list[NoticeRecord], types: dict[str, str], publication_ids: dict[str, int]
) -> list[RelationEdge]:
    """Construit les arêtes des mises à jour déclarées par les avis, retournées vers la publication concernée.

    Args:
        publication_ids: publication désignée par chaque DOI déclaré.
    """
    edges: list[RelationEdge] = []
    for notice in notices:
        if notice.doi is None:
            continue
        for relation, target_doi in extract_crossref_update_relations(notice.source_extras):
            target = publication_ids.get(target_doi)
            if relation not in NOTICE_SUBJECT_RELATIONS or target is None:
                continue
            notice_side = notice_relation(relation, types[notice.doi], None)
            edges.append(
                RelationEdge(
                    target, inverse_relation(notice_side).value, notice.doi, Source.CROSSREF.value
                )
            )
    return edges


def fetch_reference_matches(conn: Connection, notices: list[NoticeRecord]) -> list[TitleMatch]:
    """Renvoie les errata WoS reliés à l'article corrigé par la référence en fin de leur titre."""
    children: list[JsonValue] = [
        {"id": notice.id, "t": normalize_text(article.title), "y": article.year}
        for notice in notices
        if notice.source == Source.WOS
        and notice.doi
        and (article := wos_corrected_article(notice.title))
    ]
    if not children:
        return []
    rows = conn.execute(_REFERENCE_MATCHES_SQL, {"children": children}).all()
    return [TitleMatch(r.child_id, r.parent_id, r.parent_doi) for r in rows]


def fetch_title_matches(conn: Connection, notices: list[NoticeRecord]) -> list[TitleMatch]:
    """Renvoie les errata reliés par titre à l'article corrigé. Un seul enregistrement source par titre et par année d'un même avis est comparé."""
    seen: set[tuple[str, str, int]] = set()
    children: list[JsonValue] = []
    for notice in notices:
        if not (notice.doi and notice.title_normalized and notice.publication_year):
            continue
        key = (notice.doi, notice.title_normalized, notice.publication_year)
        if key not in seen:
            seen.add(key)
            children.append(
                {"id": notice.id, "t": notice.title_normalized, "y": notice.publication_year}
            )
    if not children:
        return []
    rows = conn.execute(_TITLE_MATCHES_SQL, {"children": children}).all()
    return [TitleMatch(r.child_id, r.parent_id, r.parent_doi) for r in rows]


def build_match_edges(
    matches: list[TitleMatch], notices: list[NoticeRecord], types: dict[str, str]
) -> list[RelationEdge]:
    """Construit une arête de la publication concernée vers le DOI de l'avis par rattachement de titre."""
    dois = {notice.id: notice.doi for notice in notices}
    edges: list[RelationEdge] = []
    for match in matches:
        doi = dois[match.child_id]
        assert doi is not None  # Seuls les avis à DOI sont comparés.
        edges.append(
            RelationEdge(
                match.parent_id, _publication_relation(types.get(doi)).value, doi, "title_match"
            )
        )
    return edges


def rebuild(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Reconstruit les relations de `NOTICE_RELATION_TYPES` depuis les quatre signaux, et renvoie les compteurs de la tâche."""
    notices = fetch_notice_records(conn)
    types = notice_types(notices)
    publications = [
        DeclaringPublication(r.publication_id, r.source_extras)
        for r in conn.execute(_DECLARING_PUBLICATIONS_SQL)
    ]
    publication_ids = {
        doi: publication.id
        for doi, publication in fetch_publications_by_doi(
            conn, notice_declared_targets(notices)
        ).items()
    }
    # L'ordre des signaux fixe la priorité de dédoublonnage (`ON CONFLICT`). Un avis relié par une déclaration Crossref est écarté des rattachements par titre, coûteux.
    edges = build_publication_declared_edges(publications, types) + build_notice_declared_edges(
        notices, types, publication_ids
    )
    related = {edge.target_doi for edge in edges}
    unrelated = [notice for notice in notices if notice.doi not in related]
    edges += build_match_edges(fetch_reference_matches(conn, unrelated), notices, types)
    edges += build_match_edges(fetch_title_matches(conn, unrelated), notices, types)
    changes = rebuild_relations(conn, edges, NOTICE_RELATION_TYPES)
    return relations_metrics(conn, changes, NOTICE_RELATION_TYPES, logger)


TASKS = (
    Task(
        "link_notices",
        reads=(
            *(
                f"source_records.{column}"
                for column in (
                    "source",
                    "source_extras",
                    "doc_type",
                    "publication_id",
                    "title",
                    "title_normalized",
                    "publication_year",
                    "is_matchable",
                )
            ),
            "source_record_identifiers",
            # Cible d'un DOI de forme secondaire, qui désigne la publication de la cible.
            "doi_targets",
            "publications.id",
            "publications.doc_type",
            "publications.doi",
            "publications.title_normalized",
            "publications.publication_year",
            "publication_relations",
        ),
        writes=("publication_relations",),
        # Lecture de la table avant sa reconstruction, pour compter les arêtes ajoutées et disparues.
        previous_runs=("publication_relations",),
        run=in_transaction(rebuild),
        section="Relations avec les errata et les avis",
    ),
)
