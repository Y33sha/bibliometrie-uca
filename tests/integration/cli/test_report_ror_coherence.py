from sqlalchemy import text

from domain.structures.identifiers import RorId
from interfaces.cli.maintenance.report_ror_coherence import (
    ror_coherence_report,
    ror_names,
    ror_relations,
)


def test_lectures_du_rapport_de_coherence(sa_sync_conn):
    sa_sync_conn.execute(
        text("""
            INSERT INTO ror_organizations (ror_id, name, country_code, types, status) VALUES
                ('01a8ajp46', 'Université', 'fr', '{education}', 'active'),
                ('03vgfxd91', 'Laboratoire', 'fr', '{facility}', 'active');
            INSERT INTO ror_relations VALUES ('01a8ajp46', '03vgfxd91');
        """)
    )

    assert ror_relations(sa_sync_conn) == [(RorId("01a8ajp46"), RorId("03vgfxd91"))]
    assert ror_names(sa_sync_conn, [RorId("03vgfxd91")]) == {RorId("03vgfxd91"): "Laboratoire"}
    ror_coherence_report(sa_sync_conn)
