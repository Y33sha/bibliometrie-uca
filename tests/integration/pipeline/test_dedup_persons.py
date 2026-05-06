"""Tests d'intégration — déduplication des personnes.

Teste la logique de create_persons_from_source_authorships.py
avec une vraie base PostgreSQL (bibliometrie_test).
Chaque test tourne dans une transaction rollbackée (isolation complète).
"""

import logging

from application.persons import add_identifier, add_name_form, create_person
from infrastructure.db.queries.persons.create import PgPersonsCreateQueries
from infrastructure.repositories import person_repository

_queries = PgPersonsCreateQueries()
_logger = logging.getLogger("test")

# ── Helpers ──────────────────────────────────────────────────────


def _insert_publication(db, title="Test Pub", pub_year=2024):
    """Crée une publication minimale."""
    from domain.normalize import normalize_text

    db.execute(
        """
        INSERT INTO publications (title, title_normalized, doc_type, pub_year)
        VALUES (%s, %s, 'article', %s) RETURNING id
    """,
        (title, normalize_text(title), pub_year),
    )
    return db.fetchone()["id"]


def _insert_hal_author(db, full_name, hal_person_id=None, orcid=None, idhal=None):
    """Crée un source_author HAL minimal."""
    import json

    source_ids = {}
    if hal_person_id is not None:
        source_ids["hal_person_id"] = hal_person_id
    if idhal is not None:
        source_ids["idhal"] = idhal
    db.execute(
        """
        INSERT INTO source_persons (source, source_id, full_name, orcid, source_ids)
        VALUES ('hal', %s, %s, %s, %s) RETURNING id
    """,
        (
            f"hal-{full_name}",
            full_name,
            orcid,
            json.dumps(source_ids) if source_ids else None,
        ),
    )
    return db.fetchone()["id"]


def _insert_hal_document(db, halid, publication_id):
    """Crée un source_document minimal (source='hal')."""
    db.execute(
        """
        INSERT INTO source_publications (source, source_id, title, pub_year, publication_id)
        VALUES ('hal', %s, 'Test', 2024, %s) RETURNING id
    """,
        (halid, publication_id),
    )
    return db.fetchone()["id"]


