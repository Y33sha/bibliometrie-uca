"""Import RH : création de la personne et de sa fiche `hr_records`, déduplication sur nom normalisé, service et fonction."""

from sqlalchemy import text

from interfaces.cli.imports.import_persons import RhImportOutcome, import_rh_person


def test_personne_et_fiche_rh_creees(sa_sync_conn):
    outcome = import_rh_person(
        sa_sync_conn,
        "Durand",
        "Marie",
        email="marie.durand@uca.fr",
        department="LMBP",
        role="MCF",
        start_date="2020-09-01",
        export_date="2026-01-15",
    )
    assert outcome is RhImportOutcome.INSERTED
    row = sa_sync_conn.execute(
        text("""
            SELECT prh.email, prh.role_title, prh.department_name
            FROM persons p JOIN hr_records prh ON prh.person_id = p.id
            WHERE p.last_name_normalized = 'durand' AND p.first_name_normalized = 'marie'
        """)
    ).one()
    assert row.email == "marie.durand@uca.fr"
    assert row.role_title == "MCF"
    assert row.department_name == "LMBP"


def test_meme_nom_et_meme_fiche_rh_est_un_doublon(sa_sync_conn):
    import_rh_person(sa_sync_conn, "Durand", "Marie", department="LMBP", role="MCF")
    again = import_rh_person(sa_sync_conn, "Durand", "Marie", department="LMBP", role="MCF")
    assert again is RhImportOutcome.DUPLICATE


def test_meme_nom_autre_service_est_cree(sa_sync_conn):
    import_rh_person(sa_sync_conn, "Durand", "Marie", department="LMBP", role="MCF")
    other = import_rh_person(sa_sync_conn, "Durand", "Marie", department="LPC", role="MCF")
    assert other is RhImportOutcome.INSERTED
