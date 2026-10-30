"""Phase `metadata_correction` : la valeur corrigée est écrite en place, la valeur d'origine est gardée dans `corrections`."""

import logging
from datetime import timedelta
from functools import partial

from sqlalchemy import text

from domain.dates import today
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from infrastructure.db.queues import Queue
from infrastructure.db.source_record_identifiers import source_record_doi_sql
from pipeline.transformation.publications.correction import serial_by_doi
from pipeline.transformation.publications.correction.correct_unary import compute_update
from pipeline.transformation.publications.correction.correction_store import (
    SourceRecordCorrectionStore,
)
from pipeline.transformation.publications.correction.doi_targets import (
    compute_doi_targets,
    run as run_doi_targets,
)
from pipeline.transformation.publications.correction.remove_identifiers import compute_updates
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
    """Joue la correction unaire sans valider la transaction."""
    rows = SourceRecordCorrectionStore(conn).fetch_for_unary_correction()
    updates = [u for r in rows if (u := compute_update(r)) is not None]
    return SourceRecordCorrectionStore(conn).persist_corrections(updates)


def _apply_serial_by_doi(conn) -> int:
    """Joue la sous-étape `serial_by_doi` sans valider la transaction."""
    namespaces = SourceRecordCorrectionStore(conn).fetch_serial_doi_namespaces()
    rows = SourceRecordCorrectionStore(conn).fetch_serial_by_doi_candidates()
    return SourceRecordCorrectionStore(conn).persist_serial_corrections(
        serial_by_doi.compute_updates(rows, namespaces)
    )


def test_serial_by_doi_attaches_then_doc_type_converges_same_run(sa_sync_conn):
    # The Conversation : DOI dans l'espace de noms d'une revue media, sans revue. `serial_by_doi` pose la revue ; la correction unaire qui suit, dans le même run, retype le preprint en `media`.
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
    # La correction unaire garde la clé `serial_id` écrite par `serial_by_doi`.
    assert raw2["serial_id"] == {"raw": None, "corrected_by": "SERIAL_BY_DOI_NAMESPACE"}


def test_serial_by_doi_ignores_a_removed_doi(sa_sync_conn):
    """Un DOI retiré par la correction est faux : il ne désigne aucune revue."""
    conn = sa_sync_conn
    _seed_serial(conn, "journal", namespace="10.5194/acp-")
    _source_record(
        conn,
        source_id="W_removed",
        doc_type="article",
        identifiers=[
            SourceIdentifier(
                SourceIdentifierType.DOI,
                "10.5194/acp-20-1-2020",
                SourceIdentifierRole.SECONDARY,
                "UNRESOLVED_DOI_TO_NULL",
            )
        ],
    )

    assert _apply_serial_by_doi(conn) == 0


def test_serial_by_doi_idempotent_and_self_heals(sa_sync_conn):
    conn = sa_sync_conn
    serial = _seed_serial(conn, "journal", namespace="10.5194/acp-")
    source_record = _source_record(
        conn, source_id="W_acp", doi="10.5194/acp-20-1-2020", doc_type="article"
    )

    assert _apply_serial_by_doi(conn) == 1
    assert _apply_serial_by_doi(conn) == 0  # second passage : rien ne change

    # L'espace de noms disparaît : la revue revient à NULL et sa clé quitte `corrections`.
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
        text(f"SELECT {source_record_doi_sql('sr')} FROM source_records sr WHERE sr.id = :id"),
        {"id": source_record_id},
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
    assert n == 2  # seuls les enregistrements media et theses.fr sont corrigés

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


