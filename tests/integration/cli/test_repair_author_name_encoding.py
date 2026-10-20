"""Oneshot `repair_author_name_encoding` : noms d'auteur du stock à l'encodage erroné."""

from interfaces.cli.oneshot.decode_latex_author_names import decoded_names
from interfaces.cli.oneshot.repair_author_name_encoding import CANDIDATES_SQL, PARAMS
from tests.integration.helpers.contributions import upsert_split_contributor_information
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def test_seuls_les_noms_a_l_encodage_errone_sont_repares(sa_sync_conn):
    conn = sa_sync_conn
    source_record = insert_source_record(
        conn, insert_publication(conn), source="openalex", source_id="W1"
    )
    source_contributions = {
        raw: insert_source_contribution(
            conn,
            source_record,
            source="openalex",
            author_position=position,
            raw_author_name=raw,
            contributor_information_id=upsert_split_contributor_information(
                conn, f"nom{position}", "prenom"
            ),
            roles=["author"],
        )
        for position, raw in enumerate(
            (
                "TÃ©lesphore Sime-Ngando",
                "Fran鏾is Bouchon",
                "Lema{î}tre, A.",
                "São João, Ângela",
                "Wang王",
            )
        )
    }

    rows, _ = decoded_names(conn, CANDIDATES_SQL, PARAMS)

    repaired = {r["id"]: r["raw_author_name"] for r in rows}
    assert repaired == {
        source_contributions["TÃ©lesphore Sime-Ngando"]: "Télesphore Sime-Ngando",
        source_contributions["Fran鏾is Bouchon"]: "François Bouchon",
        source_contributions["Lema{î}tre, A."]: "Lemaître, A.",
    }
