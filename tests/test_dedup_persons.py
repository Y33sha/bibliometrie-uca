"""Tests d'intégration — déduplication des personnes.

Teste la logique de create_persons_from_source_authorships.py
avec une vraie base PostgreSQL (bibliometrie_test).
Chaque test tourne dans une transaction rollbackée (isolation complète).
"""

import pytest
from utils.normalize import normalize_name
from services.persons import create_person, add_identifier, add_name_form


# ── Helpers ──────────────────────────────────────────────────────

def _insert_publication(db, title="Test Pub", pub_year=2024):
    """Crée une publication minimale."""
    from utils.normalize import normalize_text
    db.execute("""
        INSERT INTO publications (title, title_normalized, doc_type, pub_year)
        VALUES (%s, %s, 'article', %s) RETURNING id
    """, (title, normalize_text(title), pub_year))
    return db.fetchone()["id"]


def _insert_hal_author(db, full_name, hal_person_id=None, orcid=None, idhal=None):
    """Crée un source_author HAL minimal."""
    parts = full_name.strip().split()
    last = parts[-1] if len(parts) >= 2 else full_name
    first = " ".join(parts[:-1]) if len(parts) >= 2 else None
    import json
    source_ids = {}
    if hal_person_id is not None:
        source_ids["hal_person_id"] = hal_person_id
    if idhal is not None:
        source_ids["idhal"] = idhal
    db.execute("""
        INSERT INTO source_persons (source, source_id, full_name, last_name, first_name,
                                    orcid, source_ids)
        VALUES ('hal', %s, %s, %s, %s, %s, %s) RETURNING id
    """, (f"hal-{full_name}", full_name, last, first, orcid,
          json.dumps(source_ids) if source_ids else None))
    return db.fetchone()["id"]


def _insert_hal_document(db, halid, publication_id):
    """Crée un source_document minimal (source='hal')."""
    db.execute("""
        INSERT INTO source_publications (source, source_id, title, pub_year, publication_id)
        VALUES ('hal', %s, 'Test', 2024, %s) RETURNING id
    """, (halid, publication_id))
    return db.fetchone()["id"]


def _insert_hal_authorship(db, source_publication_id, source_person_id, position=0,
                           in_perimeter=True, person_id=None):
    """Crée une source_authorship HAL."""
    db.execute("""
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position, in_perimeter, person_id)
        VALUES ('hal', %s, %s, %s, %s, %s) RETURNING id
    """, (source_publication_id, source_person_id, position, in_perimeter, person_id))
    return db.fetchone()["id"]


def _insert_oa_author(db, full_name, openalex_id, orcid=None):
    """Crée un source_author OpenAlex minimal."""
    parts = full_name.strip().split()
    last = parts[-1] if len(parts) >= 2 else full_name
    first = " ".join(parts[:-1]) if len(parts) >= 2 else None
    db.execute("""
        INSERT INTO source_persons (source, source_id, full_name, last_name, first_name, orcid)
        VALUES ('openalex', %s, %s, %s, %s, %s) RETURNING id
    """, (openalex_id, full_name, last, first, orcid))
    return db.fetchone()["id"]


def _insert_oa_document(db, openalex_id, publication_id):
    """Crée un source_document minimal (source='openalex')."""
    db.execute("""
        INSERT INTO source_publications (source, source_id, title, pub_year, publication_id)
        VALUES ('openalex', %s, 'Test', 2024, %s) RETURNING id
    """, (openalex_id, publication_id))
    return db.fetchone()["id"]


def _insert_oa_authorship(db, oa_document_id, oa_author_id, position=0,
                          in_perimeter=True, person_id=None, raw_author_name=None):
    """Crée une source_authorship OpenAlex."""
    db.execute("""
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position,
             in_perimeter, person_id, raw_author_name)
        VALUES ('openalex', %s, %s, %s, %s, %s, %s) RETURNING id
    """, (oa_document_id, oa_author_id, position, in_perimeter, person_id,
          raw_author_name))
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
        "SELECT id_type, id_value FROM person_identifiers WHERE person_id = %s",
        (person_id,))
    return {(r["id_type"], r["id_value"]) for r in db.fetchall()}


# ── Étape 0 : Comptes HAL ───────────────────────────────────────

