"""Rattachement des signatures à l'identité de leur nom recalculé."""

from sqlalchemy import text

from interfaces.cli.oneshot.recompute_normalized_texts import _repoint_signatures
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication


def test_une_signature_en_ecriture_non_latine_rejoint_l_identite_de_son_nom(sa_sync_conn):
    """Régression : la lecture en curseur serveur s'étendait aux écritures qui la suivent, que PostgreSQL refuse."""
    sp = insert_source_publication(sa_sync_conn, insert_publication(sa_sync_conn, "P"))
    sa = insert_signature(
        sa_sync_conn, sp, raw_last_name="馬場", raw_first_name="重樹", author_name_normalized=""
    )

    assert _repoint_signatures(sa_sync_conn, apply=True) == 1

    assert sa_sync_conn.execute(
        text("""
            SELECT aik.last_name_normalized, aik.first_name_normalized
            FROM source_authorships sa JOIN author_identifying_keys aik ON aik.id = sa.identity_id
            WHERE sa.id = :sa
        """),
        {"sa": sa},
    ).one() == ("馬場", "重樹")
