"""Tests d'intégration — déduplication des publications.

Teste la logique de find_or_create dans services/publications.py
avec une vraie base PostgreSQL (bibliometrie_test).
Chaque test tourne dans une transaction rollbackée (isolation complète).
"""

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.publications import find_by_nnt, find_or_create, refresh_from_sources
from domain.publications.identifiers import DOI
from domain.publications.publication import Publication
from infrastructure.repositories import publication_repository

# ── Helpers ──────────────────────────────────────────────────────


def _create(conn, **kwargs):
    """Crée une publication via find_or_create et retourne (pub_id, is_new).

    Extrait `nnt` des kwargs (pas un attribut de Publication, passé séparément).
    """
    nnt = kwargs.pop("nnt", None)
    defaults = {
        "title": "Test Publication",
        "title_normalized": "test publication",
        "pub_year": 2024,
        "doc_type": "article",
        "doi": None,
        "oa_status": "unknown",
        "journal_id": None,
    }
    defaults.update(kwargs)
    doi_str = defaults.pop("doi")
    pub = Publication(
        id=None,
        title=defaults["title"],
        title_normalized=defaults["title_normalized"],
        pub_year=defaults["pub_year"],
        doc_type=defaults["doc_type"],
        doi=DOI(doi_str) if doi_str else None,
        oa_status=defaults["oa_status"],
        journal_id=defaults["journal_id"],
        container_title=defaults.get("container_title"),
        language=defaults.get("language"),
    )
    result, is_new = find_or_create(pub, nnt=nnt, repo=publication_repository(conn))
    return (result.id if result else None), is_new


def _create_journal(conn, title="Test Journal"):
    """Crée un journal minimal et retourne son id."""
    from domain.normalize import normalize_text

    return conn.execute(
        text("INSERT INTO journals (title, title_normalized) VALUES (:t, :tn) RETURNING id"),
        {"t": title, "tn": normalize_text(title)},
    ).scalar_one()


def _doi_of(conn, pub_id):
    return conn.execute(
        text("SELECT doi FROM publications WHERE id = :id"), {"id": pub_id}
    ).scalar_one()


def _scalar(conn, sql, **binds):
    return conn.execute(text(sql), binds).scalar_one()


# ── Même DOI → fusion ───────────────────────────────────────────


class TestDedupByDoi:
    def test_same_doi_same_type_merges(self, sa_sync_conn):
        """Même DOI, même type → retrouve la même publication."""
        id1, new1 = _create(
            sa_sync_conn, doi="10.1234/test", title="Article A", title_normalized="article a"
        )
        id2, new2 = _create(
            sa_sync_conn,
            doi="10.1234/test",
            title="Article A (bis)",
            title_normalized="article a bis",
        )

        assert new1 is True
        assert new2 is False
        assert id1 == id2

    def test_doi_case_insensitive(self, sa_sync_conn):
        """DOI case-insensitive → fusion."""
        id1, _ = _create(sa_sync_conn, doi="10.1234/ABC")
        id2, new2 = _create(sa_sync_conn, doi="10.1234/abc")

        assert id1 == id2
        assert new2 is False

    def test_different_doi_creates_new(self, sa_sync_conn):
        """DOI différents → deux publications distinctes."""
        id1, _ = _create(sa_sync_conn, doi="10.1234/aaa")
        id2, _ = _create(sa_sync_conn, doi="10.1234/bbb")

        assert id1 != id2


# ── DOI + types incompatibles ────────────────────────────────────