class TestStep0HalAccounts:
    def test_existing_person_propagates(self, db):
        """hal_author avec hal_person_id déjà rattaché → propage aux nouvelles authorships."""
        from processing.create_persons_from_source_authorships import (
            get_all_unlinked_authorships, step0_hal_accounts,
        )
        pub1 = _insert_publication(db, "Pub 1")
        pub2 = _insert_publication(db, "Pub 2")

        # Personne existante + hal_author rattaché
        person_id = create_person(db, "Dupont", "Jean")
        ha = _insert_hal_author(db, "Jean Dupont", hal_person_id=12345)
        db.execute("UPDATE source_persons SET person_id = %s WHERE id = %s",
                   (person_id, ha))

        hd1 = _insert_hal_document(db, "hal-001", pub1)
        hd2 = _insert_hal_document(db, "hal-002", pub2)
        has1 = _insert_hal_authorship(db, hd1, ha, position=0)
        has2 = _insert_hal_authorship(db, hd2, ha, position=0)

        all_as = get_all_unlinked_authorships(db)
        linked_ids = set()
        step0_hal_accounts(db, all_as, linked_ids, dry_run=False)

        assert _get_person_id_of_hal_authorship(db, has1) == person_id
        assert _get_person_id_of_hal_authorship(db, has2) == person_id

    def test_virgin_hal_account_skipped(self, db):
        """hal_author avec hal_person_id mais sans person_id → ignoré par passe 0."""
        from processing.create_persons_from_source_authorships import (
            get_all_unlinked_authorships, step0_hal_accounts,
        )
        pub = _insert_publication(db, "Pub vierge")
        ha = _insert_hal_author(db, "Népomucène Bensoussan", hal_person_id=99999)
        hd = _insert_hal_document(db, "hal-virgin", pub)
        has_id = _insert_hal_authorship(db, hd, ha, position=0)

        all_as = get_all_unlinked_authorships(db)
        linked_ids = set()
        step0_hal_accounts(db, all_as, linked_ids, dry_run=False)

        # Pas de rattachement en passe 0
        assert _get_person_id_of_hal_authorship(db, has_id) is None
        # L'authorship ne doit pas être marquée comme traitée
        assert ("hal", has_id) not in linked_ids

    def test_virgin_hal_account_matched_by_name(self, db):
        """hal_author vierge → ignoré en passe 0, rattaché par nom en passe 3."""
        from processing.create_persons_from_source_authorships import (
            get_all_unlinked_authorships, step0_hal_accounts,
            step3_name_forms, load_name_form_map,
        )
        pub = _insert_publication(db)

        # Personne existante (créée par un import précédent)
        person_id = create_person(db, "Bensoussan", "Népomucène")

        # Nouveau hal_author vierge, même nom
        ha = _insert_hal_author(db, "Népomucène Bensoussan",
                                hal_person_id=88888, orcid="0000-0001-1111-2222")
        hd = _insert_hal_document(db, "hal-nepo", pub)
        has_id = _insert_hal_authorship(db, hd, ha, position=0)

        all_as = get_all_unlinked_authorships(db)
        linked_ids = set()

        # Passe 0 : ignoré
        step0_hal_accounts(db, all_as, linked_ids, dry_run=False)
        assert _get_person_id_of_hal_authorship(db, has_id) is None

        # Passe 3 : rattaché par nom
        name_form_map = load_name_form_map(db)
        step3_name_forms(db, all_as, linked_ids, name_form_map, dry_run=False)
        assert _get_person_id_of_hal_authorship(db, has_id) == person_id


# ── Étape 1 : Cross-source ──────────────────────────────────────

