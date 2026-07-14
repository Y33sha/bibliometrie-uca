"""Tests d'intégration pour `infrastructure.queries.api.laboratories`."""

from sqlalchemy import text

from infrastructure.queries.api.laboratories import PgLaboratoriesQueries
from infrastructure.queries.perimeter import refresh_perimeter_structures
from tests.integration.helpers.structures import add_authorship_structure


def _create_structure(conn, code, name=None, type_="labo", hal_collection=None):
    row = conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type, hal_collection) "
            "VALUES (:code, :name, CAST(:tp AS structure_type), :col) RETURNING id"
        ),
        {"code": code, "name": name or code, "tp": type_, "col": hal_collection},
    ).one()
    return row.id


def _setup_perimeter(conn, lab_ids, code="uca"):
    root = _create_structure(conn, code=code.upper(), type_="universite")
    all_ids = [root] + list(lab_ids)
    conn.execute(
        text("INSERT INTO perimeters (code, name, structure_ids) VALUES (:c, :n, :ids)"),
        {"c": code, "n": code.upper(), "ids": all_ids},
    )
    conn.execute(
        text(
            "INSERT INTO config (key, value) VALUES ('perimeter_persons', to_jsonb(CAST(:c AS text)))"
        ),
        {"c": code},
    )
    # relation est_tutelle_de pour les descendants
    for lab in lab_ids:
        conn.execute(
            text(
                "INSERT INTO structure_relations (parent_id, child_id, relation_type) "
                "VALUES (:p, :c, 'est_tutelle_de')"
            ),
            {"p": root, "c": lab},
        )
    # Matérialise la clôture du périmètre : `get_perimeter_structure_ids` lit la table
    # `perimeter_structures`, peuplée par `refresh_perimeter_structures`.
    refresh_perimeter_structures(conn)
    return root


def _create_person(conn, last="A", first="Z"):
    row = conn.execute(
        text(
            "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES (:l, :f, lower(:l), lower(:f)) RETURNING id"
        ),
        {"l": last, "f": first},
    ).one()
    return row.id


def _create_pub_with_authorship(
    conn, person_id, lab_id, doc_type="article", pub_year=2024, in_perimeter=True
):
    pub_id = conn.execute(
        text(
            "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
            "VALUES ('X', 'x', :y, CAST(:dt AS doc_type)) RETURNING id"
        ),
        {"y": pub_year, "dt": doc_type},
    ).scalar_one()
    aid = conn.execute(
        text(
            "INSERT INTO authorships (publication_id, person_id, in_perimeter, roles) "
            "VALUES (:pid, :perid, :inp, ARRAY['author']::text[]) RETURNING id"
        ),
        {"pid": pub_id, "perid": person_id, "inp": in_perimeter},
    ).scalar_one()
    add_authorship_structure(conn, aid, lab_id)
    return pub_id


class TestListLaboratories:
    def test_lists_labos_in_perimeter(self, sa_sync_conn):
        lab = _create_structure(sa_sync_conn, code="LAB-1", name="Lab 1")
        _setup_perimeter(sa_sync_conn, [lab])
        labs = PgLaboratoriesQueries(sa_sync_conn).list_laboratories()
        ids = [lab_.id for lab_ in labs]
        assert lab in ids

    def test_includes_root_as_tutelle(self, sa_sync_conn):
        # La racine de périmètre (université) n'est plus masquée : elle figure dans les tutelles.
        lab = _create_structure(sa_sync_conn, code="LAB-2")
        root = _setup_perimeter(sa_sync_conn, [lab])
        labs = PgLaboratoriesQueries(sa_sync_conn).list_laboratories()
        lab_row = next(lab_ for lab_ in labs if lab_.id == lab)
        tutelles_ids = [t.id for t in (lab_row.tutelles or [])]
        assert root in tutelles_ids

    def test_display_types_configurable(self, sa_sync_conn):
        # Les types affichés suivent la config `laboratories_display_types`.
        conn = sa_sync_conn
        lab = _create_structure(conn, code="LAB-D", type_="labo")
        team = _create_structure(conn, code="TEAM-D", type_="equipe")
        _setup_perimeter(conn, [lab, team])
        q = PgLaboratoriesQueries(conn)

        # Défaut (posé par la migration) : ['labo'] → seul le labo apparaît.
        ids = {row.id for row in q.list_laboratories()}
        assert lab in ids
        assert team not in ids

        # Ajouter 'equipe' à la config → l'équipe apparaît.
        conn.execute(
            text(
                'UPDATE config SET value = \'["labo", "equipe"]\' '
                "WHERE key = 'laboratories_display_types'"
            )
        )
        ids2 = {row.id for row in q.list_laboratories()}
        assert {lab, team} <= ids2