def _insert_hal_authorship(
    db,
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
        db.execute("SELECT full_name FROM source_persons WHERE id = %s", (source_person_id,))
        row = db.fetchone()
        raw_author_name = row["full_name"] if row else None
    db.execute(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position,
             in_perimeter, person_id, raw_author_name)
        VALUES ('hal', %s, %s, %s, %s, %s, %s) RETURNING id
    """,
        (
            source_publication_id,
            source_person_id,
            position,
            in_perimeter,
            person_id,
            raw_author_name,
        ),
    )
    return db.fetchone()["id"]


def _insert_oa_author(db, full_name, openalex_id, orcid=None):
    """Crée un source_author OpenAlex minimal."""
    db.execute(
        """
        INSERT INTO source_persons (source, source_id, full_name, orcid)
        VALUES ('openalex', %s, %s, %s) RETURNING id
    """,
        (openalex_id, full_name, orcid),
    )
    return db.fetchone()["id"]


def _insert_oa_document(db, openalex_id, publication_id):
    """Crée un source_document minimal (source='openalex')."""
    db.execute(
        """
        INSERT INTO source_publications (source, source_id, title, pub_year, publication_id)
        VALUES ('openalex', %s, 'Test', 2024, %s) RETURNING id
    """,
        (openalex_id, publication_id),
    )
    return db.fetchone()["id"]


def _insert_oa_authorship(
    db,
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
    sur `source_authorships.identifiers` (JSONB), pas sur `source_persons`
    — le pipeline de dédup-personnes lit `sa.identifiers->>'orcid'`.
    """
    import json

    db.execute(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position,
             in_perimeter, person_id, raw_author_name, identifiers)
        VALUES ('openalex', %s, %s, %s, %s, %s, %s, %s) RETURNING id
    """,
        (
            oa_document_id,
            oa_author_id,
            position,
            in_perimeter,
            person_id,
            raw_author_name,
            json.dumps(identifiers) if identifiers else None,
        ),
    )
    return db.fetchone()["id"]


def _get_person_id_of_hal_authorship(db, authorship_id):
    db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (authorship_id,))
    row = db.fetchone()
    return row["person_id"] if row else None


def _get_person_id_of_oa_authorship(db, authorship_id):
    db.execute("SELECT person_id FROM source_authorships WHERE id = %s", (authorship_id,))
    row = db.fetchone()
    return row["person_id"] if row else None


def _get_person_identifiers(db, person_id):
    """Retourne les identifiants d'une personne : {(id_type, id_value), ...}"""
    db.execute(
        "SELECT id_type, id_value FROM person_identifiers WHERE person_id = %s", (person_id,)
    )
    return {(r["id_type"], r["id_value"]) for r in db.fetchall()}


# ── Étape 0 : Comptes HAL ───────────────────────────────────────


class TestStep0HalAccounts:
    def test_existing_person_propagates(self, db):
        """hal_author avec hal_person_id déjà rattaché → propage aux nouvelles authorships."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step0_hal_accounts,
        )

        pub1 = _insert_publication(db, "Pub 1")
        pub2 = _insert_publication(db, "Pub 2")

        # Personne existante + hal_author rattaché
        person_id = create_person(db, "Dupont", "Jean", repo=person_repository(db))
        ha = _insert_hal_author(db, "Jean Dupont", hal_person_id=12345)
        db.execute("UPDATE source_persons SET person_id = %s WHERE id = %s", (person_id, ha))

        hd1 = _insert_hal_document(db, "hal-001", pub1)
        hd2 = _insert_hal_document(db, "hal-002", pub2)
        has1 = _insert_hal_authorship(db, hd1, ha, position=0)
        has2 = _insert_hal_authorship(db, hd2, ha, position=0)

        all_as = get_all_unlinked_authorships(db, _queries)
        linked_ids = set()
        step0_hal_accounts(
            db,
            _queries,
            _logger,
            all_as,
            linked_ids,
            dry_run=False,
            person_repo=person_repository(db),
        )

        assert _get_person_id_of_hal_authorship(db, has1) == person_id
        assert _get_person_id_of_hal_authorship(db, has2) == person_id

    def test_virgin_hal_account_skipped(self, db):
        """hal_author avec hal_person_id mais sans person_id → ignoré par passe 0."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step0_hal_accounts,
        )

        pub = _insert_publication(db, "Pub vierge")
        ha = _insert_hal_author(db, "Népomucène Bensoussan", hal_person_id=99999)
        hd = _insert_hal_document(db, "hal-virgin", pub)
        has_id = _insert_hal_authorship(db, hd, ha, position=0)

        all_as = get_all_unlinked_authorships(db, _queries)
        linked_ids = set()
        step0_hal_accounts(
            db,
            _queries,
            _logger,
            all_as,
            linked_ids,
            dry_run=False,
            person_repo=person_repository(db),
        )

        # Pas de rattachement en passe 0
        assert _get_person_id_of_hal_authorship(db, has_id) is None
        # L'authorship ne doit pas être marquée comme traitée
        assert ("hal", has_id) not in linked_ids

    def test_virgin_hal_account_matched_by_name(self, db):
        """hal_author vierge → ignoré en passe 0, rattaché par nom en passe 3."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step0_hal_accounts,
            step3_name_forms,
        )

        pub = _insert_publication(db)

        # Personne existante (créée par un import précédent)
        person_id = create_person(db, "Bensoussan", "Népomucène", repo=person_repository(db))

        # Nouveau hal_author vierge, même nom
        ha = _insert_hal_author(
            db, "Népomucène Bensoussan", hal_person_id=88888, orcid="0000-0001-1111-2222"
        )
        hd = _insert_hal_document(db, "hal-nepo", pub)
        has_id = _insert_hal_authorship(db, hd, ha, position=0)

        all_as = get_all_unlinked_authorships(db, _queries)
        linked_ids = set()

        # Passe 0 : ignoré
        step0_hal_accounts(
            db,
            _queries,
            _logger,
            all_as,
            linked_ids,
            dry_run=False,
            person_repo=person_repository(db),
        )
        assert _get_person_id_of_hal_authorship(db, has_id) is None

        # Passe 3 : rattaché par nom
        name_form_map = _queries.fetch_name_form_map(db)
        step3_name_forms(
            db,
            _logger,
            all_as,
            linked_ids,
            name_form_map,
            dry_run=False,
            person_repo=person_repository(db),
        )
        assert _get_person_id_of_hal_authorship(db, has_id) == person_id


# ── Étape 1 : Cross-source ──────────────────────────────────────


class TestStep1CrossSource:
    def test_same_pub_same_position_compatible_name(self, db):
        """Même publi, même position, nom compatible → rattache à la même personne."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            load_linked_authorships_by_pub,
            step1_cross_source,
        )

        pub = _insert_publication(db, "Shared Publication")

        # Personne existante rattachée via HAL
        person_id = create_person(db, "Dupont", "Jean", repo=person_repository(db))
        ha = _insert_hal_author(db, "Jean Dupont", hal_person_id=111)
        hd = _insert_hal_document(db, "hal-100", pub)
        _insert_hal_authorship(db, hd, ha, position=3, person_id=person_id)

        # Authorship OA non rattachée, même publi, même position
        oa_author = _insert_oa_author(db, "J Dupont", "A111")
        oa_doc = _insert_oa_document(db, "W111", pub)
        oa_as = _insert_oa_authorship(db, oa_doc, oa_author, position=3, raw_author_name="J Dupont")

        all_as = get_all_unlinked_authorships(db, _queries)
        linked_ids = set()
        linked_index = load_linked_authorships_by_pub(db, _queries)
        step1_cross_source(
            db,
            _logger,
            all_as,
            linked_ids,
            linked_index,
            dry_run=False,
            person_repo=person_repository(db),
        )

        assert _get_person_id_of_oa_authorship(db, oa_as) == person_id

    def test_cross_source_imports_identifiers(self, db):
        """Cross-source rattachement → les identifiants de l'authorship sont importés."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            load_linked_authorships_by_pub,
            step1_cross_source,
        )

        pub = _insert_publication(db)

        person_id = create_person(db, "Dupont", "Jean", repo=person_repository(db))
        ha = _insert_hal_author(db, "Jean Dupont", hal_person_id=111)
        hd = _insert_hal_document(db, "hal-id-test", pub)
        _insert_hal_authorship(db, hd, ha, position=0, person_id=person_id)

        # OA authorship avec ORCID porté par identifiers (cf. chantier
        # source_persons : pour OA/WoS/CrossRef, l'ORCID vit sur
        # source_authorships.identifiers, pas sur source_persons).
        oa_author = _insert_oa_author(db, "J Dupont", "A-id1")
        oa_doc = _insert_oa_document(db, "W-id1", pub)
        _insert_oa_authorship(
            db,
            oa_doc,
            oa_author,
            position=0,
            raw_author_name="J Dupont",
            identifiers={"orcid": "0000-0001-9999-8888"},
        )

        all_as = get_all_unlinked_authorships(db, _queries)
        linked_ids = set()
        linked_index = load_linked_authorships_by_pub(db, _queries)
        step1_cross_source(
            db,
            _logger,
            all_as,
            linked_ids,
            linked_index,
            dry_run=False,
            person_repo=person_repository(db),
        )

        ids = _get_person_identifiers(db, person_id)
        assert ("orcid", "0000-0001-9999-8888") in ids

    def test_same_pub_different_position_no_match(self, db):
        """Même publi mais position différente → pas de rattachement."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            load_linked_authorships_by_pub,
            step1_cross_source,
        )

        pub = _insert_publication(db)

        person_id = create_person(db, "Dupont", "Jean", repo=person_repository(db))
        ha = _insert_hal_author(db, "Jean Dupont", hal_person_id=222)
        hd = _insert_hal_document(db, "hal-200", pub)
        _insert_hal_authorship(db, hd, ha, position=0, person_id=person_id)

        oa_author = _insert_oa_author(db, "J Dupont", "A222")
        oa_doc = _insert_oa_document(db, "W222", pub)
        oa_as = _insert_oa_authorship(db, oa_doc, oa_author, position=5, raw_author_name="J Dupont")

        all_as = get_all_unlinked_authorships(db, _queries)
        linked_ids = set()
        linked_index = load_linked_authorships_by_pub(db, _queries)
        step1_cross_source(
            db,
            _logger,
            all_as,
            linked_ids,
            linked_index,
            dry_run=False,
            person_repo=person_repository(db),
        )

        assert _get_person_id_of_oa_authorship(db, oa_as) is None


