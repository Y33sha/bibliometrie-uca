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

from infrastructure.repositories.person_repository import PgPersonRepository
from pipeline.transformation.persons.cascade import run_cascade
from pipeline.transformation.persons.identifier_arbitration import arbitrate_identifier_conflicts
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

_LOG = logging.getLogger("test")
_IDREF = "109964128"  # IdRef réel (valide au regard du value object)


def _seed(conn, *, source_contribution_id, raw_name, name_norm, idref):
    """Publication + signature in-périmètre non rattachée, portant l'identité
    `(name_norm, {idref})`. `source_contribution_id` fixe l'ordre de traitement (`ORDER BY sa.id`)."""
    insert_publication(conn, f"pub {source_contribution_id}", row_id=source_contribution_id)
    insert_source_record(
        conn,
        source_contribution_id,
        source_id=f"hal-{source_contribution_id}",
        title=f"pub {source_contribution_id}",
        row_id=source_contribution_id,
        publication_year=2024,
        doc_type="ART",
    )
    insert_source_contribution(
        conn,
        source_contribution_id,
        row_id=source_contribution_id,
        raw_author_name=raw_name,
        author_name_normalized=name_norm,
        identifiers={"idref": idref},
        in_perimeter=True,
    )


def _run(conn):
    """Arbitrage des conflits d'identifiant (transfert par consensus) puis la cascade."""
    arbitrate_identifier_conflicts(conn, _LOG, repo=PgPersonRepository(conn))
    run_cascade(conn, _LOG, repo=PgPersonRepository(conn))


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
        sa_sync_conn,
        source_contribution_id=96001,
        raw_name="Herve Chanal",
        name_norm="herve chanal",
        idref=_IDREF,
    )
    for source_contribution_id in (96002, 96003, 96004):
        _seed(
            sa_sync_conn,
            source_contribution_id=source_contribution_id,
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
    for source_contribution_id in (96011, 96012, 96013):
        _seed(
            sa_sync_conn,
            source_contribution_id=source_contribution_id,
            raw_name="Jean Martin",
            name_norm="jean martin",
            idref=_IDREF,
        )
    _seed(
        sa_sync_conn,
        source_contribution_id=96014,
        raw_name="Pierre Dupont",
        name_norm="pierre dupont",
        idref=_IDREF,
    )
    _run(sa_sync_conn)
    _run(sa_sync_conn)  # deux passes : le balayage frontal confirme le propriétaire
    owner = _idref_owner_name(sa_sync_conn, _IDREF)
    assert (owner.ln, owner.fn) == ("martin", "jean")
