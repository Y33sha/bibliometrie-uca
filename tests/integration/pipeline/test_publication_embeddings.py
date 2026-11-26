"""Tâche `encode_publications` : publications à encoder, texte encodé, plafond, sur vraie base, avec un encodeur factice."""

import logging
from collections.abc import Sequence
from contextlib import nullcontext

from sqlalchemy import text

from pipeline.transformation.publications.embeddings.encoding import encode_publications
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_record

_LOGGER = logging.getLogger(__name__)


class _Encoder:
    """Encodeur factice : vecteur de la longueur du texte, et textes reçus."""

    def __init__(self, model: str = "modele-a") -> None:
        self.model = model
        self.texts: list[str] = []

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        self.texts += texts
        return [[float(len(t)), 1.0] for t in texts]


def _encode(conn, encoder, limit=None):
    return encode_publications(lambda: nullcontext(conn), encoder, limit, _LOGGER)


def _abstract(conn, source_record: int, abstract: str) -> None:
    conn.execute(
        text("UPDATE source_records SET abstract = :a WHERE id = :id"),
        {"a": abstract, "id": source_record},
    )


def _rows(conn):
    return conn.execute(
        text(
            "SELECT publication_id, model, vector FROM publication_embeddings ORDER BY publication_id"
        )
    ).all()


def test_le_texte_encode_est_le_titre_suivi_du_plus_long_resume(sa_sync_conn):
    publication = insert_publication(sa_sync_conn, "Volcans d'Auvergne")
    _abstract(
        sa_sync_conn, insert_source_record(sa_sync_conn, publication, source_id="h1"), "Court."
    )
    _abstract(
        sa_sync_conn,
        insert_source_record(sa_sync_conn, publication, source="crossref", source_id="c1"),
        "Résumé plus long.",
    )
    encoder = _Encoder()

    metrics = _encode(sa_sync_conn, encoder)

    assert encoder.texts == ["Volcans d'Auvergne. Résumé plus long."]
    assert metrics.new == 1
    assert [(r.publication_id, r.model) for r in _rows(sa_sync_conn)] == [(publication, "modele-a")]


def test_une_publication_sans_resume_est_encodee_par_son_titre(sa_sync_conn):
    insert_publication(sa_sync_conn, "Titre seul")
    encoder = _Encoder()

    _encode(sa_sync_conn, encoder)

    assert encoder.texts == ["Titre seul"]


def test_une_publication_encodee_et_inchangee_n_est_pas_reencodee(sa_sync_conn):
    insert_publication(sa_sync_conn, "Titre")
    _encode(sa_sync_conn, _Encoder())
    encoder = _Encoder()

    metrics = _encode(sa_sync_conn, encoder)

    assert encoder.texts == []
    assert metrics.new == 0


def test_un_titre_modifie_ou_un_autre_modele_relance_l_encodage(sa_sync_conn):
    publication = insert_publication(sa_sync_conn, "Titre")
    _encode(sa_sync_conn, _Encoder())

    sa_sync_conn.execute(
        text("UPDATE publications SET title = 'Autre titre' WHERE id = :id"), {"id": publication}
    )
    retitled = _Encoder()
    _encode(sa_sync_conn, retitled)
    other_model = _Encoder("modele-b")
    _encode(sa_sync_conn, other_model)

    assert retitled.texts == ["Autre titre"]
    assert other_model.texts == ["Autre titre"]
    assert [r.model for r in _rows(sa_sync_conn)] == ["modele-b"]


def test_un_resume_modifie_au_dela_de_la_lecture_du_modele_ne_relance_pas_l_encodage(sa_sync_conn):
    publication = insert_publication(sa_sync_conn, "Titre")
    source_record = insert_source_record(sa_sync_conn, publication)
    _abstract(sa_sync_conn, source_record, "a" * 1500)
    _encode(sa_sync_conn, _Encoder())

    _abstract(sa_sync_conn, source_record, "a" * 1400 + "b" * 100)
    encoder = _Encoder()
    _encode(sa_sync_conn, encoder)

    assert encoder.texts == []


def test_le_plafond_borne_les_publications_encodees(sa_sync_conn):
    publications = [insert_publication(sa_sync_conn, f"Titre {i}") for i in range(3)]

    metrics = _encode(sa_sync_conn, _Encoder(), limit=2)

    assert [r.publication_id for r in _rows(sa_sync_conn)] == sorted(publications)[:2]
    assert metrics.extras["embeddings_pending"] == 1
