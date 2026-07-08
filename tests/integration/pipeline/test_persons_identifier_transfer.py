"""Transfert d'identifiant par consensus — canal identifiant ordre-indépendant.

Une valeur d'identifiant captée par un premier arrivé au nom minoritaire est recalée, par le
**balayage frontal des conflits** en tête de phase, sur la personne que soutient la majorité
des porteurs ; un porteur étranger minoritaire, lui, ne vole pas l'identifiant du propriétaire
majoritaire. Le balayage lit le snapshot du run précédent : la capture se forme au run 1,
elle est recalée au run 2 (convergence multi-run).

Ces tests n'appellent que `run()` (pas `populate`, qui committe et casserait le rollback
de la fixture) : l'isolation transactionnelle est préservée.
"""

import logging

from sqlalchemy import text

from application.pipeline.persons.create_persons_from_source_authorships import run
from infrastructure.queries.pipeline.persons_create import PgPersonsCreateQueries
from infrastructure.repositories import person_repository
from tests.integration.helpers.authorships import upsert_identity

_LOG = logging.getLogger("test")
_IDREF = "109964128"  # IdRef réel (valide au regard du value object)


def _seed(conn, *, sa_id, raw_name, name_norm, idref):
    """Publication + signature in-périmètre non rattachée, portant l'identité
    `(name_norm, {idref})`. `sa_id` fixe l'ordre de traitement (`ORDER BY sa.id`)."""
    conn.execute(
        text("""
            INSERT INTO publications (id, title, title_normalized, doc_type, pub_year)
            VALUES (:p, :t, :t, 'article', 2024)
        """),
        {"p": sa_id, "t": f"pub {sa_id}"},
    )
    conn.execute(
        text("""
            INSERT INTO source_publications
                (id, source, source_id, title, pub_year, doc_type, publication_id)
            VALUES (:p, 'hal', :sid, :t, 2024, 'ART', :p)
        """),
        {"p": sa_id, "sid": f"hal-{sa_id}", "t": f"pub {sa_id}"},
    )
    identity = upsert_identity(conn, name_norm, {"idref": idref})
    conn.execute(
        text("""
            INSERT INTO source_authorships
                (id, source, source_publication_id, author_position, in_perimeter,
                 person_id, raw_author_name, identity_id)
            VALUES (:p, 'hal', :p, 0, TRUE, NULL, :raw, :iid)
        """),
        {"p": sa_id, "raw": raw_name, "iid": identity},
    )


def _run(conn):
    run(conn, PgPersonsCreateQueries(), _LOG, person_repo=person_repository(conn))


def _idref_owner_name(conn, idref):
    """(nom, prénom) normalisés de la personne à qui l'IdRef est attribué."""
    return conn.execute(
        text("""
            SELECT p.last_name_normalized AS ln, p.first_name_normalized AS fn
            FROM person_identifiers pi
            JOIN persons p ON p.id = pi.person_id
            WHERE pi.id_type = 'idref' AND pi.id_value = :v
        """),
        {"v": idref},
    ).one()


def test_captured_identifier_recales_on_majority(sa_sync_conn):
    """Capture : « hervé chanal » (id bas, traité en premier) capte l'IdRef ; trois « hélène
    chanal » suivent. Le run 1 forme la capture (IdRef sur hervé) ; le run 2, par balayage
    frontal du snapshot, transfère l'IdRef à la personne majoritaire."""
    _seed(
        sa_sync_conn, sa_id=96001, raw_name="Herve Chanal", name_norm="herve chanal", idref=_IDREF
    )
    for sa_id in (96002, 96003, 96004):
        _seed(
            sa_sync_conn,
            sa_id=sa_id,
            raw_name="Helene Chanal",
            name_norm="helene chanal",
            idref=_IDREF,
        )
    _run(sa_sync_conn)  # capture : IdRef sur « hervé chanal »
    _run(sa_sync_conn)  # balayage frontal : recalage sur la majorité
    owner = _idref_owner_name(sa_sync_conn, _IDREF)
    assert (owner.ln, owner.fn) == ("chanal", "helene")


def test_foreign_bearer_does_not_steal(sa_sync_conn):
    """Porteur étranger : trois « jean martin » (majorité) portent l'IdRef, un « pierre
    dupont » (minorité, contamination) aussi. Le consensus désigne le propriétaire → pas de
    transfert, l'IdRef reste sur « jean martin »."""
    for sa_id in (96011, 96012, 96013):
        _seed(
            sa_sync_conn, sa_id=sa_id, raw_name="Jean Martin", name_norm="jean martin", idref=_IDREF
        )
    _seed(
        sa_sync_conn, sa_id=96014, raw_name="Pierre Dupont", name_norm="pierre dupont", idref=_IDREF
    )
    _run(sa_sync_conn)
    _run(sa_sync_conn)  # deux passes : le balayage frontal confirme le propriétaire
    owner = _idref_owner_name(sa_sync_conn, _IDREF)
    assert (owner.ln, owner.fn) == ("martin", "jean")
