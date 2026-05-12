"""Tests d'intégration — déduplication des personnes.

Teste la logique de create_persons_from_source_authorships.py
avec une vraie base PostgreSQL (bibliometrie_test).
Chaque test tourne dans une transaction rollbackée (isolation complète).
"""

import logging

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.persons import add_identifier, add_name_form, create_person
from infrastructure.db.queries.persons.create import PgPersonsCreateQueries
from infrastructure.repositories import person_repository

_queries = PgPersonsCreateQueries()
_logger = logging.getLogger("test")

# ── Helpers ──────────────────────────────────────────────────────


def _insert_publication(conn, title="Test Pub", pub_year=2024):
    """Crée une publication minimale."""
    from domain.normalize import normalize_text

    return conn.execute(
        text("""
            INSERT INTO publications (title, title_normalized, doc_type, pub_year)
            VALUES (:title, :norm, 'article', :pub_year) RETURNING id
        """),
        {"title": title, "norm": normalize_text(title), "pub_year": pub_year},
    ).scalar_one()


def _insert_hal_author(conn, full_name, hal_person_id=None, orcid=None, idhal=None):
    """Crée un source_author HAL minimal."""
    source_ids = {}
    if hal_person_id is not None:
        source_ids["hal_person_id"] = hal_person_id
    if idhal is not None:
        source_ids["idhal"] = idhal
    stmt = text("""
        INSERT INTO source_persons (source, source_id, full_name, orcid, source_ids)
        VALUES ('hal', :source_id, :full_name, :orcid, :source_ids) RETURNING id
    """).bindparams(bindparam("source_ids", type_=JSONB))
    return conn.execute(
        stmt,
        {
            "source_id": f"hal-{full_name}",
            "full_name": full_name,
            "orcid": orcid,
            "source_ids": source_ids if source_ids else None,
        },
    ).scalar_one()


def _insert_hal_document(conn, halid, publication_id):
    """Crée un source_document minimal (source='hal')."""
    return conn.execute(
        text("""
            INSERT INTO source_publications (source, source_id, title, pub_year, publication_id)
            VALUES ('hal', :halid, 'Test', 2024, :pub_id) RETURNING id
        """),
        {"halid": halid, "pub_id": publication_id},
    ).scalar_one()