class TestStep1CrossSource:
    def test_same_pub_same_position_compatible_name(self, db):
        """Même publi, même position, nom compatible → rattache à la même personne."""
        from processing.create_persons_from_source_authorships import (
            get_all_unlinked_authorships, step1_cross_source,
            load_linked_authorships_by_pub,
        )
        pub = _insert_publication(db, "Shared Publication")

        # Personne existante rattachée via HAL
        person_id = create_person(db, "Dupont", "Jean")
        ha = _insert_hal_author(db, "Jean Dupont", hal_person_id=111)
        hd = _insert_hal_document(db, "hal-100", pub)
        _insert_hal_authorship(db, hd, ha, position=3, person_id=person_id)

        # Authorship OA non rattachée, même publi, même position
        oa_author = _insert_oa_author(db, "J Dupont", "A111")
        oa_doc = _insert_oa_document(db, "W111", pub)
        oa_as = _insert_oa_authorship(db, oa_doc, oa_author, position=3,
                                      raw_author_name="J Dupont")

        all_as = get_all_unlinked_authorships(db)
        linked_ids = set()
        linked_index = load_linked_authorships_by_pub(db)
        step1_cross_source(db, all_as, linked_ids, linked_index, dry_run=False)

        assert _get_person_id_of_oa_authorship(db, oa_as) == person_id

    def test_cross_source_imports_identifiers(self, db):
        """Cross-source rattachement → les identifiants de l'authorship sont importés."""
        from processing.create_persons_from_source_authorships import (
            get_all_unlinked_authorships, step1_cross_source,
            load_linked_authorships_by_pub,
        )
        pub = _insert_publication(db)

        person_id = create_person(db, "Dupont", "Jean")
        ha = _insert_hal_author(db, "Jean Dupont", hal_person_id=111)
        hd = _insert_hal_document(db, "hal-id-test", pub)
        _insert_hal_authorship(db, hd, ha, position=0, person_id=person_id)

        # OA authorship avec ORCID, même publi, même position
        oa_author = _insert_oa_author(db, "J Dupont", "A-id1",
                                      orcid="0000-0001-9999-8888")
        oa_doc = _insert_oa_document(db, "W-id1", pub)
        _insert_oa_authorship(db, oa_doc, oa_author, position=0,
                              raw_author_name="J Dupont")

        all_as = get_all_unlinked_authorships(db)
        linked_ids = set()
        linked_index = load_linked_authorships_by_pub(db)
        step1_cross_source(db, all_as, linked_ids, linked_index, dry_run=False)

        ids = _get_person_identifiers(db, person_id)
        assert ("orcid", "0000-0001-9999-8888") in ids

    def test_same_pub_different_position_no_match(self, db):
        """Même publi mais position différente → pas de rattachement."""
        from processing.create_persons_from_source_authorships import (
            get_all_unlinked_authorships, step1_cross_source,
            load_linked_authorships_by_pub,
        )
        pub = _insert_publication(db)

        person_id = create_person(db, "Dupont", "Jean")
        ha = _insert_hal_author(db, "Jean Dupont", hal_person_id=222)
        hd = _insert_hal_document(db, "hal-200", pub)
        _insert_hal_authorship(db, hd, ha, position=0, person_id=person_id)

        oa_author = _insert_oa_author(db, "J Dupont", "A222")
        oa_doc = _insert_oa_document(db, "W222", pub)
        oa_as = _insert_oa_authorship(db, oa_doc, oa_author, position=5,
                                      raw_author_name="J Dupont")

        all_as = get_all_unlinked_authorships(db)
        linked_ids = set()
        linked_index = load_linked_authorships_by_pub(db)
        step1_cross_source(db, all_as, linked_ids, linked_index, dry_run=False)

        assert _get_person_id_of_oa_authorship(db, oa_as) is None


# ── Étape 2 : ORCID connu ───────────────────────────────────────

class TestStep2Orcid:
    def test_known_orcid_links(self, db):
        """ORCID déjà en base (confirmed) → rattache à la bonne personne."""
        from processing.create_persons_from_source_authorships import (
            get_all_unlinked_authorships, step2_orcid,
        )
        pub = _insert_publication(db)
        person_id = create_person(db, "Dupont", "Jean")
        add_identifier(db, person_id, "orcid", "0000-0001-2345-6789",
                       source="hal", status="confirmed")

        oa_author = _insert_oa_author(db, "J Dupont", "A333", orcid="0000-0001-2345-6789")
        oa_doc = _insert_oa_document(db, "W333", pub)
        oa_as = _insert_oa_authorship(db, oa_doc, oa_author, position=0,
                                      raw_author_name="J Dupont",
)

        all_as = get_all_unlinked_authorships(db)
        linked_ids = set()
        step2_orcid(db, all_as, linked_ids, dry_run=False)

        assert _get_person_id_of_oa_authorship(db, oa_as) == person_id

    def test_orcid_match_imports_other_identifiers(self, db):
        """Rattachement par ORCID → les autres identifiants (IdRef) sont aussi importés."""
        from processing.create_persons_from_source_authorships import (
            get_all_unlinked_authorships, step2_orcid,
        )
        pub = _insert_publication(db)
        person_id = create_person(db, "Dupont", "Jean")
        add_identifier(db, person_id, "orcid", "0000-0001-2345-6789",
                       source="hal", status="confirmed")

        # HAL author avec même ORCID + un IdRef
        ha = _insert_hal_author(db, "Jean Dupont", hal_person_id=None,
                                orcid="0000-0001-2345-6789")
        # Ajouter idref manuellement (helper ne le gère pas)
        db.execute("UPDATE source_persons SET idref = %s WHERE id = %s",
                   ("123456789", ha))

        hd = _insert_hal_document(db, "hal-orcid-idref", pub)
        _insert_hal_authorship(db, hd, ha, position=0)

        all_as = get_all_unlinked_authorships(db)
        linked_ids = set()
        step2_orcid(db, all_as, linked_ids, dry_run=False)

        ids = _get_person_identifiers(db, person_id)
        assert ("idref", "123456789") in ids

    def test_rejected_orcid_ignored(self, db):
        """ORCID rejeté en base → pas de rattachement."""
        from processing.create_persons_from_source_authorships import (
            get_all_unlinked_authorships, step2_orcid,
        )
        pub = _insert_publication(db)
        person_id = create_person(db, "Dupont", "Jean")
        add_identifier(db, person_id, "orcid", "0000-0001-9999-0000",
                       source="hal", status="rejected")

        oa_author = _insert_oa_author(db, "J Dupont", "A444")
        oa_doc = _insert_oa_document(db, "W444", pub)
        oa_as = _insert_oa_authorship(db, oa_doc, oa_author, position=0,
                                      raw_author_name="J Dupont",
)

        all_as = get_all_unlinked_authorships(db)
        linked_ids = set()
        step2_orcid(db, all_as, linked_ids, dry_run=False)

        assert _get_person_id_of_oa_authorship(db, oa_as) is None

    def test_unknown_orcid_not_linked(self, db):
        """ORCID absent de la base → pas de rattachement (sera traité par name_forms)."""
        from processing.create_persons_from_source_authorships import (
            get_all_unlinked_authorships, step2_orcid,
        )
        pub = _insert_publication(db)
        oa_author = _insert_oa_author(db, "Nobody", "A555", orcid="0000-9999-9999-9999")
        oa_doc = _insert_oa_document(db, "W555", pub)
        oa_as = _insert_oa_authorship(db, oa_doc, oa_author, position=0,
                                      raw_author_name="Nobody",
)

        all_as = get_all_unlinked_authorships(db)
        linked_ids = set()
        step2_orcid(db, all_as, linked_ids, dry_run=False)

        assert _get_person_id_of_oa_authorship(db, oa_as) is None