class TestGetLaboratory:
    def test_returns_none_for_missing(self, sa_sync_conn):
        assert PgLaboratoriesQueries(sa_sync_conn).get_laboratory(999_999) is None

    def test_returns_full_profile(self, sa_sync_conn):
        lab = _create_structure(sa_sync_conn, code="LAB", name="Le labo", hal_collection="LAB-COL")
        res = PgLaboratoriesQueries(sa_sync_conn).get_laboratory(lab)
        assert res is not None
        assert res.structure.code == "LAB"
        assert res.structure.hal_collection == "LAB-COL"
        assert isinstance(res.parents, list)
        assert isinstance(res.children, list)
        assert isinstance(res.theses_count, int)


class TestGetLaboratoryAddresses:
    def test_lists_linked_addresses(self, sa_sync_conn):
        lab = _create_structure(sa_sync_conn, code="LAB")
        addr = sa_sync_conn.execute(
            text("INSERT INTO addresses (raw_text, normalized_text) VALUES ('A', 'a') RETURNING id")
        ).scalar_one()
        sa_sync_conn.execute(
            text(
                "INSERT INTO address_structures (address_id, structure_id, is_confirmed) "
                "VALUES (:a, :s, TRUE)"
            ),
            {"a": addr, "s": lab},
        )

        res = PgLaboratoriesQueries(sa_sync_conn).get_laboratory_addresses(lab, page=1, per_page=50)
        ids = [a.id for a in res.addresses]
        assert addr in ids

    def test_excludes_rejected_links(self, sa_sync_conn):
        lab = _create_structure(sa_sync_conn, code="LAB")
        addr = sa_sync_conn.execute(
            text("INSERT INTO addresses (raw_text, normalized_text) VALUES ('R', 'r') RETURNING id")
        ).scalar_one()
        sa_sync_conn.execute(
            text(
                "INSERT INTO address_structures (address_id, structure_id, is_confirmed) "
                "VALUES (:a, :s, FALSE)"
            ),
            {"a": addr, "s": lab},
        )
        res = PgLaboratoriesQueries(sa_sync_conn).get_laboratory_addresses(lab, page=1, per_page=50)
        ids = [a.id for a in res.addresses]
        assert addr not in ids