def test_registrant_rule_reads_the_active_own_dois(sa_sync_conn):
    """Le DOI de presse actif d'un work OpenAlex décide du type ; un DOI de presse retiré par la correction est ignoré."""
    conn = sa_sync_conn
    publisher = insert_publisher(conn, "The Conversation Media Group", publisher_type="media")
    insert_doi_prefix(conn, "10.64628", ra="Crossref", publisher_id=publisher)
    secondary = SourceIdentifierRole.SECONDARY
    kept = _source_record(
        conn,
        source_id="W1",
        doc_type="article",
        identifiers=[SourceIdentifier(SourceIdentifierType.DOI, "10.64628/aak.x", secondary)],
    )
    removed = _source_record(
        conn,
        source_id="W2",
        doc_type="article",
        identifiers=[
            SourceIdentifier(
                SourceIdentifierType.DOI, "10.64628/aak.y", secondary, "UNRESOLVED_DOI_TO_NULL"
            )
        ],
    )

    _apply(conn)

    assert _state(conn, kept)[0] == "media"
    assert _state(conn, removed)[0] == "article"


def test_reversibility_invariant(sa_sync_conn):
    conn = sa_sync_conn
    media_serial = _seed_serial(conn, "media")
    _source_record(conn, source_id="W_media", doc_type="article", serial_id=media_serial)
    _apply(conn)

    # Le type d'origine se reconstruit depuis `corrections`.
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
    assert _apply(conn) == 0  # rien à corriger


def test_self_heals_when_serial_no_longer_media(sa_sync_conn):
    conn = sa_sync_conn
    media_serial = _seed_serial(conn, "media")
    source_record = _source_record(
        conn, source_id="W_media", doc_type="article", serial_id=media_serial
    )
    assert _apply(conn) == 1
    assert _state(conn, source_record)[0] == "media"

    # La revue change de type : la règle cesse de s'appliquer et le type d'origine revient.
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
    # Thèse dans une revue, avec un DOI d'éditeur (préfixe autre que celui des thèses) : c'est la version publiée, retypée en `article`. Avec un DOI de l'ABES ou sans DOI, le type resterait thèse.
    secondary = SourceIdentifierRole.SECONDARY
    source_record = insert_source_record(
        conn,
        source="openalex",
        source_id="W-conflation",
        title="T",
        doi="10.1016/j.ex.2020.01.001",
        doc_type="thesis",
        serial_id=jid,
        identifiers=[
            SourceIdentifier(SourceIdentifierType.NNT, "2020CLFAC001", secondary),
            SourceIdentifier(SourceIdentifierType.HAL_ID, "tel-01", secondary),
            SourceIdentifier(SourceIdentifierType.HAL_ID, "hal-99", secondary),
        ],
    )

    assert _apply(conn) == 1
    row = conn.execute(
        text("SELECT doc_type, corrections FROM source_records WHERE id = :id"),
        {"id": source_record},
    ).one()
    assert row.doc_type == "article"  # type corrigé
    assert row.corrections["doc_type"]["corrected_by"] == "THESIS_WITH_SERIAL_TO_ARTICLE"
    # Réversibilité : les identifiants retirés restent dans la table, avec leur règle.
    removed = conn.execute(
        text("""
            SELECT id_value, removed_by FROM source_record_identifiers
            WHERE source_record_id = :id AND id_type <> 'doi' ORDER BY id_value
        """),
        {"id": source_record},
    ).all()
    assert removed == [
        ("2020CLFAC001", "THESIS_WITH_SERIAL_TO_ARTICLE"),
        ("hal-99", None),
        ("tel-01", "THESIS_WITH_SERIAL_TO_ARTICLE"),
    ]


def _embargoed_copy(conn, source_record_id: int, embargo_until) -> None:
    conn.execute(
        text(
            "INSERT INTO source_record_locations (source_record_id, url, is_oa, embargo_until)"
            " VALUES (:id, 'https://hal.science/hal-1', true, :until)"
        ),
        {"id": source_record_id, "until": embargo_until},
    )


