"""Rattachement des contributions sources aux informations du contributeur de leur nom recalculé."""

from sqlalchemy import text

from interfaces.cli.oneshot.recompute_normalized_texts import _repoint_source_contributions
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def test_une_contribution_source_en_ecriture_non_latine_rejoint_les_informations_du_contributeur_de_son_nom(
    sa_sync_conn,
):
    """Régression : les écritures qui suivent la lecture en curseur serveur aboutissent."""
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
            SELECT ci.last_name_normalized, ci.first_name_normalized
            FROM source_contributions sc JOIN contributor_information ci ON ci.id = sc.contributor_information_id
            WHERE sc.id = :sa
        """),
        {"sa": sa},
    ).one() == ("馬場", "重樹")