class TestDedupDoiTypeConflict:
    def test_chapter_vs_book_no_merge(self, sa_sync_conn):
        """Même DOI, chapitre vs ouvrage → pas de fusion (DOI = celui de l'ouvrage)."""
        id_book, _ = _create(
            sa_sync_conn,
            doi="10.1234/book",
            doc_type="book",
            title="The Book",
            title_normalized="the book",
        )
        id_chap, new = _create(
            sa_sync_conn,
            doi="10.1234/book",
            doc_type="book_chapter",
            title="Chapter 1",
            title_normalized="chapter 1",
        )

        assert id_book != id_chap
        assert new is True

        # Le chapitre ne doit pas avoir hérité du DOI de l'ouvrage
        assert _doi_of(sa_sync_conn, id_chap) is None

    def test_book_vs_chapter_no_merge(self, sa_sync_conn):
        """Même DOI, ouvrage après chapitre → pas de fusion, DOI retiré du chapitre."""
        id_chap, _ = _create(
            sa_sync_conn,
            doi="10.1234/book",
            doc_type="book_chapter",
            title="Chapter 1",
            title_normalized="chapter 1",
        )
        id_book, _ = _create(
            sa_sync_conn,
            doi="10.1234/book",
            doc_type="book",
            title="The Book",
            title_normalized="the book",
        )

        assert id_chap != id_book

        # Le DOI doit avoir été retiré du chapitre
        assert _doi_of(sa_sync_conn, id_chap) is None

    def test_two_chapters_same_doi_different_title(self, sa_sync_conn):
        """Deux chapitres avec même DOI mais titres différents → pas de fusion, DOI retiré."""
        id1, _ = _create(
            sa_sync_conn,
            doi="10.1234/book",
            doc_type="book_chapter",
            title="Chapter 1",
            title_normalized="chapter 1",
        )
        id2, _ = _create(
            sa_sync_conn,
            doi="10.1234/book",
            doc_type="book_chapter",
            title="Chapter 2",
            title_normalized="chapter 2",
        )

        assert id1 != id2

        # DOI retiré des deux
        assert _doi_of(sa_sync_conn, id1) is None
        assert _doi_of(sa_sync_conn, id2) is None

    def test_two_chapters_same_doi_same_title(self, sa_sync_conn):
        """Deux chapitres avec même DOI et même titre → fusion."""
        id1, _ = _create(
            sa_sync_conn,
            doi="10.1234/chap",
            doc_type="book_chapter",
            title="Chapter 1",
            title_normalized="chapter 1",
        )
        id2, new = _create(
            sa_sync_conn,
            doi="10.1234/chap",
            doc_type="book_chapter",
            title="Chapter 1",
            title_normalized="chapter 1",
        )

        assert id1 == id2
        assert new is False


# ── Déduplication par titre + année + journal ────────────────────


class TestDedupByTitle:
    def test_same_title_year_journal_no_merge(self, sa_sync_conn):
        """Meme titre + annee + journal sans DOI commun -> pas de fusion."""
        jid = _create_journal(sa_sync_conn)
        id1, _ = _create(
            sa_sync_conn,
            title="Mon Article",
            title_normalized="mon article",
            pub_year=2024,
            journal_id=jid,
            doc_type="article",
        )
        id2, new = _create(
            sa_sync_conn,
            title="Mon Article (v2)",
            title_normalized="mon article",
            pub_year=2024,
            journal_id=jid,
            doc_type="article",
        )

        assert id1 != id2
        assert new is True

    def test_same_title_different_year_no_merge(self, sa_sync_conn):
        """Même titre + journal mais année différente → pas de fusion."""
        jid = _create_journal(sa_sync_conn)
        id1, _ = _create(
            sa_sync_conn,
            title_normalized="mon article",
            pub_year=2023,
            journal_id=jid,
            doc_type="article",
        )
        id2, _ = _create(
            sa_sync_conn,
            title_normalized="mon article",
            pub_year=2024,
            journal_id=jid,
            doc_type="article",
        )

        assert id1 != id2

    def test_same_title_different_journal_no_merge(self, sa_sync_conn):
        """Même titre + année mais journal différent → pas de fusion."""
        j1 = _create_journal(sa_sync_conn, "Journal A")
        j2 = _create_journal(sa_sync_conn, "Journal B")
        id1, _ = _create(
            sa_sync_conn,
            title_normalized="mon article",
            pub_year=2024,
            journal_id=j1,
            doc_type="article",
        )
        id2, _ = _create(
            sa_sync_conn,
            title_normalized="mon article",
            pub_year=2024,
            journal_id=j2,
            doc_type="article",
        )

        assert id1 != id2

    def test_title_match_with_contradicting_doi_no_merge(self, sa_sync_conn):
        """Même titre+année+journal mais DOI contradictoires → pas de fusion."""
        jid = _create_journal(sa_sync_conn)
        id1, _ = _create(
            sa_sync_conn,
            doi="10.1234/aaa",
            title_normalized="mon article",
            pub_year=2024,
            journal_id=jid,
            doc_type="article",
        )
        id2, _ = _create(
            sa_sync_conn,
            doi="10.1234/bbb",
            title_normalized="mon article",
            pub_year=2024,
            journal_id=jid,
            doc_type="article",
        )

        assert id1 != id2

    def test_title_match_only_for_articles(self, sa_sync_conn):
        """Le match par titre ne s'applique qu'aux articles (pas book_chapter, etc.)."""
        jid = _create_journal(sa_sync_conn)
        id1, _ = _create(
            sa_sync_conn,
            title_normalized="mon chapitre",
            pub_year=2024,
            journal_id=jid,
            doc_type="book_chapter",
        )
        id2, _ = _create(
            sa_sync_conn,
            title_normalized="mon chapitre",
            pub_year=2024,
            journal_id=jid,
            doc_type="book_chapter",
        )

        assert id1 != id2

    def test_no_journal_no_title_match(self, sa_sync_conn):
        """Sans journal_id, pas de match par titre (trop risqué)."""
        id1, _ = _create(
            sa_sync_conn, title_normalized="mon article", pub_year=2024, doc_type="article"
        )
        id2, _ = _create(
            sa_sync_conn, title_normalized="mon article", pub_year=2024, doc_type="article"
        )

        assert id1 != id2