# ── Étape 2 : ORCID connu ───────────────────────────────────────


class TestStep2Orcid:
    def test_known_orcid_links(self, db):
        """ORCID déjà en base (confirmed) → rattache à la bonne personne."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step2_orcid,
        )

        pub = _insert_publication(db)
        person_id = create_person(db, "Dupont", "Jean", repo=person_repository(db))
        add_identifier(
            db,
            person_id,
            "orcid",
            "0000-0001-2345-6789",
            source="hal",
            status="confirmed",
            repo=person_repository(db),
        )

        oa_author = _insert_oa_author(db, "J Dupont", "A333")
        oa_doc = _insert_oa_document(db, "W333", pub)
        oa_as = _insert_oa_authorship(
            db,
            oa_doc,
            oa_author,
            position=0,
            raw_author_name="J Dupont",
            identifiers={"orcid": "0000-0001-2345-6789"},
        )

        all_as = get_all_unlinked_authorships(db, _queries)
        linked_ids = set()
        step2_orcid(
            db,
            _queries,
            _logger,
            all_as,
            linked_ids,
            dry_run=False,
            person_repo=person_repository(db),
        )

        assert _get_person_id_of_oa_authorship(db, oa_as) == person_id

    def test_orcid_match_imports_other_identifiers(self, db):
        """Rattachement par ORCID → les autres identifiants (IdRef) sont aussi importés."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step2_orcid,
        )

        pub = _insert_publication(db)
        person_id = create_person(db, "Dupont", "Jean", repo=person_repository(db))
        add_identifier(
            db,
            person_id,
            "orcid",
            "0000-0001-2345-6789",
            source="hal",
            status="confirmed",
            repo=person_repository(db),
        )

        # HAL author avec même ORCID + un IdRef
        ha = _insert_hal_author(db, "Jean Dupont", hal_person_id=None, orcid="0000-0001-2345-6789")
        # Ajouter idref manuellement (helper ne le gère pas)
        db.execute("UPDATE source_persons SET idref = %s WHERE id = %s", ("123456789", ha))

        hd = _insert_hal_document(db, "hal-orcid-idref", pub)
        _insert_hal_authorship(db, hd, ha, position=0)

        all_as = get_all_unlinked_authorships(db, _queries)
        linked_ids = set()
        step2_orcid(
            db,
            _queries,
            _logger,
            all_as,
            linked_ids,
            dry_run=False,
            person_repo=person_repository(db),
        )

        ids = _get_person_identifiers(db, person_id)
        assert ("idref", "123456789") in ids

    def test_rejected_orcid_ignored(self, db):
        """ORCID rejeté en base → pas de rattachement."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step2_orcid,
        )

        pub = _insert_publication(db)
        person_id = create_person(db, "Dupont", "Jean", repo=person_repository(db))
        add_identifier(
            db,
            person_id,
            "orcid",
            "0000-0001-9999-0000",
            source="hal",
            status="rejected",
            repo=person_repository(db),
        )

        oa_author = _insert_oa_author(db, "J Dupont", "A444")
        oa_doc = _insert_oa_document(db, "W444", pub)
        oa_as = _insert_oa_authorship(
            db,
            oa_doc,
            oa_author,
            position=0,
            raw_author_name="J Dupont",
        )

        all_as = get_all_unlinked_authorships(db, _queries)
        linked_ids = set()
        step2_orcid(
            db,
            _queries,
            _logger,
            all_as,
            linked_ids,
            dry_run=False,
            person_repo=person_repository(db),
        )

        assert _get_person_id_of_oa_authorship(db, oa_as) is None

    def test_unknown_orcid_not_linked(self, db):
        """ORCID absent de la base → pas de rattachement (sera traité par name_forms)."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step2_orcid,
        )

        pub = _insert_publication(db)
        oa_author = _insert_oa_author(db, "Nobody", "A555", orcid="0000-9999-9999-9999")
        oa_doc = _insert_oa_document(db, "W555", pub)
        oa_as = _insert_oa_authorship(
            db,
            oa_doc,
            oa_author,
            position=0,
            raw_author_name="Nobody",
        )

        all_as = get_all_unlinked_authorships(db, _queries)
        linked_ids = set()
        step2_orcid(
            db,
            _queries,
            _logger,
            all_as,
            linked_ids,
            dry_run=False,
            person_repo=person_repository(db),
        )

        assert _get_person_id_of_oa_authorship(db, oa_as) is None


