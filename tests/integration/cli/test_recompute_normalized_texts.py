"""Rattachement des signatures à l'identité de leur nom recalculé."""

from sqlalchemy import text

from interfaces.cli.oneshot.recompute_normalized_texts import _repoint_source_contributions
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def test_une_contribution_source_en_ecriture_non_latine_rejoint_les_informations_du_contributeur_de_son_nom(
    sa_sync_conn,
):
    """Régression : la lecture en curseur serveur s'étendait aux écritures qui la suivent, que PostgreSQL refuse."""
    source_record = insert_source_record(sa_sync_conn, insert_publication(sa_sync_conn, "P"))
    sa = insert_source_contribution(
        sa_sync_conn,
        source_record,
        raw_last_name="馬場",
        raw_first_name="重樹",
        author_name_normalized="",
    )

    assert _repoint_source_contributions(sa_sync_conn, apply=True) == 1

    assert sa_sync_conn.execute(
        text("""
            SELECT aik.last_name_normalized, aik.first_name_normalized
            FROM source_contributions sa JOIN contributor_information aik ON aik.id = sa.contributor_information_id
            WHERE sa.id = :sa
        """),
        {"sa": sa},
    ).one() == ("馬場", "重樹")