# ── Pas de DOI → pas de faux positif ────────────────────────────


class TestNoDoi:
    def test_no_doi_no_journal_creates_separate(self, sa_sync_conn):
        """Sans DOI ni journal, chaque appel crée une publication distincte."""
        id1, _ = _create(sa_sync_conn, title="Article X", title_normalized="article x")
        id2, _ = _create(sa_sync_conn, title="Article Y", title_normalized="article y")

        assert id1 != id2

    def test_no_doi_same_title_no_merge_without_journal(self, sa_sync_conn):
        """Sans DOI, même titre mais sans journal → pas de fusion."""
        id1, _ = _create(sa_sync_conn, title_normalized="article x", doc_type="article")
        id2, _ = _create(sa_sync_conn, title_normalized="article x", doc_type="article")

        assert id1 != id2


# ── Enrichissement ───────────────────────────────────────────────


class TestRefreshFromSources:
    """Teste refresh_from_sources : recalcul des métadonnées depuis source_publications."""

    def _insert_sd(self, conn, pub_id, source, **kwargs):
        """Insère un source_document rattaché à pub_id."""
        conn.execute(
            text(
                """
                INSERT INTO source_publications (source, source_id, title, pub_year, publication_id,
                                              doc_type, oa_status, language, journal_id)
                VALUES (:source, :source_id, 'Test', 2024, :pub_id,
                        :doc_type, :oa_status, :language, :journal_id)
                """
            ),
            {
                "source": source,
                "source_id": f"{source}-{pub_id}-{kwargs.get('oa_status', '')}",
                "pub_id": pub_id,
                "doc_type": kwargs.get("doc_type"),
                "oa_status": kwargs.get("oa_status"),
                "language": kwargs.get("language"),
                "journal_id": kwargs.get("journal_id"),
            },
        )

    def test_language_from_source(self, sa_sync_conn):
        """refresh_from_sources propage les métadonnées des source_publications."""
        id1, _ = _create(
            sa_sync_conn,
            doi="10.1234/enrich",
            oa_status="closed",
            pub_year=2024,
            doc_type="article",
        )
        self._insert_sd(sa_sync_conn, id1, "hal", language="en", oa_status="closed")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        lang = _scalar(sa_sync_conn, "SELECT language FROM publications WHERE id = :id", id=id1)
        assert lang == "en"

    def test_oa_status_upgrade(self, sa_sync_conn):
        """Le statut OA le plus ouvert gagne (closed + green → green)."""
        id1, _ = _create(sa_sync_conn, doi="10.1234/oa", oa_status="closed")
        self._insert_sd(sa_sync_conn, id1, "hal", oa_status="closed")
        self._insert_sd(sa_sync_conn, id1, "openalex", oa_status="green")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        oa = _scalar(sa_sync_conn, "SELECT oa_status FROM publications WHERE id = :id", id=id1)
        assert oa == "green"

    def test_diamond_always_wins(self, sa_sync_conn):
        """Diamond prime sur tout."""
        id1, _ = _create(sa_sync_conn, doi="10.1234/dia", oa_status="gold")
        self._insert_sd(sa_sync_conn, id1, "hal", oa_status="gold")
        self._insert_sd(sa_sync_conn, id1, "openalex", oa_status="diamond")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        oa = _scalar(sa_sync_conn, "SELECT oa_status FROM publications WHERE id = :id", id=id1)
        assert oa == "diamond"

    def test_source_priority_hal_over_openalex(self, sa_sync_conn):
        """HAL est prioritaire sur OpenAlex pour les champs scalaires."""
        id1, _ = _create(sa_sync_conn, doi="10.1234/prio", pub_year=2024, doc_type="article")
        self._insert_sd(sa_sync_conn, id1, "openalex", language="en")
        self._insert_sd(sa_sync_conn, id1, "hal", language="fr")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        lang = _scalar(sa_sync_conn, "SELECT language FROM publications WHERE id = :id", id=id1)
        assert lang == "fr"

    def test_thesis_priority_theses_over_hal(self, sa_sync_conn):
        """Pour les thèses, theses.fr est prioritaire."""
        id1, _ = _create(sa_sync_conn, doi="10.1234/thesis-prio", pub_year=2024, doc_type="thesis")
        self._insert_sd(sa_sync_conn, id1, "hal", language="en", doc_type="THESE")
        self._insert_sd(sa_sync_conn, id1, "theses", language="fr", doc_type="thesis")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        lang = _scalar(sa_sync_conn, "SELECT language FROM publications WHERE id = :id", id=id1)
        assert lang == "fr"

    def test_source_priority_scanr_over_hal(self, sa_sync_conn):
        """Pour les non-thèses, ScanR est prioritaire sur HAL."""
        id1, _ = _create(sa_sync_conn, doi="10.1234/scanr-prio", pub_year=2024, doc_type="article")
        self._insert_sd(sa_sync_conn, id1, "hal", language="en", doc_type="ART")
        self._insert_sd(sa_sync_conn, id1, "scanr", language="fr", doc_type="article")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        lang = _scalar(sa_sync_conn, "SELECT language FROM publications WHERE id = :id", id=id1)
        assert lang == "fr"

    def test_doc_type_mapping(self, sa_sync_conn):
        """Les doc_types bruts sont mappés vers l'enum canonique."""
        id1, _ = _create(sa_sync_conn, pub_year=2024, doc_type="other")
        self._insert_sd(sa_sync_conn, id1, "hal", doc_type="ART")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        dt = _scalar(sa_sync_conn, "SELECT doc_type FROM publications WHERE id = :id", id=id1)
        assert dt == "article"

    def test_ongoing_thesis_to_thesis(self, sa_sync_conn):
        """Un ongoing_thesis passe à thesis quand theses.fr le dit."""
        id1, _ = _create(sa_sync_conn, pub_year=2024, doc_type="ongoing_thesis")
        self._insert_sd(sa_sync_conn, id1, "theses", doc_type="thesis")
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        dt = _scalar(sa_sync_conn, "SELECT doc_type FROM publications WHERE id = :id", id=id1)
        assert dt == "thesis"

    def test_keywords_merged(self, sa_sync_conn):
        """Les keywords sont fusionnés sans doublons."""
        id1, _ = _create(sa_sync_conn, pub_year=2024, doc_type="article")
        sa_sync_conn.execute(
            text(
                """
                INSERT INTO source_publications (source, source_id, title, pub_year, publication_id, keywords)
                VALUES ('hal', 'hal-kw1', 'Test', 2024, :p, ARRAY['python', 'data']),
                       ('openalex', 'oa-kw1', 'Test', 2024, :p, ARRAY['Data', 'machine learning'])
                """
            ),
            {"p": id1},
        )
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        kw = _scalar(sa_sync_conn, "SELECT keywords FROM publications WHERE id = :id", id=id1)
        # 'data' et 'Data' sont dédupliqués (case-insensitive), 3 mots-clés
        assert len(kw) == 3
        lower_kw = [k.lower() for k in kw]
        assert "python" in lower_kw
        assert "data" in lower_kw
        assert "machine learning" in lower_kw

    def test_topics_composite_by_source(self, sa_sync_conn):
        """publications.topics est un composite {source: data}, chaque source
        garde sa forme native. Rien n'est perdu (même en cas de clés en
        conflit entre sources, avant le fix les données OpenAlex étaient
        silencieusement perdues si HAL était prioritaire)."""
        id1, _ = _create(sa_sync_conn, pub_year=2024, doc_type="article")
        sa_sync_conn.execute(
            text(
                """
                INSERT INTO source_publications (source, source_id, title, pub_year, publication_id, topics)
                VALUES ('hal', 'hal-tp1', 'Test', 2024, :p, '{"hal_domains": ["info"]}'),
                       ('openalex', 'oa-tp1', 'Test', 2024, :p,
                        '{"concepts": ["AI"], "hal_domains": ["math"]}')
                """
            ),
            {"p": id1},
        )
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        topics = _scalar(sa_sync_conn, "SELECT topics FROM publications WHERE id = :id", id=id1)
        # Chaque source garde sa forme sous sa propre clé
        assert topics["hal"] == {"hal_domains": ["info"]}
        assert topics["openalex"] == {"concepts": ["AI"], "hal_domains": ["math"]}

    def test_topics_composite_supports_openalex_list(self, sa_sync_conn):
        """OpenAlex stocke les topics en liste (hiérarchie domain/field/subfield/topic).
        Avant le fix, cette liste était silencieusement ignorée (isinstance dict check).
        Maintenant elle est conservée sous la clé 'openalex'."""
        id1, _ = _create(sa_sync_conn, pub_year=2024, doc_type="article")
        sa_sync_conn.execute(
            text(
                """
                INSERT INTO source_publications (source, source_id, title, pub_year, publication_id, topics)
                VALUES ('openalex', 'oa-tp2', 'Test', 2024, :p,
                        '[{"domain": "SS", "field": "Eco", "subfield": "Micro", "topic": "Behav", "score": 0.95}]'::jsonb),
                       ('theses', 'th-tp2', 'Test', 2024, :p,
                        '{"discipline": "Info", "rameau": ["Algo"]}')
                """
            ),
            {"p": id1},
        )
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        topics = _scalar(sa_sync_conn, "SELECT topics FROM publications WHERE id = :id", id=id1)
        # La liste OpenAlex est préservée telle quelle
        assert isinstance(topics["openalex"], list)
        assert topics["openalex"][0]["domain"] == "SS"
        # Et le dict theses.fr aussi
        assert topics["theses"]["discipline"] == "Info"

    def test_is_retracted_or(self, sa_sync_conn):
        """is_retracted = True si au moins une source le dit."""
        id1, _ = _create(sa_sync_conn, pub_year=2024, doc_type="article")
        sa_sync_conn.execute(
            text(
                """
                INSERT INTO source_publications (source, source_id, title, pub_year, publication_id, is_retracted)
                VALUES ('hal', 'hal-ret1', 'Test', 2024, :p, FALSE),
                       ('openalex', 'oa-ret1', 'Test', 2024, :p, TRUE)
                """
            ),
            {"p": id1},
        )
        refresh_from_sources(id1, repo=publication_repository(sa_sync_conn))

        is_ret = _scalar(
            sa_sync_conn, "SELECT is_retracted FROM publications WHERE id = :id", id=id1
        )
        assert is_ret is True

    def test_allow_create_false(self, sa_sync_conn):
        """allow_create=False → retourne None si non trouvée."""
        result, _ = find_or_create(
            Publication(id=None, title="X", pub_year=2024, title_normalized="x"),
            allow_create=False,
            repo=publication_repository(sa_sync_conn),
        )
        assert result is None