# ── Étape 3 : Name forms ────────────────────────────────────────


class TestStep3NameForms:
    def test_known_name_form_links(self, db):
        """Forme de nom connue, mappée à 1 personne → rattache."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step3_name_forms,
        )

        pub = _insert_publication(db)
        person_id = create_person(db, "Martin", "Pierre", repo=person_repository(db))
        # create_person crée déjà les name_forms via refresh_person_name_forms

        oa_author = _insert_oa_author(db, "Pierre Martin", "A666")
        oa_doc = _insert_oa_document(db, "W666", pub)
        oa_as = _insert_oa_authorship(
            db, oa_doc, oa_author, position=0, raw_author_name="Pierre Martin"
        )

        all_as = get_all_unlinked_authorships(db, _queries)
        linked_ids = set()
        name_form_map = _queries.fetch_name_form_map(db)
        step3_name_forms(
            db,
            _logger,
            all_as,
            linked_ids,
            name_form_map,
            dry_run=False,
            person_repo=person_repository(db),
        )

        assert _get_person_id_of_oa_authorship(db, oa_as) == person_id

    def test_ambiguous_name_form_orphan(self, db):
        """Forme de nom mappée à 2 personnes → orphelin."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step3_name_forms,
        )

        pub = _insert_publication(db)
        pid1 = create_person(db, "Dupont", "Jean", repo=person_repository(db))
        pid2 = create_person(db, "Dupont", "Jacques", repo=person_repository(db))
        # "j dupont" est une forme ambiguë (initiale J → match les deux)
        add_name_form(db, pid1, "J Dupont", repo=person_repository(db))
        add_name_form(db, pid2, "J Dupont", repo=person_repository(db))

        oa_author = _insert_oa_author(db, "J Dupont", "A777")
        oa_doc = _insert_oa_document(db, "W777", pub)
        oa_as = _insert_oa_authorship(db, oa_doc, oa_author, position=0, raw_author_name="J Dupont")

        all_as = get_all_unlinked_authorships(db, _queries)
        linked_ids = set()
        name_form_map = _queries.fetch_name_form_map(db)
        step3_name_forms(
            db,
            _logger,
            all_as,
            linked_ids,
            name_form_map,
            dry_run=False,
            person_repo=person_repository(db),
        )

        # Doit rester orphelin
        assert _get_person_id_of_oa_authorship(db, oa_as) is None

    def test_unknown_name_creates_person(self, db):
        """Forme de nom inconnue → crée une nouvelle personne."""
        from application.pipeline.persons.create_persons_from_source_authorships import (
            get_all_unlinked_authorships,
            step3_name_forms,
        )

        pub = _insert_publication(db)
        oa_author = _insert_oa_author(db, "Inconnu Nouveau", "A888")
        oa_doc = _insert_oa_document(db, "W888", pub)
        oa_as = _insert_oa_authorship(
            db, oa_doc, oa_author, position=0, raw_author_name="Inconnu Nouveau"
        )

        all_as = get_all_unlinked_authorships(db, _queries)
        linked_ids = set()
        name_form_map = _queries.fetch_name_form_map(db)
        step3_name_forms(
            db,
            _logger,
            all_as,
            linked_ids,
            name_form_map,
            dry_run=False,
            person_repo=person_repository(db),
        )

        pid = _get_person_id_of_oa_authorship(db, oa_as)
        assert pid is not None

        # La personne doit exister
        db.execute("SELECT last_name FROM persons WHERE id = %s", (pid,))
        assert db.fetchone()["last_name"] == "Nouveau"