class TestGetLaboratoryDashboard:
    def test_returns_structure_even_when_empty(self, sa_sync_conn):
        lab = _create_structure(sa_sync_conn, code="LAB")
        res = PgLaboratoriesQueries(sa_sync_conn).get_laboratory_dashboard(lab)
        assert res.pubs_by_year == []
        assert res.oa.total == 0
        assert res.collab.total_articles == 0
        assert res.top_countries == []

    def test_aggregates_oa_and_countries(self, sa_sync_conn):
        sa_sync_conn.execute(
            text("INSERT INTO countries (code, name) VALUES ('us', 'USA') ON CONFLICT DO NOTHING")
        )
        lab = _create_structure(sa_sync_conn, code="LAB")
        pid = _create_person(sa_sync_conn)
        pub_id = sa_sync_conn.execute(
            text("""
                INSERT INTO publications (title, title_normalized, pub_year, doc_type, oa_status, countries)
                VALUES ('X', 'x', 2024, 'article', 'gold', ARRAY['fr', 'us'])
                RETURNING id
            """)
        ).scalar_one()
        aid = sa_sync_conn.execute(
            text(
                "INSERT INTO authorships (publication_id, person_id, in_perimeter, roles) "
                "VALUES (:pid, :perid, TRUE, ARRAY['author']::text[]) RETURNING id"
            ),
            {"pid": pub_id, "perid": pid},
        ).scalar_one()
        add_authorship_structure(sa_sync_conn, aid, lab)

        res = PgLaboratoriesQueries(sa_sync_conn).get_laboratory_dashboard(lab)
        assert res.oa.open_access == 1
        assert res.collab.international == 1
        assert any(c.code == "us" for c in res.top_countries)

    def test_excludes_non_applicable_country(self, sa_sync_conn):
        """`xx` (Non applicable) ne doit ni gonfler le compte international
        ni apparaître dans le top pays."""
        lab = _create_structure(sa_sync_conn, code="LAB")
        pid = _create_person(sa_sync_conn)
        pub_id = sa_sync_conn.execute(
            text("""
                INSERT INTO publications (title, title_normalized, pub_year, doc_type, oa_status, countries)
                VALUES ('Y', 'y', 2024, 'article', 'closed', ARRAY['fr', 'xx'])
                RETURNING id
            """)
        ).scalar_one()
        aid = sa_sync_conn.execute(
            text(
                "INSERT INTO authorships (publication_id, person_id, in_perimeter, roles) "
                "VALUES (:pid, :perid, TRUE, ARRAY['author']::text[]) RETURNING id"
            ),
            {"pid": pub_id, "perid": pid},
        ).scalar_one()
        add_authorship_structure(sa_sync_conn, aid, lab)

        res = PgLaboratoriesQueries(sa_sync_conn).get_laboratory_dashboard(lab)
        assert res.collab.total_articles == 1
        assert res.collab.international == 0
        assert res.collab.domestic == 1
        assert not any(c.code == "xx" for c in res.top_countries)


class TestGetLaboratorySubjects:
    def test_top_subjects_by_frequency(self, sa_sync_conn):
        lab = _create_structure(sa_sync_conn, "L1")
        _setup_perimeter(sa_sync_conn, [lab])

        # 3 publications du labo avec sujets variables.
        def _create_pub(title="X", doc_type="article"):
            row = sa_sync_conn.execute(
                text(
                    "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
                    "VALUES (:t, lower(:t), 2024, CAST(:dt AS doc_type)) RETURNING id"
                ),
                {"t": title, "dt": doc_type},
            ).one()
            return row.id

        def _create_subject(label):
            row = sa_sync_conn.execute(
                text("INSERT INTO subjects (label) VALUES (:l) RETURNING id"),
                {"l": label},
            ).one()
            return row.id

        def _link(pub_id, sid):
            sa_sync_conn.execute(
                text(
                    "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                    "VALUES (:p, :s, 'hal')"
                ),
                {"p": pub_id, "s": sid},
            )

        def _attach(pub_id):
            aid = sa_sync_conn.execute(
                text(
                    "INSERT INTO authorships (publication_id, in_perimeter, roles) "
                    "VALUES (:p, TRUE, ARRAY['author']::text[]) RETURNING id"
                ),
                {"p": pub_id},
            ).scalar_one()
            add_authorship_structure(sa_sync_conn, aid, lab)

        p1 = _create_pub("p1")
        p2 = _create_pub("p2")
        p3 = _create_pub("p3")
        for p in (p1, p2, p3):
            _attach(p)

        ai = _create_subject("AI")
        bio = _create_subject("Biology")
        # AI sur 3 publis ; Biology sur 1.
        for p in (p1, p2, p3):
            _link(p, ai)
        _link(p1, bio)

        res = PgLaboratoriesQueries(sa_sync_conn).get_laboratory_subjects(lab, limit=10)
        assert len(res) == 2
        assert res[0].label == "AI"
        assert res[0].count == 3
        assert res[1].label == "Biology"
        assert res[1].count == 1