# ── Déduplication par NNT ──────────────────────────────────────


_INSERT_NNT_SOURCE_DOC_SQL = text(
    """
    INSERT INTO source_publications
        (source, source_id, title, pub_year, publication_id, external_ids)
    VALUES (:source, :source_id, 'Thesis', 2023, :pub_id, :external_ids)
    """
).bindparams(bindparam("external_ids", type_=JSONB))


def _create_source_doc_with_nnt(conn, pub_id, source, source_id, nnt):
    """Helper : crée un source_document avec NNT dans external_ids."""
    conn.execute(
        _INSERT_NNT_SOURCE_DOC_SQL,
        {
            "source": source,
            "source_id": source_id,
            "pub_id": pub_id,
            "external_ids": {"nnt": nnt},
        },
    )


class TestDedupByNnt:
    def test_nnt_dedup_theses_first(self, sa_sync_conn):
        """Thèse créée par theses.fr, retrouvée par NNT quand OpenAlex arrive."""
        id1, new1 = _create(
            sa_sync_conn,
            title="Ma thèse",
            title_normalized="ma these",
            pub_year=2023,
            doc_type="thesis",
            nnt="2023UCFA0069",
        )
        assert new1 is True
        _create_source_doc_with_nnt(sa_sync_conn, id1, "theses", "2023UCFA0069", "2023UCFA0069")

        id2, new2 = _create(
            sa_sync_conn,
            title="My thesis",
            title_normalized="my thesis",
            pub_year=2023,
            doc_type="thesis",
            nnt="2023UCFA0069",
        )
        assert new2 is False
        assert id1 == id2

    def test_nnt_dedup_openalex_first(self, sa_sync_conn):
        """Thèse créée par OpenAlex, retrouvée par NNT quand theses.fr arrive."""
        id1, new1 = _create(
            sa_sync_conn,
            title="My thesis",
            title_normalized="my thesis",
            pub_year=2023,
            doc_type="thesis",
            nnt="2023UCFA0069",
        )
        assert new1 is True
        _create_source_doc_with_nnt(sa_sync_conn, id1, "openalex", "W123", "2023UCFA0069")

        id2, new2 = _create(
            sa_sync_conn,
            title="Ma thèse",
            title_normalized="ma these",
            pub_year=2023,
            doc_type="thesis",
            nnt="2023UCFA0069",
        )
        assert new2 is False
        assert id1 == id2

    def test_nnt_not_stored_as_doi(self, sa_sync_conn):
        """Le NNT ne doit jamais se retrouver dans publications.doi."""
        id1, _ = _create(
            sa_sync_conn,
            title="Ma thèse",
            title_normalized="ma these",
            pub_year=2023,
            doc_type="thesis",
            nnt="2023UCFA0069",
        )
        assert _doi_of(sa_sync_conn, id1) is None

    def test_thesis_with_both_doi_and_nnt(self, sa_sync_conn):
        """Thèse avec DOI réel + NNT : le DOI est stocké dans doi, NNT sert au dedup."""
        id1, _ = _create(
            sa_sync_conn,
            title="Ma thèse",
            title_normalized="ma these",
            pub_year=2023,
            doc_type="thesis",
            doi="10.1234/thesis",
            nnt="2023UCFA0069",
        )
        assert _doi_of(sa_sync_conn, id1) == "10.1234/thesis"

    def test_doi_dedup_takes_priority(self, sa_sync_conn):
        """Le DOI a priorité sur le NNT pour la déduplication."""
        id1, _ = _create(
            sa_sync_conn,
            title="Ma thèse",
            title_normalized="ma these",
            pub_year=2023,
            doc_type="thesis",
            doi="10.1234/thesis",
        )
        id2, new2 = _create(
            sa_sync_conn,
            title="Ma thèse",
            title_normalized="ma these",
            pub_year=2023,
            doc_type="thesis",
            doi="10.1234/thesis",
            nnt="2023UCFA0069",
        )
        assert id1 == id2
        assert new2 is False

    def test_find_by_nnt(self, sa_sync_conn):
        """find_by_nnt retrouve une publication via external_ids."""
        id1, _ = _create(
            sa_sync_conn,
            title="Ma thèse",
            title_normalized="ma these",
            pub_year=2023,
            doc_type="thesis",
        )
        _create_source_doc_with_nnt(sa_sync_conn, id1, "theses", "2023UCFA0069", "2023UCFA0069")

        result = find_by_nnt("2023UCFA0069", repo=publication_repository(sa_sync_conn))
        assert result is not None
        assert result.id == id1

    def test_find_by_nnt_case_insensitive(self, sa_sync_conn):
        """find_by_nnt normalise en uppercase."""
        id1, _ = _create(
            sa_sync_conn,
            title="Ma thèse",
            title_normalized="ma these",
            pub_year=2023,
            doc_type="thesis",
        )
        _create_source_doc_with_nnt(sa_sync_conn, id1, "theses", "2023UCFA0069", "2023UCFA0069")

        result = find_by_nnt("2023ucfa0069", repo=publication_repository(sa_sync_conn))
        assert result is not None
        assert result.id == id1
