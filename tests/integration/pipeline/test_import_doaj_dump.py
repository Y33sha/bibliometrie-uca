"""Import du dump DOAJ (`run_import_doaj_dump`)."""

import logging

from sqlalchemy import text

from pipeline.transformation.publishing.serials.enrich_serials_from_doaj import (
    model_doaj_serials_as_diamond,
    run_import_doaj_dump,
    type_doaj_serials_as_journals,
)
from tests.integration.helpers.serials import insert_serial, insert_serial_issn


def _create_serial(conn, *, issn=None, eissn=None):
    serial_id = insert_serial(conn, "J")
    for value, support in ((issn, "print"), (eissn, "electronic")):
        if value:
            insert_serial_issn(conn, serial_id, issn=value, support=support)
    return serial_id


def _row(issn="", eissn="", **extra):
    r = {
        "Journal ISSN (print version)": issn,
        "Journal EISSN (online version)": eissn,
    }
    r.update(extra)
    return r


def _run(conn, rows, *, dry_run=False):
    # Sans validation : la fixture `sa_sync_conn` est une transaction annulée en fin de test.
    return run_import_doaj_dump(
        conn,
        logging.getLogger("test"),
        rows=rows,
        dry_run=dry_run,
        commit=False,
    )


def _is_in_doaj(conn, jid):
    return conn.execute(
        text("SELECT is_in_doaj FROM serials WHERE id = :id"), {"id": jid}
    ).scalar_one()


class TestImportDoajDump:
    def test_matches_by_issn_and_writes_payload(self, sa_sync_conn):
        jid = _create_serial(sa_sync_conn, issn="0028-0836")
        stats = _run(sa_sync_conn, [_row(issn="0028-0836", **{"Journal title": "Foo"})])
        assert stats.matched == 1
        row = sa_sync_conn.execute(
            text("SELECT is_in_doaj, doaj_payload FROM serials WHERE id = :id"), {"id": jid}
        ).one()
        assert row.is_in_doaj is True
        assert row.doaj_payload["Journal title"] == "Foo"

    def test_matches_on_eissn_when_print_absent(self, sa_sync_conn):
        jid = _create_serial(sa_sync_conn, eissn="1476-4687")
        stats = _run(sa_sync_conn, [_row(eissn="1476-4687")])
        assert stats.matched == 1
        assert _is_in_doaj(sa_sync_conn, jid) is True

    def test_matches_on_normalized_issn(self, sa_sync_conn):
        """Un ISSN du dump est normalisé avant d'être comparé aux ISSN des revues."""
        jid = _create_serial(sa_sync_conn, issn="0071-190X")
        stats = _run(sa_sync_conn, [_row(issn="0071190X")])
        assert stats.matched == 1
        assert _is_in_doaj(sa_sync_conn, jid) is True

    def test_invalid_issn_counted_as_absent(self, sa_sync_conn):
        stats = _run(sa_sync_conn, [_row(issn="1234-5678")])  # clé de contrôle fausse
        assert stats.no_issn_rows == 1

    def test_reset_clears_serials_absent_from_dump(self, sa_sync_conn):
        # Une revue marquée `is_in_doaj` et absente du dump perd sa marque.
        jid = _create_serial(sa_sync_conn, issn="0036-8075")
        _create_serial(sa_sync_conn, issn="0028-0836")
        sa_sync_conn.execute(
            text("UPDATE serials SET is_in_doaj = TRUE WHERE id = :id"), {"id": jid}
        )
        _run(sa_sync_conn, [_row(issn="0028-0836")])  # dump sans l'ISSN de la première revue
        assert _is_in_doaj(sa_sync_conn, jid) is False

    def test_dump_without_recognized_serial_changes_nothing(self, sa_sync_conn):
        """Aucune revue reconnue (format du dump changé, par exemple) : les revues restent en l'état."""
        jid = _create_serial(sa_sync_conn, issn="0036-8075")
        sa_sync_conn.execute(
            text("UPDATE serials SET is_in_doaj = TRUE WHERE id = :id"), {"id": jid}
        )
        stats = _run(sa_sync_conn, [{"Colonne renommée": "0036-8075"}])
        assert stats.matched == 0
        assert _is_in_doaj(sa_sync_conn, jid) is True

    def test_orphan_rows_counted_not_matched(self, sa_sync_conn):
        stats = _run(sa_sync_conn, [_row(issn="2049-3630")])  # ISSN absent de la base
        assert stats.orphan_rows == 1
        assert stats.matched == 0

    def test_dry_run_counts_but_writes_nothing(self, sa_sync_conn):
        jid = _create_serial(sa_sync_conn, issn="0028-0836")
        stats = _run(sa_sync_conn, [_row(issn="0028-0836")], dry_run=True)
        assert stats.matched == 1  # compté
        assert _is_in_doaj(sa_sync_conn, jid) is False  # sans écriture