def test_expired_embargo_promoted_to_green(sa_sync_conn):
    conn = sa_sync_conn
    # `embargo_expired` est calculé à la lecture, sur les copies. Date de levée passée : la règle, commune à toutes les sources, passe `embargoed` à `green`.
    source_record = insert_source_record(
        conn,
        source="openalex",
        source_id="W-emb-past",
        title="T",
        doc_type="article",
        oa_status="embargoed",
    )
    _embargoed_copy(conn, source_record, today() - timedelta(days=1))
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
    diamond = insert_serial(conn, "Diamant", oa_model="diamond")
    paying = insert_serial(conn, "Payante", oa_model="full_oa")
    gold_in_diamond = _source_record(conn, source_id="W-d2", oa_status="gold", serial_id=diamond)
    diamond_in_paying = _source_record(
        conn, source_id="W-d3", oa_status="diamond", serial_id=paying
    )
    diamond_without_journal = _source_record(conn, source_id="W-d4", oa_status="diamond")

    _apply(conn)

    assert _oa_status(conn, gold_in_diamond) == "diamond"
    assert _oa_status(conn, diamond_in_paying) == "gold"
    assert _oa_status(conn, diamond_without_journal) == "gold"


def test_active_embargo_not_promoted(sa_sync_conn):
    conn = sa_sync_conn
    # Date de levée future : `embargo_expired` est faux, le statut reste `embargoed`.
    source_record = insert_source_record(
        conn,
        source="openalex",
        source_id="W-emb-future",
        title="T",
        doc_type="article",
        oa_status="embargoed",
    )
    _embargoed_copy(conn, source_record, today() + timedelta(days=365))
    assert _apply(conn) == 0
    oa = conn.execute(
        text("SELECT oa_status::text FROM source_records WHERE id = :id"), {"id": source_record}
    ).scalar_one()
    assert oa == "embargoed"


# ── Sous-étape cluster : ouvrage/chapitre au même DOI ──


def _apply_cluster(conn) -> int:
    """Joue les sous-étapes `doi_targets` puis `remove_identifiers`. Renvoie le nombre d'enregistrements sources corrigés."""
    store = SourceRecordCorrectionStore(conn)
    run_doi_targets(conn, store, logging.getLogger("test"))
    return store.persist_doi_corrections(compute_updates(store.fetch_doi_cluster_candidates()))


def _doi_statuses(conn, source_record: int) -> dict[str, str | None]:
    """Renvoie la règle qui retire chaque DOI de l'enregistrement source, `None` pour un DOI actif."""
    return dict(
        conn.execute(
            text("""
                SELECT id_value, removed_by FROM source_record_identifiers
                WHERE source_record_id = :id AND id_type = 'doi'
            """),
            {"id": source_record},
        ).all()
    )


def _targets(conn) -> dict[str, str]:
    """Renvoie la cible de chaque DOI de `doi_targets`."""
    return dict(conn.execute(text("SELECT doi, target_doi FROM doi_targets")).all())


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

    assert _doi_statuses(conn, book) == {"10.1/x": None}
    assert _doi_statuses(conn, chapter) == {"10.1/x": "OUVRAGE_VS_CHAPITRE"}


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

    # L'ouvrage est retypé en article : le chapitre retrouve son DOI.
    conn.execute(
        text("UPDATE source_records SET doc_type = 'article' WHERE id = :id"), {"id": book}
    )
    assert _apply_cluster(conn) == 1
    assert _doi_statuses(conn, chapter) == {"10.1/x": None}


def test_chapters_same_title_untouched(sa_sync_conn):
    # Deux enregistrements du même chapitre (même titre normalisé) au même DOI : aucune correction.
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
    # Deux chapitres distincts au même DOI, sans ouvrage : tous deux perdent le DOI.
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
        assert _doi_statuses(conn, source_record) == {"10.1/z": "CHAPITRES_TITRES_DIFFERENTS"}