def _insert_hal_authorship(
    conn,
    source_publication_id,
    source_person_id,
    position=0,
    in_perimeter=True,
    person_id=None,
    raw_author_name=None,
):
    """Crée une source_authorship HAL.

    `raw_author_name` est lu depuis `source_persons.full_name` par défaut
    (parse côté caller via `parse_raw_author_name`) — c'est ce qui se
    passe en prod aussi.
    """
    if raw_author_name is None:
        raw_author_name = conn.execute(
            text("SELECT full_name FROM source_persons WHERE id = :sp_id"),
            {"sp_id": source_person_id},
        ).scalar_one_or_none()
    return conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, source_person_id, author_position,
                 in_perimeter, person_id, raw_author_name, author_name_normalized)
            VALUES ('hal', :sd, :sp, :pos, :in_perim, :person_id,
                    :raw, normalize_name_form(:raw)) RETURNING id
        """),
        {
            "sd": source_publication_id,
            "sp": source_person_id,
            "pos": position,
            "in_perim": in_perimeter,
            "person_id": person_id,
            "raw": raw_author_name,
        },
    ).scalar_one()


def _insert_oa_author(conn, full_name, openalex_id, orcid=None):
    """Crée un source_author OpenAlex minimal."""
    return conn.execute(
        text("""
            INSERT INTO source_persons (source, source_id, full_name, orcid)
            VALUES ('openalex', :source_id, :full_name, :orcid) RETURNING id
        """),
        {"source_id": openalex_id, "full_name": full_name, "orcid": orcid},
    ).scalar_one()


def _insert_oa_document(conn, openalex_id, publication_id):
    """Crée un source_document minimal (source='openalex')."""
    return conn.execute(
        text("""
            INSERT INTO source_publications (source, source_id, title, pub_year, publication_id)
            VALUES ('openalex', :oa_id, 'Test', 2024, :pub_id) RETURNING id
        """),
        {"oa_id": openalex_id, "pub_id": publication_id},
    ).scalar_one()


def _insert_oa_authorship(
    conn,
    oa_document_id,
    oa_author_id,
    position=0,
    in_perimeter=True,
    person_id=None,
    raw_author_name=None,
    identifiers=None,
):
    """Crée une source_authorship OpenAlex.

    Pour OpenAlex/WoS/CrossRef, les identifiants (orcid, idref, ...) vivent
    sur `source_authorships.person_identifiers` (JSONB), pas sur
    `source_persons` — le pipeline de dédup-personnes lit
    `sa.person_identifiers->>'orcid'`.
    """
    stmt = text("""
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position,
             in_perimeter, person_id, raw_author_name, person_identifiers, author_name_normalized)
        VALUES ('openalex', :sd, :sp, :pos, :in_perim, :person_id,
                :raw, :person_identifiers, normalize_name_form(:raw)) RETURNING id
    """).bindparams(bindparam("person_identifiers", type_=JSONB))
    return conn.execute(
        stmt,
        {
            "sd": oa_document_id,
            "sp": oa_author_id,
            "pos": position,
            "in_perim": in_perimeter,
            "person_id": person_id,
            "raw": raw_author_name,
            "person_identifiers": identifiers,
        },
    ).scalar_one()


def _get_person_id_of_hal_authorship(conn, authorship_id):
    return conn.execute(
        text("SELECT person_id FROM source_authorships WHERE id = :id"),
        {"id": authorship_id},
    ).scalar_one_or_none()


def _get_person_id_of_oa_authorship(conn, authorship_id):
    return conn.execute(
        text("SELECT person_id FROM source_authorships WHERE id = :id"),
        {"id": authorship_id},
    ).scalar_one_or_none()


def _get_person_identifiers(conn, person_id):
    """Retourne les identifiants d'une personne : {(id_type, id_value), ...}"""
    rows = conn.execute(
        text("SELECT id_type, id_value FROM person_identifiers WHERE person_id = :pid"),
        {"pid": person_id},
    ).all()
    return {(r.id_type, r.id_value) for r in rows}


# ── Étape 1 : Cross-source ──────────────────────────────────────


