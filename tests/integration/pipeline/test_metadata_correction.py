"""Intégration : la phase metadata_correction persiste l'effective + le brut réversible."""

import json
from datetime import timedelta
from functools import partial

from sqlalchemy import text

from domain.dates import today
from infrastructure.db.queues import Queue
from pipeline.transformation.publications.correction import serial_by_doi
from pipeline.transformation.publications.correction.correct_by_cluster import compute_updates
from pipeline.transformation.publications.correction.correct_unary import compute_update
from pipeline.transformation.publications.correction.correction_store import (
    SourceRecordCorrectionStore,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.serials import (
    insert_doi_prefix,
    insert_publisher,
    insert_serial,
    insert_serial_doi_namespace,
)
from tests.integration.helpers.sources import insert_source_record

# Enregistrement source de titre « T », OpenAlex par défaut.
_typed_source_record = partial(
    insert_source_record, source="openalex", title="T", title_normalized="t"
)

# Enregistrement source de titre « Un titre », OpenAlex par défaut.
_source_record = partial(insert_source_record, source="openalex", title="Un titre")


def _seed_serial(conn, serial_type: str, namespace: str | None = None) -> int:
    serial_id = insert_serial(conn, "J", serial_type=serial_type)
    if namespace is not None:
        insert_serial_doi_namespace(conn, namespace, serial_id=serial_id, dois=10, share=1.0)
    return serial_id


def _apply(conn) -> int:
    """Joue la passe unaire sans committer (transaction de test rollbackée)."""
    rows = SourceRecordCorrectionStore(conn).fetch_for_unary_correction()
    updates = [u for r in rows if (u := compute_update(r)) is not None]
    return SourceRecordCorrectionStore(conn).persist_corrections(updates)


def _apply_serial_by_doi(conn) -> int:
    """Joue le sous-step serial_by_doi sans committer."""
    namespaces = SourceRecordCorrectionStore(conn).fetch_serial_doi_namespaces()
    rows = SourceRecordCorrectionStore(conn).fetch_serial_by_doi_candidates()
    return SourceRecordCorrectionStore(conn).persist_serial_corrections(
        serial_by_doi.compute_updates(rows, namespaces)
    )


def test_serial_by_doi_attaches_then_doc_type_converges_same_run(sa_sync_conn):
    # The Conversation : DOI dans l'espace de noms d'une revue media, sans serial_id. serial_by_doi
    # pose la revue ; l'unaire qui suit (même run) la joint et reclasse preprint → media.
    conn = sa_sync_conn
    media_serial = _seed_serial(conn, "media", namespace="10.64628/aak.")
    source_record = _source_record(
        conn, source_id="W_tc", doi="10.64628/aak.xyz", doc_type="preprint"
    )

    assert _apply_serial_by_doi(conn) == 1
    jid, raw = conn.execute(
        text("SELECT serial_id, corrections FROM source_records WHERE id = :id"),
        {"id": source_record},
    ).one()
    assert jid == media_serial
    assert raw == {"serial_id": {"raw": None, "corrected_by": "SERIAL_BY_DOI_NAMESPACE"}}

    _apply(conn)
    doc_type, raw2 = _state(conn, source_record)
    assert doc_type == "media"
    assert raw2["doc_type"] == {"raw": "preprint", "corrected_by": "SERIAL_TYPE_MEDIA_TO_MEDIA"}
    # Le sous-step unaire préserve la clé possédée par serial_by_doi.
    assert raw2["serial_id"] == {"raw": None, "corrected_by": "SERIAL_BY_DOI_NAMESPACE"}


def test_serial_by_doi_idempotent_and_self_heals(sa_sync_conn):
    conn = sa_sync_conn
    serial = _seed_serial(conn, "journal", namespace="10.5194/acp-")
    source_record = _source_record(
        conn, source_id="W_acp", doi="10.5194/acp-20-1-2020", doc_type="article"
    )

    assert _apply_serial_by_doi(conn) == 1
    assert _apply_serial_by_doi(conn) == 0  # second run : rien ne change

    # L'espace de noms disparaît → restauration NULL, stash retiré.
    conn.execute(text("DELETE FROM serial_doi_namespaces WHERE serial_id = :id"), {"id": serial})
    assert _apply_serial_by_doi(conn) == 1
    jid, raw = conn.execute(
        text("SELECT serial_id, corrections FROM source_records WHERE id = :id"),
        {"id": source_record},
    ).one()
    assert jid is None
    assert raw == {}


def _state(conn, source_record_id: int) -> tuple:
    return conn.execute(
        text("SELECT doc_type, corrections FROM source_records WHERE id = :id"),
        {"id": source_record_id},
    ).one()


def _doi(conn, source_record_id: int) -> str | None:
    return conn.execute(
        text("SELECT doi FROM source_records WHERE id = :id"), {"id": source_record_id}
    ).scalar_one()


def test_serial_media_and_theses_url_corrected_plain_untouched(sa_sync_conn):
    conn = sa_sync_conn
    media_serial = _seed_serial(conn, "media")
    media_source_record = _source_record(
        conn, source_id="W_media", doc_type="article", serial_id=media_serial
    )
    theses_source_record = _source_record(
        conn, source_id="W_theses", doc_type="article", urls=["https://theses.fr/2020ABCD"]
    )
    plain_source_record = _source_record(conn, source_id="W_plain", doc_type="article")

    n = _apply(conn)
    assert n == 2  # media + theses corrigées, plain non

    media_doc_type, media_raw = _state(conn, media_source_record)
    assert media_doc_type == "media"
    assert media_raw == {
        "doc_type": {"raw": "article", "corrected_by": "SERIAL_TYPE_MEDIA_TO_MEDIA"}
    }

    theses_doc_type, theses_raw = _state(conn, theses_source_record)
    assert theses_doc_type == "thesis"
    assert theses_raw == {"doc_type": {"raw": "article", "corrected_by": "THESES_FR_URL_TO_THESIS"}}

    plain_doc_type, plain_raw = _state(conn, plain_source_record)
    assert plain_doc_type == "article"
    assert plain_raw == {}


def test_doi_of_a_media_registrant_becomes_media(sa_sync_conn):
    """Cas réel : The Conversation dépose ses articles sous `10.64628`, sans titre de revue."""
    conn = sa_sync_conn
    publisher = insert_publisher(conn, "The Conversation Media Group", publisher_type="media")
    insert_doi_prefix(conn, "10.64628", ra="Crossref", publisher_id=publisher)
    source_record = _source_record(
        conn,
        source="crossref",
        source_id="10.64628/aak.x",
        doi="10.64628/aak.x",
        doc_type="preprint",
        raw_doc_type="posted-content",
    )

    _apply(conn)

    doc_type, raw = _state(conn, source_record)
    assert doc_type == "media"
    assert raw["doc_type"]["corrected_by"] == "DOI_REGISTRANT_MEDIA_TO_MEDIA"


def test_reversibility_invariant(sa_sync_conn):
    conn = sa_sync_conn
    media_serial = _seed_serial(conn, "media")
    _source_record(conn, source_id="W_media", doc_type="article", serial_id=media_serial)
    _apply(conn)

    # COALESCE(corrections->'doc_type'->>'raw', doc_type::text) reconstruit le brut d'origine.
    reconstructed = conn.execute(
        text(
            "SELECT COALESCE(corrections->'doc_type'->>'raw', doc_type::text) "
            "FROM source_records WHERE source_id = 'W_media'"
        )
    ).scalar_one()
    assert reconstructed == "article"


def test_idempotent_second_run_changes_nothing(sa_sync_conn):
    conn = sa_sync_conn
    media_serial = _seed_serial(conn, "media")
    _source_record(conn, source_id="W_media", doc_type="article", serial_id=media_serial)
    _source_record(
        conn, source_id="W_theses", doc_type="article", urls=["https://theses.fr/2020ABCD"]
    )

    assert _apply(conn) == 2
    assert _apply(conn) == 0  # rien à recorriger


def test_self_heals_when_serial_no_longer_media(sa_sync_conn):
    conn = sa_sync_conn
    media_serial = _seed_serial(conn, "media")
    source_record = _source_record(
        conn, source_id="W_media", doc_type="article", serial_id=media_serial
    )
    assert _apply(conn) == 1
    assert _state(conn, source_record)[0] == "media"

    # Le journal change de type : la règle ne s'applique plus, le brut doit revenir.
    conn.execute(
        text("UPDATE serials SET serial_type = 'journal' WHERE id = :id"),
        {"id": media_serial},
    )
    assert _apply(conn) == 1
    doc_type, raw = _state(conn, source_record)
    assert doc_type == "article"
    assert raw == {}


def test_thesis_with_serial_corrected_and_deconflated(sa_sync_conn):
    conn = sa_sync_conn
    jid = _seed_serial(conn, "journal")
    # DOI d'éditeur (préfixe ≠ registre de thèses) : signe la version publiée → la conflation
    # thèse↔article bascule en `article`. (Avec un DOI ABES ou sans DOI, le type resterait thèse.)
    source_record = insert_source_record(
        conn,
        source="openalex",
        source_id="W-conflation",
        title="T",
        doi="10.1016/j.ex.2020.01.001",
        doc_type="thesis",
        serial_id=jid,
        external_ids={"nnt": "2020CLFAC001", "hal_id": ["tel-01", "hal-99"]},
    )

    assert _apply(conn) == 1
    row = conn.execute(
        text("SELECT doc_type, external_ids, corrections FROM source_records WHERE id = :id"),
        {"id": source_record},
    ).one()
    assert row.doc_type == "article"  # mistype corrigé
    assert row.external_ids == {"hal_id": ["hal-99"]}  # nnt + tel- retirés, hal- gardé
    assert row.corrections["doc_type"]["corrected_by"] == "THESIS_WITH_SERIAL_TO_ARTICLE"
    assert row.corrections["external_ids"]["corrected_by"] == "THESIS_WITH_SERIAL_TO_ARTICLE"
    # Réversibilité : le brut external_ids est reconstructible.
    raw_nnt = conn.execute(
        text(
            "SELECT corrections->'external_ids'->'raw'->>'nnt' FROM source_records WHERE id = :id"
        ),
        {"id": source_record},
    ).scalar_one()
    assert raw_nnt == "2020CLFAC001"


def test_expired_embargo_promoted_to_green(sa_sync_conn):
    conn = sa_sync_conn
    # `embargo_expired` est calculé au fetch (`embargo_until <= current_date`) ; date de levée
    # passée ⇒ la règle promeut `embargoed → green`. (Règle agnostique de la source.)
    source_record = insert_source_record(
        conn,
        source="openalex",
        source_id="W-emb-past",
        title="T",
        doc_type="article",
        oa_status="embargoed",
        embargo_until=today() - timedelta(days=1),
    )
    assert _apply(conn) == 1
    row = conn.execute(
        text("SELECT oa_status::text AS oa, corrections FROM source_records WHERE id = :id"),
        {"id": source_record},
    ).one()
    assert row.oa == "green"
    assert row.corrections["oa_status"] == {
        "raw": "embargoed",
        "corrected_by": "EMBARGO_EXPIRED_TO_GREEN",
    }


def _oa_status(conn, source_record_id: int) -> str:
    return conn.execute(
        text("SELECT oa_status::text FROM source_records WHERE id = :id"), {"id": source_record_id}
    ).scalar_one()


def test_diamond_follows_the_journal(sa_sync_conn):
    conn = sa_sync_conn
    doaj_free = insert_serial(conn, "Sans frais", oa_model="full_oa", is_in_doaj=True)
    conn.execute(
        text("UPDATE serials SET doaj_payload = CAST(:p AS jsonb) WHERE id = :id"),
        {"p": json.dumps({"APC": "No", "Has other fees": "No"}), "id": doaj_free},
    )
    marked = insert_serial(conn, "Marquée", oa_model="diamond")
    paying = insert_serial(conn, "Payante", oa_model="full_oa")
    gold_in_doaj = _source_record(conn, source_id="W-d1", oa_status="gold", serial_id=doaj_free)
    gold_in_marked = _source_record(conn, source_id="W-d2", oa_status="gold", serial_id=marked)
    diamond_in_paying = _source_record(
        conn, source_id="W-d3", oa_status="diamond", serial_id=paying
    )
    diamond_without_journal = _source_record(conn, source_id="W-d4", oa_status="diamond")

    _apply(conn)

    assert _oa_status(conn, gold_in_doaj) == "diamond"
    assert _oa_status(conn, gold_in_marked) == "diamond"
    assert _oa_status(conn, diamond_in_paying) == "gold"
    assert _oa_status(conn, diamond_without_journal) == "gold"


def test_active_embargo_not_promoted(sa_sync_conn):
    conn = sa_sync_conn
    # Date de levée future ⇒ `embargo_expired` faux ⇒ pas de promotion.
    source_record = insert_source_record(
        conn,
        source="openalex",
        source_id="W-emb-future",
        title="T",
        doc_type="article",
        oa_status="embargoed",
        embargo_until=today() + timedelta(days=365),
    )
    assert _apply(conn) == 0
    oa = conn.execute(
        text("SELECT oa_status::text FROM source_records WHERE id = :id"), {"id": source_record}
    ).scalar_one()
    assert oa == "embargoed"


# ── Sous-étape cluster : ouvrage/chapitre au même DOI ──


def _apply_cluster(conn) -> int:
    rows = SourceRecordCorrectionStore(conn).fetch_doi_cluster_candidates()
    return SourceRecordCorrectionStore(conn).persist_doi_corrections(compute_updates(rows))


def test_chapter_loses_doi_of_its_book(sa_sync_conn):
    conn = sa_sync_conn
    book = _typed_source_record(
        conn,
        source_id="b1",
        doi="10.1/x",
        doc_type="book",
        title="Le livre",
        title_normalized="le livre",
    )
    chapter = _typed_source_record(conn, source_id="c1", doi="10.1/x", doc_type="book_chapter")

    assert _apply_cluster(conn) == 1  # seul le chapitre

    book_doi, _ = _state(conn, book)
    # le book garde son DOI
    assert (
        conn.execute(
            text("SELECT doi FROM source_records WHERE id = :id"), {"id": book}
        ).scalar_one()
        == "10.1/x"
    )
    chap_doi = conn.execute(
        text("SELECT doi FROM source_records WHERE id = :id"), {"id": chapter}
    ).scalar_one()
    assert chap_doi is None
    chap_raw = conn.execute(
        text("SELECT corrections FROM source_records WHERE id = :id"), {"id": chapter}
    ).scalar_one()
    assert chap_raw == {"doi": {"raw": "10.1/x", "corrected_by": "OUVRAGE_VS_CHAPITRE"}}

    # Réversibilité : le DOI brut du chapitre reste reconstructible.
    reconstructed = conn.execute(
        text("SELECT COALESCE(corrections->'doi'->>'raw', doi) FROM source_records WHERE id = :id"),
        {"id": chapter},
    ).scalar_one()
    assert reconstructed == "10.1/x"


def test_idempotent_and_self_heals_when_book_retyped(sa_sync_conn):
    conn = sa_sync_conn
    book = _typed_source_record(
        conn,
        source_id="b1",
        doi="10.1/x",
        doc_type="book",
        title="Le livre",
        title_normalized="le livre",
    )
    chapter = _typed_source_record(conn, source_id="c1", doi="10.1/x", doc_type="book_chapter")
    assert _apply_cluster(conn) == 1
    assert _apply_cluster(conn) == 0  # idempotent

    # L'ouvrage est retypé (n'est plus un book) : le chapitre récupère son DOI.
    conn.execute(
        text("UPDATE source_records SET doc_type = 'article' WHERE id = :id"), {"id": book}
    )
    assert _apply_cluster(conn) == 1
    chap_doi = conn.execute(
        text("SELECT doi, corrections FROM source_records WHERE id = :id"), {"id": chapter}
    ).one()
    assert chap_doi.doi == "10.1/x"
    assert chap_doi.corrections == {}


def test_chapters_same_title_untouched(sa_sync_conn):
    # Même chapitre (titre normalisé identique) sous un DOI : pas de conflit.
    conn = sa_sync_conn
    insert_source_record(
        conn,
        source="openalex",
        source_id="c1",
        title="T",
        title_normalized="introduction",
        doi="10.1/y",
        doc_type="book_chapter",
    )
    insert_source_record(
        conn,
        source="openalex",
        source_id="c2",
        title="T",
        title_normalized="introduction",
        doi="10.1/y",
        doc_type="book_chapter",
    )
    assert _apply_cluster(conn) == 0


def test_chapters_distinct_titles_both_lose_doi(sa_sync_conn):
    # Deux chapitres réellement distincts au même DOI (sans ouvrage) → tous deux perdent le DOI.
    conn = sa_sync_conn
    c1 = insert_source_record(
        conn,
        source="openalex",
        source_id="c1",
        title="T",
        title_normalized="geographie de l environnement",
        doi="10.1/z",
        doc_type="book_chapter",
    )
    c2 = insert_source_record(
        conn,
        source="openalex",
        source_id="c2",
        title="T",
        title_normalized="nommer et representer les processus biophysiques",
        doi="10.1/z",
        doc_type="book_chapter",
    )
    assert _apply_cluster(conn) == 2
    for source_record in (c1, c2):
        row = conn.execute(
            text("SELECT doi, corrections FROM source_records WHERE id = :id"),
            {"id": source_record},
        ).one()
        assert row.doi is None
        assert row.corrections["doi"]["corrected_by"] == "CHAPITRES_TITRES_DIFFERENTS"


def test_chapters_number_prefix_same_chapter_untouched(sa_sync_conn):
    # « chapitre 14 X » vs « X » : même chapitre après nettoyage → pas de conflit.
    conn = sa_sync_conn
    insert_source_record(
        conn,
        source="openalex",
        source_id="c1",
        title="T",
        title_normalized="chapitre 14 les limnosystemes",
        doi="10.1/w",
        doc_type="book_chapter",
    )
    insert_source_record(
        conn,
        source="openalex",
        source_id="c2",
        title="T",
        title_normalized="les limnosystemes",
        doi="10.1/w",
        doc_type="book_chapter",
    )
    assert _apply_cluster(conn) == 0


# ── Sous-étape cluster : DOI inconnu de doi.org ──


def test_un_doi_inconnu_de_doi_org_est_nulle_puis_restaure(sa_sync_conn):
    """Régression : un DOI factice (`10.1364/ao.xx.xxxxxx`) réunissait des enregistrements sources sans rapport."""
    conn = sa_sync_conn
    first = _typed_source_record(
        conn, source_id="h1", doi="10.1364/ao.xx.xxxxxx", doc_type="article"
    )
    second = _typed_source_record(
        conn, source_id="h2", doi="10.1364/ao.xx.xxxxxx", doc_type="article"
    )
    conn.execute(
        text(
            "INSERT INTO failed_lookups (source, id_type, id_value, not_found_at)"
            " VALUES ('doi_org', 'doi', '10.1364/ao.xx.xxxxxx', now())"
        )
    )

    assert _apply_cluster(conn) == 2
    raw = conn.execute(
        text("SELECT doi, corrections FROM source_records WHERE id = :id"), {"id": first}
    ).one()
    assert raw.doi is None
    assert raw.corrections == {
        "doi": {"raw": "10.1364/ao.xx.xxxxxx", "corrected_by": "UNRESOLVED_DOI_TO_NULL"}
    }

    # doi.org connaît le DOI au run suivant : les enregistrements sources le retrouvent.
    conn.execute(text("DELETE FROM failed_lookups"))
    assert _apply_cluster(conn) == 2
    dois = conn.execute(
        text("SELECT doi FROM source_records WHERE id IN (:a, :b)"),
        {"a": first, "b": second},
    ).scalars()
    assert set(dois) == {"10.1364/ao.xx.xxxxxx"}


# ── Sous-étape cluster : copies de repository et versions (IsVariantFormOf, IsVersionOf) ──


def _seed_datacite(conn, *, source_id, doi, doc_type, relations, corrections=None):
    """Enregistrement source DataCite dont les `related_identifiers` mentionnent `relations`, couples (type, DOI cible)."""
    source_extras = {"related_identifiers": [{"relation_type": t, "doi": d} for t, d in relations]}
    return _typed_source_record(
        conn,
        source="datacite",
        source_id=source_id,
        doi=doi,
        doc_type=doc_type,
        source_extras=source_extras,
        corrections=corrections,
    )


def test_la_regle_lit_le_type_de_l_enregistrement_source_qui_mentionne_la_cible(sa_sync_conn):
    """Un enregistrement source OpenAlex `article` au DOI d'un working paper DataCite ne fait pas converger le groupe.

    Régression : la cible était attachée à toutes les enregistrements sources du DOI, et le type de l'enregistrement source OpenAlex, que la revue déduite du DOI fait changer d'un run à l'autre, décidait pour le groupe.
    """
    conn = sa_sync_conn
    wp = _seed_datacite(
        conn,
        source_id="wp",
        doi="10.18154/rwth-1",
        doc_type="preprint",
        relations=[("IsVariantFormOf", "10.48550/arxiv.1")],
    )
    oa = _typed_source_record(conn, source_id="oa", doi="10.18154/rwth-1", doc_type="article")
    assert _apply_cluster(conn) == 0
    assert (_doi(conn, wp), _doi(conn, oa)) == ("10.18154/rwth-1", "10.18154/rwth-1")


def test_un_groupe_substitue_a_tort_retrouve_ses_doi(sa_sync_conn):
    conn = sa_sync_conn
    stash = {"doi": {"raw": "10.18154/rwth-1", "corrected_by": "DATACITE_VARIANT_TO_PRIMARY"}}
    wp = _seed_datacite(
        conn,
        source_id="wp",
        doi="10.48550/arxiv.1",
        doc_type="preprint",
        relations=[("IsVariantFormOf", "10.48550/arxiv.1")],
        corrections=stash,
    )
    oa = _typed_source_record(conn, source_id="oa", doi="10.48550/arxiv.1", doc_type="article")
    conn.execute(
        text("UPDATE source_records SET corrections = CAST(:raw AS jsonb) WHERE id = :id"),
        {"raw": json.dumps(stash), "id": oa},
    )
    assert _apply_cluster(conn) == 2
    assert _apply_cluster(conn) == 0
    assert (_doi(conn, wp), _doi(conn, oa)) == ("10.18154/rwth-1", "10.18154/rwth-1")


def test_une_copie_de_l_article_fait_converger_ses_voisines(sa_sync_conn):
    conn = sa_sync_conn
    copie = _seed_datacite(
        conn,
        source_id="copie",
        doi="10.3204/pubdb-1",
        doc_type="article",
        relations=[("IsVariantFormOf", "10.1007/article")],
    )
    oa = _typed_source_record(conn, source_id="oa", doi="10.3204/pubdb-1", doc_type="article")
    assert _apply_cluster(conn) == 2
    assert (_doi(conn, copie), _doi(conn, oa)) == ("10.1007/article", "10.1007/article")


def test_une_cible_inconnue_de_doi_org_ne_remplace_pas_le_doi(sa_sync_conn):
    """Régression : une copie de repository prenait le DOI de l'article qu'elle déclare, que doi.org ne connaît pas, et le reprenait à chaque passage."""
    conn = sa_sync_conn
    stash = {"doi": {"raw": "10.15120/gsi-1", "corrected_by": "DATACITE_VARIANT_TO_PRIMARY"}}
    copie = _seed_datacite(
        conn,
        source_id="copie",
        doi="10.1103/inconnu",
        doc_type="article",
        relations=[("IsVariantFormOf", "10.1103/inconnu")],
        corrections=stash,
    )
    conn.execute(
        text(
            "INSERT INTO failed_lookups (source, id_type, id_value, not_found_at)"
            " VALUES ('doi_org', 'doi', '10.1103/inconnu', now())"
        )
    )
    assert _apply_cluster(conn) == 1
    assert _doi(conn, copie) == "10.15120/gsi-1"


def test_la_version_prime_sur_la_variante(sa_sync_conn):
    """Un enregistrement source qui mentionne un concept et une variante converge sur le concept."""
    conn = sa_sync_conn
    version = _seed_datacite(
        conn,
        source_id="v",
        doi="10.5281/zenodo.20",
        doc_type="software",
        relations=[("IsVariantFormOf", "10.5281/zenodo.1"), ("IsVersionOf", "10.5281/zenodo.9")],
    )
    assert _apply_cluster(conn) == 1
    assert _doi(conn, version) == "10.5281/zenodo.9"


# ── Sous-étape cluster : pièce d'un dataset → dataset parent (IsPartOf) ──


def _seed_datacite_piece(conn, *, source_id, doi, parent_doi, doc_type="dataset", title="Piece"):
    """enregistrement source DataCite déclarant une relation `IsPartOf` vers `parent_doi` dans son `source_extras`."""
    return insert_source_record(
        conn,
        source="datacite",
        source_id=source_id,
        title=title,
        title_normalized="piece",
        doi=doi,
        doc_type=doc_type,
        source_extras={"related_identifiers": [{"relation_type": "IsPartOf", "doi": parent_doi}]},
    )


def test_dataset_piece_converges_to_present_dataset_parent(sa_sync_conn):
    # Le parent dataset est moissonné ; la pièce (DOI frère, non suffixé) et son doublon
    # cross-source basculent tous deux sur le DOI parent.
    conn = sa_sync_conn
    parent = _typed_source_record(conn, source_id="d-parent", doi="10.9001/set", doc_type="dataset")
    piece = _seed_datacite_piece(
        conn, source_id="d-piece", doi="10.9002/file1", parent_doi="10.9001/set"
    )
    # Doublon OpenAlex de la pièce : même DOI, sans la relation ; il doit converger aussi.
    sibling = _typed_source_record(
        conn, source_id="oa-piece", doi="10.9002/file1", doc_type="dataset"
    )

    assert _apply_cluster(conn) == 2  # la pièce DataCite + son doublon OpenAlex

    assert _doi(conn, parent) == "10.9001/set"  # le parent garde son DOI
    for source_record in (piece, sibling):
        row = conn.execute(
            text("SELECT doi, corrections FROM source_records WHERE id = :id"),
            {"id": source_record},
        ).one()
        assert row.doi == "10.9001/set"
        assert row.corrections["doi"] == {
            "raw": "10.9002/file1",
            "corrected_by": "DATACITE_PACKAGE_PIECE",
        }


def test_une_correction_de_doi_regroupe_les_contributions_sources_de_la_publication(sa_sync_conn):
    """La pièce converge sur le DOI du dépôt qui partage sa publication : le groupement l'écarte."""
    conn = sa_sync_conn
    publication = insert_publication(conn)
    other = insert_publication(conn)
    insert_source_record(
        conn,
        publication,
        source="datacite",
        source_id="d-parent",
        title="Set",
        doi="10.9001/set",
        doc_type="dataset",
    )
    insert_source_record(
        conn,
        publication,
        source="datacite",
        source_id="d-piece",
        title="Piece",
        title_normalized="piece",
        doi="10.9002/file1",
        doc_type="dataset",
        source_extras={
            "related_identifiers": [{"relation_type": "IsPartOf", "doi": "10.9001/set"}]
        },
    )
    insert_source_record(conn, other, source="openalex", source_id="W-other", title="Other")
    clear(conn, Queue.PUBLICATION_CONTRIBUTIONS)

    assert _apply_cluster(conn) == 1

    marked = queued(conn, Queue.PUBLICATION_CONTRIBUTIONS)
    assert publication in marked
    assert other not in marked


def test_dataset_piece_not_merged_when_parent_is_article(sa_sync_conn):
    # Parent moissonné mais typé `article` (dataset supplémentaire d'un article) : pas de fusion.
    conn = sa_sync_conn
    _typed_source_record(conn, source_id="art", doi="10.9004/paper", doc_type="article")
    piece = _seed_datacite_piece(
        conn, source_id="d-piece", doi="10.9002/data", parent_doi="10.9004/paper"
    )
    assert _apply_cluster(conn) == 0
    assert _doi(conn, piece) == "10.9002/data"


def test_dataset_piece_not_merged_when_parent_absent(sa_sync_conn):
    # Parent non moissonné : rien à absorber, la pièce attend un run ultérieur.
    conn = sa_sync_conn
    piece = _seed_datacite_piece(
        conn, source_id="d-piece", doi="10.9002/data", parent_doi="10.9003/set"
    )
    assert _apply_cluster(conn) == 0
    assert _doi(conn, piece) == "10.9002/data"


# ── Sous-étape cluster : fichier complémentaire figshare → collection de l'article ──


def _seed_figshare(
    conn, *, source_id, doi, title_normalized, source="datacite", year=2023, doc_type="dataset"
):
    """Enregistrement source figshare, sans relation déclarée."""
    return insert_source_record(
        conn,
        source=source,
        source_id=source_id,
        title=title_normalized,
        title_normalized=title_normalized,
        doi=doi,
        doc_type=doc_type,
        publication_year=year,
    )


_ARTICLE = "effects of sevoflurane on lung epithelial permeability"


def test_figshare_additional_file_converges_to_collection_of_same_title(sa_sync_conn):
    conn = sa_sync_conn
    collection = _seed_figshare(
        conn, source_id="c", doi="10.6084/m9.figshare.c.6702115", title_normalized=_ARTICLE
    )
    piece = _seed_figshare(
        conn,
        source_id="f1",
        doi="10.6084/m9.figshare.23538907",
        title_normalized=f"additional file 1 of {_ARTICLE}",
    )
    # Doublon OpenAlex de la pièce : il suit la décision du groupe.
    sibling = _seed_figshare(
        conn,
        source="openalex",
        source_id="W-f1",
        doi="10.6084/m9.figshare.23538907",
        title_normalized=f"additional file 1 of {_ARTICLE}",
    )

    assert _apply_cluster(conn) == 2

    assert _doi(conn, collection) == "10.6084/m9.figshare.c.6702115"
    for source_record in (piece, sibling):
        row = conn.execute(
            text("SELECT doi, corrections FROM source_records WHERE id = :id"),
            {"id": source_record},
        ).one()
        assert row.doi == "10.6084/m9.figshare.c.6702115"
        assert row.corrections["doi"] == {
            "raw": "10.6084/m9.figshare.23538907",
            "corrected_by": "DATACITE_PACKAGE_PIECE",
        }


def test_figshare_additional_file_converges_whatever_its_source_and_type(sa_sync_conn):
    """Une pièce que seul OpenAlex donne, et une pièce que DataCite type `media`, rejoignent la collection."""
    conn = sa_sync_conn
    _seed_figshare(
        conn, source_id="c", doi="10.6084/m9.figshare.c.6702115", title_normalized=_ARTICLE
    )
    openalex_only = _seed_figshare(
        conn,
        source="openalex",
        source_id="W-f1",
        doi="10.6084/m9.figshare.23538907",
        title_normalized=f"additional file 1 of {_ARTICLE}",
    )
    media = _seed_figshare(
        conn,
        source_id="f2",
        doi="10.6084/m9.figshare.23538910",
        title_normalized=f"additional file 2 of {_ARTICLE}",
        doc_type="media",
    )

    assert _apply_cluster(conn) == 2
    for source_record in (openalex_only, media):
        assert _doi(conn, source_record) == "10.6084/m9.figshare.c.6702115"


def test_figshare_additional_file_stays_without_collection(sa_sync_conn):
    conn = sa_sync_conn
    piece = _seed_figshare(
        conn,
        source_id="f1",
        doi="10.6084/m9.figshare.23538907",
        title_normalized=f"additional file 1 of {_ARTICLE}",
    )
    assert _apply_cluster(conn) == 0
    assert _doi(conn, piece) == "10.6084/m9.figshare.23538907"


def test_figshare_additional_file_stays_when_two_collections_share_the_title(sa_sync_conn):
    conn = sa_sync_conn
    for source_id, doi in (("c1", "10.6084/m9.figshare.c.1"), ("c2", "10.6084/m9.figshare.c.2")):
        _seed_figshare(conn, source_id=source_id, doi=doi, title_normalized=_ARTICLE)
    piece = _seed_figshare(
        conn,
        source_id="f1",
        doi="10.6084/m9.figshare.23538907",
        title_normalized=f"additional file 1 of {_ARTICLE}",
    )
    assert _apply_cluster(conn) == 0
    assert _doi(conn, piece) == "10.6084/m9.figshare.23538907"


def test_figshare_additional_file_stays_when_collection_year_differs(sa_sync_conn):
    conn = sa_sync_conn
    _seed_figshare(
        conn,
        source_id="c",
        doi="10.6084/m9.figshare.c.6702115",
        title_normalized=_ARTICLE,
        year=2021,
    )
    piece = _seed_figshare(
        conn,
        source_id="f1",
        doi="10.6084/m9.figshare.23538907",
        title_normalized=f"additional file 1 of {_ARTICLE}",
    )
    assert _apply_cluster(conn) == 0
    assert _doi(conn, piece) == "10.6084/m9.figshare.23538907"


def test_dataset_piece_idempotent_and_self_heals_when_parent_retyped(sa_sync_conn):
    conn = sa_sync_conn
    parent = _typed_source_record(conn, source_id="d-parent", doi="10.9001/set", doc_type="dataset")
    piece = _seed_datacite_piece(
        conn, source_id="d-piece", doi="10.9002/file1", parent_doi="10.9001/set"
    )
    assert _apply_cluster(conn) == 1
    assert _apply_cluster(conn) == 0  # idempotent

    # Le parent n'est plus un dataset : la pièce récupère son DOI d'origine.
    conn.execute(
        text("UPDATE source_records SET doc_type = 'article' WHERE id = :id"), {"id": parent}
    )
    assert _apply_cluster(conn) == 1
    row = conn.execute(
        text("SELECT doi, corrections FROM source_records WHERE id = :id"), {"id": piece}
    ).one()
    assert row.doi == "10.9002/file1"
    assert row.corrections == {}