def test_chapters_number_prefix_same_chapter_untouched(sa_sync_conn):
    # « chapitre 14 X » et « X » désignent le même chapitre, numéro retiré : aucune correction.
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
    """Un DOI inconnu de doi.org, comme le DOI factice `10.1364/ao.xx.xxxxxx`, est retiré de ses enregistrements sources, puis restauré quand doi.org le connaît."""
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
    assert _doi_statuses(conn, first) == {"10.1364/ao.xx.xxxxxx": "UNRESOLVED_DOI_TO_NULL"}

    # doi.org connaît le DOI au run suivant : les enregistrements sources le retrouvent.
    conn.execute(text("DELETE FROM failed_lookups"))
    assert _apply_cluster(conn) == 2
    for source_record in (first, second):
        assert _doi_statuses(conn, source_record) == {"10.1364/ao.xx.xxxxxx": None}


# ── Sous-étape cluster : copies de repository et versions (IsVariantFormOf, IsVersionOf) ──


def _seed_datacite(conn, *, source_id, doi, doc_type, relations, corrections=None):
    """Insère un enregistrement source DataCite dont les `related_identifiers` mentionnent `relations`, couples (type, DOI cible)."""
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


def _seed_work(conn, *, source_id, doi):
    """Insère un enregistrement source Crossref d'une œuvre principale, avec son DOI dans `source_record_identifiers`."""
    return _typed_source_record(
        conn,
        source="crossref",
        source_id=source_id,
        doi=doi,
        doc_type="article",
        identifiers=[SourceIdentifier(SourceIdentifierType.DOI, doi, SourceIdentifierRole.PRIMARY)],
    )


def test_la_regle_lit_le_type_de_l_enregistrement_source_qui_mentionne_la_cible(sa_sync_conn):
    """Un enregistrement source OpenAlex `article` au DOI d'un working paper DataCite laisse ce DOI sans cible."""
    conn = sa_sync_conn
    _seed_work(conn, source_id="arxiv", doi="10.48550/arxiv.1")
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
    assert _targets(conn) == {}


def test_le_doi_d_une_copie_de_l_article_a_pour_cible_l_article(sa_sync_conn):
    conn = sa_sync_conn
    _seed_work(conn, source_id="article", doi="10.1007/article")
    copie = _seed_datacite(
        conn,
        source_id="copie",
        doi="10.3204/pubdb-1",
        doc_type="article",
        relations=[("IsVariantFormOf", "10.1007/article")],
    )
    oa = _typed_source_record(conn, source_id="oa", doi="10.3204/pubdb-1", doc_type="article")
    assert _apply_cluster(conn) == 0
    assert (_doi(conn, copie), _doi(conn, oa)) == ("10.3204/pubdb-1", "10.3204/pubdb-1")
    assert _targets(conn) == {"10.3204/pubdb-1": "10.1007/article"}


def test_le_doi_d_une_copie_de_l_article_absent_de_la_base_n_a_pas_de_cible(sa_sync_conn):
    conn = sa_sync_conn
    _seed_datacite(
        conn,
        source_id="copie",
        doi="10.3204/pubdb-1",
        doc_type="article",
        relations=[("IsVariantFormOf", "10.1007/article")],
    )
    _apply_cluster(conn)
    assert _targets(conn) == {}


def test_une_cible_inconnue_de_doi_org_n_est_pas_une_cible(sa_sync_conn):
    """L'article déclaré par une copie de repository, inconnu de doi.org, reste hors des cibles."""
    conn = sa_sync_conn
    _seed_work(conn, source_id="article", doi="10.1103/inconnu")
    _seed_datacite(
        conn,
        source_id="copie",
        doi="10.15120/gsi-1",
        doc_type="article",
        relations=[("IsVariantFormOf", "10.1103/inconnu")],
    )
    conn.execute(
        text(
            "INSERT INTO failed_lookups (source, id_type, id_value, not_found_at)"
            " VALUES ('doi_org', 'doi', '10.1103/inconnu', now())"
        )
    )
    _apply_cluster(conn)
    assert "10.15120/gsi-1" not in _targets(conn)