# ── Étape 3 : Name forms ────────────────────────────────────────

class TestStep3NameForms:
    def test_known_name_form_links(self, db):
        """Forme de nom connue, mappée à 1 personne → rattache."""
        from processing.create_persons_from_source_authorships import (
            get_all_unlinked_authorships, step3_name_forms, load_name_form_map,
        )
        pub = _insert_publication(db)
        person_id = create_person(db, "Martin", "Pierre")
        # create_person crée déjà les name_forms via refresh_person_name_forms

        oa_author = _insert_oa_author(db, "Pierre Martin", "A666")
        oa_doc = _insert_oa_document(db, "W666", pub)
        oa_as = _insert_oa_authorship(db, oa_doc, oa_author, position=0,
                                      raw_author_name="Pierre Martin")

        all_as = get_all_unlinked_authorships(db)
        linked_ids = set()
        name_form_map = load_name_form_map(db)
        step3_name_forms(db, all_as, linked_ids, name_form_map, dry_run=False)

        assert _get_person_id_of_oa_authorship(db, oa_as) == person_id

    def test_ambiguous_name_form_orphan(self, db):
        """Forme de nom mappée à 2 personnes → orphelin."""
        from processing.create_persons_from_source_authorships import (
            get_all_unlinked_authorships, step3_name_forms, load_name_form_map,
        )
        pub = _insert_publication(db)
        pid1 = create_person(db, "Dupont", "Jean")
        pid2 = create_person(db, "Dupont", "Jacques")
        # "j dupont" est une forme ambiguë (initiale J → match les deux)
        add_name_form(db, pid1, "J Dupont")
        add_name_form(db, pid2, "J Dupont")

        oa_author = _insert_oa_author(db, "J Dupont", "A777")
        oa_doc = _insert_oa_document(db, "W777", pub)
        oa_as = _insert_oa_authorship(db, oa_doc, oa_author, position=0,
                                      raw_author_name="J Dupont")

        all_as = get_all_unlinked_authorships(db)
        linked_ids = set()
        name_form_map = load_name_form_map(db)
        step3_name_forms(db, all_as, linked_ids, name_form_map, dry_run=False)

        # Doit rester orphelin
        assert _get_person_id_of_oa_authorship(db, oa_as) is None

    def test_unknown_name_creates_person(self, db):
        """Forme de nom inconnue → crée une nouvelle personne."""
        from processing.create_persons_from_source_authorships import (
            get_all_unlinked_authorships, step3_name_forms, load_name_form_map,
        )
        pub = _insert_publication(db)
        oa_author = _insert_oa_author(db, "Inconnu Nouveau", "A888")
        oa_doc = _insert_oa_document(db, "W888", pub)
        oa_as = _insert_oa_authorship(db, oa_doc, oa_author, position=0,
                                      raw_author_name="Inconnu Nouveau")

        all_as = get_all_unlinked_authorships(db)
        linked_ids = set()
        name_form_map = load_name_form_map(db)
        step3_name_forms(db, all_as, linked_ids, name_form_map, dry_run=False)

        pid = _get_person_id_of_oa_authorship(db, oa_as)
        assert pid is not None

        # La personne doit exister
        db.execute("SELECT last_name FROM persons WHERE id = %s", (pid,))
        assert db.fetchone()["last_name"] == "Nouveau"