class TestStep1CrossSource:
    def test_same_pub_same_position_compatible_name(self, sa_sync_conn):
        """Même publi, même position, nom compatible → rattache à la même personne."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            load_linked_authorships_by_pub,
            step1_cross_source,
        )

        pub = _insert_publication(sa_sync_conn, "Shared Publication")

        # Personne existante rattachée via HAL
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        ha = _insert_hal_author(sa_sync_conn, "Jean Dupont", hal_person_id=111)
        hd = _insert_hal_document(sa_sync_conn, "hal-100", pub)
        _insert_hal_authorship(sa_sync_conn, hd, ha, position=3, person_id=person_id)

        # Authorship OA non rattachée, même publi, même position
        oa_author = _insert_oa_author(sa_sync_conn, "J Dupont", "A111")
        oa_doc = _insert_oa_document(sa_sync_conn, "W111", pub)
        oa_as = _insert_oa_authorship(
            sa_sync_conn, oa_doc, oa_author, position=3, raw_author_name="J Dupont"
        )

        all_as = get_all_unlinked_authorships(sa_sync_conn, _queries)
        linked_ids = set()
        linked_index = load_linked_authorships_by_pub(sa_sync_conn, _queries)
        step1_cross_source(
            _logger,
            all_as,
            linked_ids,
            linked_index,
            dry_run=False,
            person_repo=person_repository(sa_sync_conn),
        )

        assert _get_person_id_of_oa_authorship(sa_sync_conn, oa_as) == person_id

    def test_cross_source_imports_identifiers(self, sa_sync_conn):
        """Cross-source rattachement → les identifiants de l'authorship sont importés."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            load_linked_authorships_by_pub,
            step1_cross_source,
        )

        pub = _insert_publication(sa_sync_conn)

        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        ha = _insert_hal_author(sa_sync_conn, "Jean Dupont", hal_person_id=111)
        hd = _insert_hal_document(sa_sync_conn, "hal-id-test", pub)
        _insert_hal_authorship(sa_sync_conn, hd, ha, position=0, person_id=person_id)

        # OA authorship avec ORCID porté par person_identifiers (cf. chantier
        # source_persons : pour OA/WoS/CrossRef, l'ORCID vit sur
        # source_authorships.person_identifiers, pas sur source_persons).
        oa_author = _insert_oa_author(sa_sync_conn, "J Dupont", "A-id1")
        oa_doc = _insert_oa_document(sa_sync_conn, "W-id1", pub)
        _insert_oa_authorship(
            sa_sync_conn,
            oa_doc,
            oa_author,
            position=0,
            raw_author_name="J Dupont",
            identifiers={"orcid": "0000-0001-9999-8888"},
        )

        all_as = get_all_unlinked_authorships(sa_sync_conn, _queries)
        linked_ids = set()
        linked_index = load_linked_authorships_by_pub(sa_sync_conn, _queries)
        step1_cross_source(
            _logger,
            all_as,
            linked_ids,
            linked_index,
            dry_run=False,
            person_repo=person_repository(sa_sync_conn),
        )

        ids = _get_person_identifiers(sa_sync_conn, person_id)
        assert ("orcid", "0000-0001-9999-8888") in ids

    def test_same_pub_different_position_no_match(self, sa_sync_conn):
        """Même publi mais position différente → pas de rattachement."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            load_linked_authorships_by_pub,
            step1_cross_source,
        )

        pub = _insert_publication(sa_sync_conn)

        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        ha = _insert_hal_author(sa_sync_conn, "Jean Dupont", hal_person_id=222)
        hd = _insert_hal_document(sa_sync_conn, "hal-200", pub)
        _insert_hal_authorship(sa_sync_conn, hd, ha, position=0, person_id=person_id)

        oa_author = _insert_oa_author(sa_sync_conn, "J Dupont", "A222")
        oa_doc = _insert_oa_document(sa_sync_conn, "W222", pub)
        oa_as = _insert_oa_authorship(
            sa_sync_conn, oa_doc, oa_author, position=5, raw_author_name="J Dupont"
        )

        all_as = get_all_unlinked_authorships(sa_sync_conn, _queries)
        linked_ids = set()
        linked_index = load_linked_authorships_by_pub(sa_sync_conn, _queries)
        step1_cross_source(
            _logger,
            all_as,
            linked_ids,
            linked_index,
            dry_run=False,
            person_repo=person_repository(sa_sync_conn),
        )

        assert _get_person_id_of_oa_authorship(sa_sync_conn, oa_as) is None


# ── Étape 2 : ORCID connu ───────────────────────────────────────


class TestStep2Orcid:
    def test_known_orcid_links(self, sa_sync_conn):
        """ORCID déjà en base (confirmed) → rattache à la bonne personne."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step2_orcid,
        )

        pub = _insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        add_identifier(
            person_id,
            "orcid",
            "0000-0001-2345-6789",
            source="hal",
            status="confirmed",
            repo=person_repository(sa_sync_conn),
        )

        oa_author = _insert_oa_author(sa_sync_conn, "J Dupont", "A333")
        oa_doc = _insert_oa_document(sa_sync_conn, "W333", pub)
        oa_as = _insert_oa_authorship(
            sa_sync_conn,
            oa_doc,
            oa_author,
            position=0,
            raw_author_name="J Dupont",
            identifiers={"orcid": "0000-0001-2345-6789"},
        )

        all_as = get_all_unlinked_authorships(sa_sync_conn, _queries)
        linked_ids = set()
        step2_orcid(
            sa_sync_conn,
            _queries,
            _logger,
            all_as,
            linked_ids,
            dry_run=False,
            person_repo=person_repository(sa_sync_conn),
        )

        assert _get_person_id_of_oa_authorship(sa_sync_conn, oa_as) == person_id

    def test_orcid_match_imports_other_identifiers(self, sa_sync_conn):
        """Rattachement par ORCID → les autres identifiants (IdRef) sont aussi importés."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step2_orcid,
        )

        pub = _insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        add_identifier(
            person_id,
            "orcid",
            "0000-0001-2345-6789",
            source="hal",
            status="confirmed",
            repo=person_repository(sa_sync_conn),
        )

        # HAL author avec même ORCID + un IdRef
        ha = _insert_hal_author(
            sa_sync_conn, "Jean Dupont", hal_person_id=None, orcid="0000-0001-2345-6789"
        )
        # Ajouter idref manuellement (helper ne le gère pas)
        sa_sync_conn.execute(
            text("UPDATE source_persons SET idref = :idref WHERE id = :sp_id"),
            {"idref": "123456789", "sp_id": ha},
        )

        hd = _insert_hal_document(sa_sync_conn, "hal-orcid-idref", pub)
        _insert_hal_authorship(sa_sync_conn, hd, ha, position=0)

        all_as = get_all_unlinked_authorships(sa_sync_conn, _queries)
        linked_ids = set()
        step2_orcid(
            sa_sync_conn,
            _queries,
            _logger,
            all_as,
            linked_ids,
            dry_run=False,
            person_repo=person_repository(sa_sync_conn),
        )

        ids = _get_person_identifiers(sa_sync_conn, person_id)
        assert ("idref", "123456789") in ids

    def test_rejected_orcid_ignored(self, sa_sync_conn):
        """ORCID rejeté en base → pas de rattachement."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step2_orcid,
        )

        pub = _insert_publication(sa_sync_conn)
        person_id = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        add_identifier(
            person_id,
            "orcid",
            "0000-0001-9999-0000",
            source="hal",
            status="rejected",
            repo=person_repository(sa_sync_conn),
        )

        oa_author = _insert_oa_author(sa_sync_conn, "J Dupont", "A444")
        oa_doc = _insert_oa_document(sa_sync_conn, "W444", pub)
        oa_as = _insert_oa_authorship(
            sa_sync_conn,
            oa_doc,
            oa_author,
            position=0,
            raw_author_name="J Dupont",
        )

        all_as = get_all_unlinked_authorships(sa_sync_conn, _queries)
        linked_ids = set()
        step2_orcid(
            sa_sync_conn,
            _queries,
            _logger,
            all_as,
            linked_ids,
            dry_run=False,
            person_repo=person_repository(sa_sync_conn),
        )

        assert _get_person_id_of_oa_authorship(sa_sync_conn, oa_as) is None

    def test_unknown_orcid_not_linked(self, sa_sync_conn):
        """ORCID absent de la base → pas de rattachement (sera traité par name_forms)."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step2_orcid,
        )

        pub = _insert_publication(sa_sync_conn)
        oa_author = _insert_oa_author(sa_sync_conn, "Nobody", "A555", orcid="0000-9999-9999-9999")
        oa_doc = _insert_oa_document(sa_sync_conn, "W555", pub)
        oa_as = _insert_oa_authorship(
            sa_sync_conn,
            oa_doc,
            oa_author,
            position=0,
            raw_author_name="Nobody",
        )

        all_as = get_all_unlinked_authorships(sa_sync_conn, _queries)
        linked_ids = set()
        step2_orcid(
            sa_sync_conn,
            _queries,
            _logger,
            all_as,
            linked_ids,
            dry_run=False,
            person_repo=person_repository(sa_sync_conn),
        )

        assert _get_person_id_of_oa_authorship(sa_sync_conn, oa_as) is None


# ── Étape 3 : Name forms ────────────────────────────────────────


class TestStep3NameForms:
    def test_known_name_form_links(self, sa_sync_conn):
        """Forme de nom connue, mappée à 1 personne → rattache."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step3_name_forms,
        )

        pub = _insert_publication(sa_sync_conn)
        person_id = create_person("Martin", "Pierre", repo=person_repository(sa_sync_conn))
        # create_person crée déjà les name_forms via refresh_person_name_forms

        oa_author = _insert_oa_author(sa_sync_conn, "Pierre Martin", "A666")
        oa_doc = _insert_oa_document(sa_sync_conn, "W666", pub)
        oa_as = _insert_oa_authorship(
            sa_sync_conn, oa_doc, oa_author, position=0, raw_author_name="Pierre Martin"
        )

        all_as = get_all_unlinked_authorships(sa_sync_conn, _queries)
        linked_ids = set()
        name_form_map = _queries.fetch_name_form_map(sa_sync_conn)
        step3_name_forms(
            _logger,
            all_as,
            linked_ids,
            name_form_map,
            dry_run=False,
            person_repo=person_repository(sa_sync_conn),
        )

        assert _get_person_id_of_oa_authorship(sa_sync_conn, oa_as) == person_id

    def test_ambiguous_name_form_orphan(self, sa_sync_conn):
        """Forme de nom mappée à 2 personnes → orphelin."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step3_name_forms,
        )

        pub = _insert_publication(sa_sync_conn)
        pid1 = create_person("Dupont", "Jean", repo=person_repository(sa_sync_conn))
        pid2 = create_person("Dupont", "Jacques", repo=person_repository(sa_sync_conn))
        # "j dupont" est une forme ambiguë (initiale J → match les deux)
        add_name_form(pid1, "J Dupont", repo=person_repository(sa_sync_conn))
        add_name_form(pid2, "J Dupont", repo=person_repository(sa_sync_conn))

        oa_author = _insert_oa_author(sa_sync_conn, "J Dupont", "A777")
        oa_doc = _insert_oa_document(sa_sync_conn, "W777", pub)
        oa_as = _insert_oa_authorship(
            sa_sync_conn, oa_doc, oa_author, position=0, raw_author_name="J Dupont"
        )

        all_as = get_all_unlinked_authorships(sa_sync_conn, _queries)
        linked_ids = set()
        name_form_map = _queries.fetch_name_form_map(sa_sync_conn)
        step3_name_forms(
            _logger,
            all_as,
            linked_ids,
            name_form_map,
            dry_run=False,
            person_repo=person_repository(sa_sync_conn),
        )

        # Doit rester orphelin
        assert _get_person_id_of_oa_authorship(sa_sync_conn, oa_as) is None

    def test_unknown_name_creates_person(self, sa_sync_conn):
        """Forme de nom inconnue → crée une nouvelle personne."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step3_name_forms,
        )

        pub = _insert_publication(sa_sync_conn)
        oa_author = _insert_oa_author(sa_sync_conn, "Inconnu Nouveau", "A888")
        oa_doc = _insert_oa_document(sa_sync_conn, "W888", pub)
        oa_as = _insert_oa_authorship(
            sa_sync_conn, oa_doc, oa_author, position=0, raw_author_name="Inconnu Nouveau"
        )

        all_as = get_all_unlinked_authorships(sa_sync_conn, _queries)
        linked_ids = set()
        name_form_map = _queries.fetch_name_form_map(sa_sync_conn)
        step3_name_forms(
            _logger,
            all_as,
            linked_ids,
            name_form_map,
            dry_run=False,
            person_repo=person_repository(sa_sync_conn),
        )

        pid = _get_person_id_of_oa_authorship(sa_sync_conn, oa_as)
        assert pid is not None

        # La personne doit exister
        last_name = sa_sync_conn.execute(
            text("SELECT last_name FROM persons WHERE id = :pid"), {"pid": pid}
        ).scalar_one()
        assert last_name == "Nouveau"