def test_un_doi_inconnu_de_doi_org_n_a_pas_de_cible(sa_sync_conn):
    conn = sa_sync_conn
    _seed_work(conn, source_id="concept", doi="10.5281/zenodo.9")
    _seed_datacite(
        conn,
        source_id="v",
        doi="10.5281/zenodo.20",
        doc_type="software",
        relations=[("IsVersionOf", "10.5281/zenodo.9")],
    )
    conn.execute(
        text(
            "INSERT INTO failed_lookups (source, id_type, id_value, not_found_at)"
            " VALUES ('doi_org', 'doi', '10.5281/zenodo.20', now())"
        )
    )
    _apply_cluster(conn)
    assert _targets(conn) == {}


def test_la_version_prime_sur_la_variante(sa_sync_conn):
    """Un enregistrement source qui mentionne un concept et une variante : son DOI a pour cible le concept."""
    conn = sa_sync_conn
    _seed_work(conn, source_id="variante", doi="10.5281/zenodo.1")
    _seed_work(conn, source_id="concept", doi="10.5281/zenodo.9")
    _seed_datacite(
        conn,
        source_id="v",
        doi="10.5281/zenodo.20",
        doc_type="software",
        relations=[("IsVariantFormOf", "10.5281/zenodo.1"), ("IsVersionOf", "10.5281/zenodo.9")],
    )
    _apply_cluster(conn)
    assert conn.execute(text("SELECT doi, target_doi, rule FROM doi_targets")).all() == [
        ("10.5281/zenodo.20", "10.5281/zenodo.9", "DATACITE_VERSION_TO_CONCEPT")
    ]


def test_les_versions_d_un_preprint_ont_pour_cible_la_plus_recente(sa_sync_conn):
    """Chaque version d'un preprint Research Square a pour cible la version la plus récente."""
    conn = sa_sync_conn
    _typed_source_record(conn, source_id="W1", doi="10.21203/rs.3.rs-1/v1")
    _typed_source_record(conn, source_id="W2", doi="10.21203/rs.3.rs-1/v2")

    _apply_cluster(conn)

    assert _targets(conn) == {"10.21203/rs.3.rs-1/v1": "10.21203/rs.3.rs-1/v2"}


def test_les_versions_ont_pour_cible_le_doi_concept_moissonne(sa_sync_conn):
    conn = sa_sync_conn
    _seed_work(conn, source_id="concept", doi="10.6084/m9.figshare.1")
    _typed_source_record(conn, source_id="W1", doi="10.6084/m9.figshare.1.v1")

    _apply_cluster(conn)

    assert _targets(conn) == {"10.6084/m9.figshare.1.v1": "10.6084/m9.figshare.1"}


def test_les_versions_ont_pour_cible_le_doi_concept_derive_d_openalex(sa_sync_conn):
    """Le DOI de la v1 a pour cible le DOI concept Figshare, présent seulement comme DOI `derived` d'un work OpenAlex."""
    conn = sa_sync_conn
    _typed_source_record(
        conn,
        source_id="W1",
        identifiers=[
            SourceIdentifier(
                SourceIdentifierType.DOI, "10.6084/m9.figshare.c.1", SourceIdentifierRole.DERIVED
            )
        ],
    )
    _seed_work(conn, source_id="v1", doi="10.6084/m9.figshare.c.1.v1")

    _apply_cluster(conn)

    assert _targets(conn) == {"10.6084/m9.figshare.c.1.v1": "10.6084/m9.figshare.c.1"}