class TestTypeDoajSerialsAsJournals:
    def test_unknown_serial_in_doaj_becomes_journal(self, sa_sync_conn):
        unknown = insert_serial(sa_sync_conn, "U", serial_type="unknown", is_in_doaj=True)
        absent = insert_serial(sa_sync_conn, "A", serial_type="unknown", is_in_doaj=False)
        typed = insert_serial(sa_sync_conn, "P", serial_type="proceedings", is_in_doaj=True)
        manual = insert_serial(sa_sync_conn, "M", serial_type="unknown", is_in_doaj=True)
        sa_sync_conn.execute(
            text("UPDATE serials SET manual_fields = ARRAY['serial_type'] WHERE id = :id"),
            {"id": manual},
        )
        assert type_doaj_serials_as_journals(sa_sync_conn) == 1
        types = dict(
            sa_sync_conn.execute(
                text("SELECT id, serial_type::text FROM serials WHERE id = ANY(:ids)"),
                {"ids": [unknown, absent, typed, manual]},
            ).all()
        )
        assert types == {
            unknown: "journal",
            absent: "unknown",
            typed: "proceedings",
            manual: "unknown",
        }


def _doaj_serial(conn, title, *, oa_model, apc, fees="No", manual=False):
    """Insère une revue présente dans le DOAJ, avec ses frais déclarés."""
    serial_id = insert_serial(conn, title, oa_model=oa_model, is_in_doaj=True)
    conn.execute(
        text(
            "UPDATE serials SET doaj_payload = jsonb_build_object('APC', CAST(:apc AS text), 'Has other fees', CAST(:fees AS text)),"
            " manual_fields = CASE WHEN :manual THEN ARRAY['oa_model'] ELSE manual_fields END WHERE id = :id"
        ),
        {"apc": apc, "fees": fees, "manual": manual, "id": serial_id},
    )
    return serial_id


class TestModelDoajSerialsAsDiamond:
    def test_doaj_without_fees_is_diamond(self, sa_sync_conn):
        free = _doaj_serial(sa_sync_conn, "Libre", oa_model="full_oa", apc="No")
        free_subscription = _doaj_serial(
            sa_sync_conn, "Abonnement", oa_model="subscription", apc="No"
        )
        other_fees = _doaj_serial(sa_sync_conn, "Frais", oa_model="full_oa", apc="No", fees="Yes")
        lost_diamond = _doaj_serial(sa_sync_conn, "Payante", oa_model="diamond", apc="Yes")
        manual = _doaj_serial(sa_sync_conn, "Manuelle", oa_model="full_oa", apc="No", manual=True)
        manual_diamond = insert_serial(sa_sync_conn, "Marquée", oa_model="diamond")
        sa_sync_conn.execute(
            text("UPDATE serials SET manual_fields = ARRAY['oa_model'] WHERE id = :id"),
            {"id": manual_diamond},
        )

        assert model_doaj_serials_as_diamond(sa_sync_conn) == 3
        models = dict(
            sa_sync_conn.execute(
                text("SELECT id, oa_model::text FROM serials WHERE id = ANY(:ids)"),
                {
                    "ids": [
                        free,
                        free_subscription,
                        other_fees,
                        lost_diamond,
                        manual,
                        manual_diamond,
                    ]
                },
            ).all()
        )
        assert models == {
            free: "diamond",
            free_subscription: "diamond",
            other_fees: "full_oa",
            lost_diamond: "full_oa",
            manual: "full_oa",
            manual_diamond: "diamond",
        }
