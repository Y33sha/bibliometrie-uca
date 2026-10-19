"""Oneshot `repair_author_name_encoding` : noms d'auteur du stock à l'encodage erroné."""

from interfaces.cli.oneshot.decode_latex_author_names import decoded_names
from interfaces.cli.oneshot.repair_author_name_encoding import CANDIDATES_SQL, PARAMS
from tests.integration.helpers.authorships import upsert_split_identity
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_publication


def test_seuls_les_noms_a_l_encodage_errone_sont_repares(sa_sync_conn):
    conn = sa_sync_conn
    notice = insert_source_publication(
        conn, insert_publication(conn), source="openalex", source_id="W1"
    )
    signatures = {
        raw: insert_signature(
            conn,
            notice,
            source="openalex",
            author_position=position,
            raw_author_name=raw,
            identity_id=upsert_split_identity(conn, f"nom{position}", "prenom"),
            roles=["author"],
        )
        for position, raw in enumerate(
            ("TÃ©lesphore Sime-Ngando", "Fran鏾is Bouchon", "São João, Ângela", "Wang王")
        )
    }

    rows, _ = decoded_names(conn, CANDIDATES_SQL, PARAMS)

    repaired = {r["id"]: r["raw_author_name"] for r in rows}
    assert repaired == {
        signatures["TÃ©lesphore Sime-Ngando"]: "Télesphore Sime-Ngando",
        signatures["Fran鏾is Bouchon"]: "François Bouchon",
    }