def test_la_version_datacite_reste_en_jeu_tant_que_sa_cible_est_sans_enregistrement_source(
    sa_sync_conn,
):
    """Un dépôt Figshare en v1 a pour cible son DOI concept. Il est écarté de la réconciliation seulement quand le concept est le DOI `primary` d'un autre enregistrement source."""
    conn = sa_sync_conn
    version = _seed_work(conn, source_id="v1", doi="10.6084/m9.figshare.1.v1")
    conn.execute(
        text("UPDATE source_records SET source = 'datacite' WHERE id = :id"), {"id": version}
    )
    conn.execute(
        text(
            "INSERT INTO doi_targets (doi, target_doi, rule)"
            " VALUES ('10.6084/m9.figshare.1.v1', '10.6084/m9.figshare.1', 'DOI_VERSION_TO_UNVERSIONED')"
        )
    )

    def target_recorded() -> bool:
        rows = SourceRecordCorrectionStore(conn).fetch_matchability_rows()
        return next(r for r in rows if r.id == version).facts.primary_doi_target_recorded

    assert not target_recorded()
    _seed_work(conn, source_id="concept", doi="10.6084/m9.figshare.1")
    assert target_recorded()


def test_un_changement_de_cible_marque_les_enregistrements_sources_du_doi(sa_sync_conn):
    conn = sa_sync_conn
    _seed_work(conn, source_id="concept", doi="10.5281/zenodo.9")
    version = _seed_datacite(
        conn,
        source_id="v",
        doi="10.5281/zenodo.20",
        doc_type="software",
        relations=[("IsVersionOf", "10.5281/zenodo.9")],
    )
    hal = _typed_source_record(conn, source_id="hal-1", doi="10.5281/zenodo.20")
    clear(conn, Queue.SOURCE_RECORD_KEYS)

    _apply_cluster(conn)
    assert {version, hal} <= queued(conn, Queue.SOURCE_RECORD_KEYS)

    clear(conn, Queue.SOURCE_RECORD_KEYS)
    _apply_cluster(conn)
    assert queued(conn, Queue.SOURCE_RECORD_KEYS) == set()


def test_le_concept_present_comme_doi_lie_ne_compte_pas(sa_sync_conn):
    """Un concept présent seulement comme identifiant lié de la version compte comme absent de la base : le DOI de la version reste sans cible."""
    conn = sa_sync_conn
    version = _seed_datacite(
        conn,
        source_id="v",
        doi="10.5281/zenodo.20",
        doc_type="software",
        relations=[("IsVersionOf", "10.5281/zenodo.9")],
    )
    conn.execute(
        text(
            "INSERT INTO source_record_identifiers (source_record_id, id_type, id_value, role)"
            " VALUES (:id, 'doi', '10.5281/zenodo.9', 'related')"
        ),
        {"id": version},
    )
    _apply_cluster(conn)
    assert _targets(conn) == {}


# ── Sous-étape cluster : pièce d'un dataset → dataset parent (IsPartOf) ──


def _seed_datacite_piece(conn, *, source_id, doi, parent_doi, doc_type="dataset", title="Piece"):
    """Insère un enregistrement source DataCite déclarant une relation `IsPartOf` vers `parent_doi` dans son `source_extras`."""
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


def test_dataset_piece_doi_targets_the_present_dataset_parent(sa_sync_conn):
    # Le dataset parent est moissonné. La pièce, de DOI sans lien de forme avec celui du parent, et son doublon d'une autre source gardent leur DOI, qui a pour cible celui du parent.
    conn = sa_sync_conn
    _typed_source_record(conn, source_id="d-parent", doi="10.9001/set", doc_type="dataset")
    piece = _seed_datacite_piece(
        conn, source_id="d-piece", doi="10.9002/file1", parent_doi="10.9001/set"
    )
    sibling = _typed_source_record(
        conn, source_id="oa-piece", doi="10.9002/file1", doc_type="dataset"
    )

    assert _apply_cluster(conn) == 0
    assert (_doi(conn, piece), _doi(conn, sibling)) == ("10.9002/file1", "10.9002/file1")
    assert _targets(conn) == {"10.9002/file1": "10.9001/set"}


