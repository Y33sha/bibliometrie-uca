"""Exceptions métier : champs structurés et message lisible."""

from domain.errors import (
    AuthorshipAlreadyAssignedError,
    CannotAttributeConflict,
    DistinctDoiError,
    PublisherMergeBlockedError,
    RejectedPairError,
)


def _paire_de_revues() -> dict:
    return {
        "target_journal_id": 1,
        "target_title": "Nature",
        "source_journal_id": 2,
        "source_title": "Nature",
        "reason": "ISSN différents : 0028-0836 vs 9999-9999",
    }


def _paire_rejetee() -> dict:
    return {"publication_id": 10, "person_id": 20, "rejected_at": "2026-01-01T00:00:00+00:00"}


class TestCannotAttributeConflict:
    def test_porte_les_champs_du_conflit(self):
        exc = CannotAttributeConflict(
            "ORCID déjà attribué",
            id_type="orcid",
            id_value="0000-0002-1825-0097",
            existing_person_id=42,
            existing_status="confirmed",
        )
        assert str(exc) == "ORCID déjà attribué"
        assert (exc.id_type, exc.id_value) == ("orcid", "0000-0002-1825-0097")
        assert (exc.existing_person_id, exc.existing_status) == (42, "confirmed")


class TestPublisherMergeBlockedError:
    def test_une_paire(self):
        paires = [_paire_de_revues()]
        exc = PublisherMergeBlockedError(paires)
        assert exc.blocking_journals == paires
        assert str(exc) == "Fusion bloquée par 1 paire de revues à traiter manuellement"

    def test_plusieurs_paires(self):
        exc = PublisherMergeBlockedError([_paire_de_revues(), _paire_de_revues()])
        assert str(exc) == "Fusion bloquée par 2 paires de revues à traiter manuellement"


class TestDistinctDoiError:
    def test_porte_les_deux_publications_et_leurs_doi(self):
        exc = DistinctDoiError(1, 2, "10.1/x", "10.2/y")
        assert (exc.target_id, exc.source_id) == (1, 2)
        assert (exc.target_doi, exc.source_doi) == ("10.1/x", "10.2/y")
        assert str(exc) == "Fusion refusée : #1 (10.1/x) et #2 (10.2/y) ont des DOI distincts"


class TestAuthorshipAlreadyAssignedError:
    def test_nomme_la_signature_et_sa_detentrice(self):
        exc = AuthorshipAlreadyAssignedError(7, 42)
        assert (exc.authorship_id, exc.owner_person_id) == (7, 42)
        assert str(exc) == (
            "La signature #7 est déjà attribuée à la personne #42 ; "
            "seule une signature orpheline peut être attribuée."
        )


class TestRejectedPairError:
    def test_une_paire(self):
        paires = [_paire_rejetee()]
        exc = RejectedPairError(paires)
        assert exc.rejected_pairs == paires
        assert str(exc) == "1 paire (publication, personne) déjà rejetée"

    def test_plusieurs_paires(self):
        exc = RejectedPairError([_paire_rejetee(), _paire_rejetee()])
        assert str(exc) == "2 paires (publication, personne) déjà rejetées"
