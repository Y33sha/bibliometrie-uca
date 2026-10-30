"""Tests d'intégration de `sync_detections`, sur les deux tables de liens."""

from collections.abc import Callable
from dataclasses import dataclass
from itertools import count

import pytest
from sqlalchemy import Connection, text

from pipeline.transformation.structures.detections import (
    ADDRESS_STRUCTURES,
    IDREF_STRUCTURES,
    Detection,
    DetectionTable,
    sync_detections,
)
from tests.integration.helpers.addresses import insert_address
from tests.integration.helpers.structures import insert_structure, insert_structure_name_form

_keys = count(1)
_codes = count(1)


@dataclass(frozen=True)
class _Table:
    table: DetectionTable
    new_key: Callable[[Connection], int | str]


@pytest.fixture(
    params=[
        _Table(ADDRESS_STRUCTURES, lambda conn: insert_address(conn, f"A{next(_keys)}")),
        _Table(IDREF_STRUCTURES, lambda conn: f"ppn-test-{next(_keys)}"),
    ],
    ids=["address_structures", "idref_structures"],
)
def links(request: pytest.FixtureRequest) -> _Table:
    return request.param


def _link(
    conn: Connection,
    links: _Table,
    key: int | str,
    structure_id: int,
    form_id: int | None,
    is_confirmed: bool | None = None,
) -> None:
    t = links.table
    conn.execute(
        text(
            f"INSERT INTO {t.name} ({t.key}, structure_id, matched_form_id, is_confirmed)"
            " VALUES (:key, :sid, :fid, :confirmed)"
        ),
        {"key": key, "sid": structure_id, "fid": form_id, "confirmed": is_confirmed},
    )


def _linked(conn: Connection, links: _Table, key: int | str) -> dict[int, int | None]:
    """Renvoie `{structure_id: matched_form_id}` des liens de `key`."""
    t = links.table
    rows = conn.execute(
        text(f"SELECT structure_id, matched_form_id FROM {t.name} WHERE {t.key} = :key"),
        {"key": key},
    ).all()
    return {r.structure_id: r.matched_form_id for r in rows}


def _structure_with_form(conn: Connection, form_text: str = "uca") -> tuple[int, int]:
    s = insert_structure(conn, f"S{next(_codes)}", name="X")
    return s, insert_structure_name_form(conn, s, form_text=form_text)


class TestUndetectedLinks:
    def test_lien_non_detecte_supprime(self, sa_sync_conn, links):
        s1, f1 = _structure_with_form(sa_sync_conn)
        s2, f2 = _structure_with_form(sa_sync_conn, "y")
        key = links.new_key(sa_sync_conn)
        _link(sa_sync_conn, links, key, s1, f1)
        _link(sa_sync_conn, links, key, s2, f2)

        sync_detections(sa_sync_conn, links.table, [Detection(key, s1, f1)])

        assert _linked(sa_sync_conn, links, key) == {s1: f1}

    def test_lien_confirme_garde_sans_forme(self, sa_sync_conn, links):
        s, f = _structure_with_form(sa_sync_conn)
        key = links.new_key(sa_sync_conn)
        _link(sa_sync_conn, links, key, s, f, is_confirmed=True)

        sync_detections(sa_sync_conn, links.table, [])

        assert _linked(sa_sync_conn, links, key) == {s: None}

    def test_lien_dont_la_forme_est_supprimee(self, sa_sync_conn, links):
        """La suppression d'une forme vide `matched_form_id` : le lien, non confirmé et non détecté, est supprimé."""
        s, f = _structure_with_form(sa_sync_conn)
        key = links.new_key(sa_sync_conn)
        _link(sa_sync_conn, links, key, s, f)
        sa_sync_conn.execute(text("DELETE FROM structure_name_forms WHERE id = :f"), {"f": f})

        sync_detections(sa_sync_conn, links.table, [])

        assert _linked(sa_sync_conn, links, key) == {}

    def test_detection_par_couple(self, sa_sync_conn, links):
        """Une structure détectée pour une clé garde seulement le lien de cette clé."""
        s, f = _structure_with_form(sa_sync_conn)
        key1, key2 = links.new_key(sa_sync_conn), links.new_key(sa_sync_conn)
        _link(sa_sync_conn, links, key1, s, f)
        _link(sa_sync_conn, links, key2, s, f)

        sync_detections(sa_sync_conn, links.table, [Detection(key1, s, f)])

        assert _linked(sa_sync_conn, links, key1) == {s: f}
        assert _linked(sa_sync_conn, links, key2) == {}

    def test_scope_borne_la_synchronisation(self, sa_sync_conn, links):
        s, f = _structure_with_form(sa_sync_conn)
        inside, outside = links.new_key(sa_sync_conn), links.new_key(sa_sync_conn)
        _link(sa_sync_conn, links, inside, s, f)
        _link(sa_sync_conn, links, outside, s, f)

        sync_detections(sa_sync_conn, links.table, [], scope=[inside])

        assert _linked(sa_sync_conn, links, inside) == {}
        assert _linked(sa_sync_conn, links, outside) == {s: f}


class TestDetectedLinks:
    def test_insere(self, sa_sync_conn, links):
        s1, f1 = _structure_with_form(sa_sync_conn)
        s2, f2 = _structure_with_form(sa_sync_conn, "y")
        key = links.new_key(sa_sync_conn)

        sync_detections(sa_sync_conn, links.table, [Detection(key, s1, f1), Detection(key, s2, f2)])

        assert _linked(sa_sync_conn, links, key) == {s1: f1, s2: f2}

    def test_met_a_jour_la_forme(self, sa_sync_conn, links):
        s, f1 = _structure_with_form(sa_sync_conn, "x1")
        f2 = insert_structure_name_form(sa_sync_conn, s, form_text="x2")
        key = links.new_key(sa_sync_conn)
        _link(sa_sync_conn, links, key, s, f1)

        sync_detections(sa_sync_conn, links.table, [Detection(key, s, f2)])

        assert _linked(sa_sync_conn, links, key) == {s: f2}

    def test_detection_identique_sans_ecriture(self, sa_sync_conn, links):
        """Une détection identique laisse la ligne intacte (`xmin` inchangé)."""
        s, f = _structure_with_form(sa_sync_conn)
        key = links.new_key(sa_sync_conn)
        t = links.table
        sync_detections(sa_sync_conn, t, [Detection(key, s, f)])
        xmin = text(f"SELECT xmin FROM {t.name} WHERE {t.key} = :key AND structure_id = :s")
        before = sa_sync_conn.execute(xmin, {"key": key, "s": s}).scalar_one()

        sync_detections(sa_sync_conn, t, [Detection(key, s, f)])

        assert sa_sync_conn.execute(xmin, {"key": key, "s": s}).scalar_one() == before
