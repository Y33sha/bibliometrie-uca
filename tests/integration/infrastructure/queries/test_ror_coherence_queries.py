from sqlalchemy import text

from domain.structures.identifiers import RorId
from infrastructure.read_models.ror import PgRorCoherenceQueries


def test_lectures_du_rapport_de_coherence(sa_sync_conn):
    sa_sync_conn.execute(
        text("""
            INSERT INTO ror_organizations (ror_id, name, country_code, types, status) VALUES
                ('01a8ajp46', 'Université', 'fr', '{education}', 'active'),
                ('03vgfxd91', 'Laboratoire', 'fr', '{facility}', 'active');
            INSERT INTO ror_relations VALUES ('01a8ajp46', '03vgfxd91');
        """)
    )
    queries = PgRorCoherenceQueries(sa_sync_conn)

    assert queries.ror_relations() == [(RorId("01a8ajp46"), RorId("03vgfxd91"))]
    assert queries.ror_names([RorId("03vgfxd91")]) == {RorId("03vgfxd91"): "Laboratoire"}
    queries.structures()
    queries.tutelles()
    queries.perimeter_structure_ids()