def test_dataset_piece_without_target_when_parent_is_article(sa_sync_conn):
    # Parent moissonné mais typé `article` (dataset complémentaire d'un article) : pas de cible.
    conn = sa_sync_conn
    _typed_source_record(conn, source_id="art", doi="10.9004/paper", doc_type="article")
    _seed_datacite_piece(conn, source_id="d-piece", doi="10.9002/data", parent_doi="10.9004/paper")
    _apply_cluster(conn)
    assert _targets(conn) == {}


def test_dataset_piece_without_target_when_parent_absent(sa_sync_conn):
    # Parent non moissonné : la pièce reste sans cible jusqu'à un run ultérieur.
    conn = sa_sync_conn
    _seed_datacite_piece(conn, source_id="d-piece", doi="10.9002/data", parent_doi="10.9003/set")
    _apply_cluster(conn)
    assert _targets(conn) == {}


# ── Sous-étape cluster : fichier complémentaire figshare → collection de l'article ──


def _seed_figshare(
    conn, *, source_id, doi, title_normalized, source="datacite", year=2023, doc_type="dataset"
):
    """Insère un enregistrement source figshare, sans relation déclarée."""
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


def test_figshare_additional_file_targets_the_collection_of_same_title(sa_sync_conn):
    conn = sa_sync_conn
    _seed_figshare(
        conn, source_id="c", doi="10.6084/m9.figshare.c.6702115", title_normalized=_ARTICLE
    )
    piece = _seed_figshare(
        conn,
        source_id="f1",
        doi="10.6084/m9.figshare.23538907",
        title_normalized=f"additional file 1 of {_ARTICLE}",
    )
    # Doublon OpenAlex de la pièce, au même DOI.
    sibling = _seed_figshare(
        conn,
        source="openalex",
        source_id="W-f1",
        doi="10.6084/m9.figshare.23538907",
        title_normalized=f"additional file 1 of {_ARTICLE}",
    )

    assert _apply_cluster(conn) == 0
    assert _doi(conn, piece) == _doi(conn, sibling) == "10.6084/m9.figshare.23538907"
    assert _targets(conn) == {"10.6084/m9.figshare.23538907": "10.6084/m9.figshare.c.6702115"}


def test_figshare_additional_file_targets_the_collection_whatever_its_source_and_type(
    sa_sync_conn,
):
    """Une pièce présente seulement dans OpenAlex et une pièce typée `media` par DataCite ont pour cible la collection."""
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

    _apply_cluster(conn)
    assert set(_targets(conn)) == {_doi(conn, openalex_only), _doi(conn, media)}


def test_figshare_additional_file_without_number_targets_the_collection(sa_sync_conn):
    """Une pièce de titre « Additional file of T », sans numéro, a pour cible la collection."""
    conn = sa_sync_conn
    _seed_figshare(
        conn, source_id="c", doi="10.6084/m9.figshare.c.6702115", title_normalized=_ARTICLE
    )
    _seed_figshare(
        conn,
        source_id="f1",
        doi="10.6084/m9.figshare.23538907",
        title_normalized=f"additional file of {_ARTICLE}",
    )
    _apply_cluster(conn)
    assert _targets(conn) == {"10.6084/m9.figshare.23538907": "10.6084/m9.figshare.c.6702115"}


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


def test_dataset_piece_target_idempotent_and_self_heals_when_parent_retyped(sa_sync_conn):
    conn = sa_sync_conn
    parent = _typed_source_record(conn, source_id="d-parent", doi="10.9001/set", doc_type="dataset")
    _seed_datacite_piece(conn, source_id="d-piece", doi="10.9002/file1", parent_doi="10.9001/set")
    store = SourceRecordCorrectionStore(conn)
    targets = compute_doi_targets(store.fetch_secondary_form_declarations())
    assert store.replace_doi_targets(targets) == 1
    assert store.replace_doi_targets(targets) == 0  # idempotent

    # Parent retypé en article : la pièce perd sa cible.
    conn.execute(
        text("UPDATE source_records SET doc_type = 'article' WHERE id = :id"), {"id": parent}
    )
    _apply_cluster(conn)
    assert _targets(conn) == {}
