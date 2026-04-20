"""Tests d'intégration — déduplication des publications.

Teste la logique de find_or_create dans services/publications.py
avec une vraie base PostgreSQL (bibliometrie_test).
Chaque test tourne dans une transaction rollbackée (isolation complète).
"""

from psycopg2.extras import Json

from application.publications import find_by_nnt, find_or_create, refresh_from_sources
from infrastructure.repositories import publication_repository

# ── Helpers ──────────────────────────────────────────────────────


def _create(db, **kwargs):
    """Crée une publication via find_or_create et retourne (id, is_new)."""
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
    return find_or_create(db, **defaults, repo=publication_repository(db))


def _create_journal(db, title="Test Journal"):
    """Crée un journal minimal et retourne son id."""
    from domain.normalize import normalize_text

    db.execute(
        "INSERT INTO journals (title, title_normalized) VALUES (%s, %s) RETURNING id",
        (title, normalize_text(title)),
    )
    return db.fetchone()["id"]


# ── Même DOI → fusion ───────────────────────────────────────────


class TestDedupByDoi:
    def test_same_doi_same_type_merges(self, db):
        """Même DOI, même type → retrouve la même publication."""
        id1, new1 = _create(db, doi="10.1234/test", title="Article A", title_normalized="article a")
        id2, new2 = _create(
            db, doi="10.1234/test", title="Article A (bis)", title_normalized="article a bis"
        )

        assert new1 is True
        assert new2 is False
        assert id1 == id2

    def test_doi_case_insensitive(self, db):
        """DOI case-insensitive → fusion."""
        id1, _ = _create(db, doi="10.1234/ABC")
        id2, new2 = _create(db, doi="10.1234/abc")

        assert id1 == id2
        assert new2 is False

    def test_different_doi_creates_new(self, db):
        """DOI différents → deux publications distinctes."""
        id1, _ = _create(db, doi="10.1234/aaa")
        id2, _ = _create(db, doi="10.1234/bbb")

        assert id1 != id2


# ── DOI + types incompatibles ────────────────────────────────────


class TestDedupDoiTypeConflict:
    def test_chapter_vs_book_no_merge(self, db):
        """Même DOI, chapitre vs ouvrage → pas de fusion (DOI = celui de l'ouvrage)."""
        id_book, _ = _create(
            db, doi="10.1234/book", doc_type="book", title="The Book", title_normalized="the book"
        )
        id_chap, new = _create(
            db,
            doi="10.1234/book",
            doc_type="book_chapter",
            title="Chapter 1",
            title_normalized="chapter 1",
        )

        assert id_book != id_chap
        assert new is True

        # Le chapitre ne doit pas avoir hérité du DOI de l'ouvrage
        db.execute("SELECT doi FROM publications WHERE id = %s", (id_chap,))
        assert db.fetchone()["doi"] is None

    def test_book_vs_chapter_no_merge(self, db):
        """Même DOI, ouvrage après chapitre → pas de fusion, DOI retiré du chapitre."""
        id_chap, _ = _create(
            db,
            doi="10.1234/book",
            doc_type="book_chapter",
            title="Chapter 1",
            title_normalized="chapter 1",
        )
        id_book, _ = _create(
            db, doi="10.1234/book", doc_type="book", title="The Book", title_normalized="the book"
        )

        assert id_chap != id_book

        # Le DOI doit avoir été retiré du chapitre
        db.execute("SELECT doi FROM publications WHERE id = %s", (id_chap,))
        assert db.fetchone()["doi"] is None

    def test_two_chapters_same_doi_different_title(self, db):
        """Deux chapitres avec même DOI mais titres différents → pas de fusion, DOI retiré."""
        id1, _ = _create(
            db,
            doi="10.1234/book",
            doc_type="book_chapter",
            title="Chapter 1",
            title_normalized="chapter 1",
        )
        id2, _ = _create(
            db,
            doi="10.1234/book",
            doc_type="book_chapter",
            title="Chapter 2",
            title_normalized="chapter 2",
        )

        assert id1 != id2

        # DOI retiré des deux
        db.execute("SELECT doi FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["doi"] is None
        db.execute("SELECT doi FROM publications WHERE id = %s", (id2,))
        assert db.fetchone()["doi"] is None

    def test_two_chapters_same_doi_same_title(self, db):
        """Deux chapitres avec même DOI et même titre → fusion."""
        id1, _ = _create(
            db,
            doi="10.1234/chap",
            doc_type="book_chapter",
            title="Chapter 1",
            title_normalized="chapter 1",
        )
        id2, new = _create(
            db,
            doi="10.1234/chap",
            doc_type="book_chapter",
            title="Chapter 1",
            title_normalized="chapter 1",
        )

        assert id1 == id2
        assert new is False


# ── Déduplication par titre + année + journal ────────────────────


class TestDedupByTitle:
    def test_same_title_year_journal_no_merge(self, db):
        """Meme titre + annee + journal sans DOI commun -> pas de fusion."""
        jid = _create_journal(db)
        id1, _ = _create(
            db,
            title="Mon Article",
            title_normalized="mon article",
            pub_year=2024,
            journal_id=jid,
            doc_type="article",
        )
        id2, new = _create(
            db,
            title="Mon Article (v2)",
            title_normalized="mon article",
            pub_year=2024,
            journal_id=jid,
            doc_type="article",
        )

        assert id1 != id2
        assert new is True

    def test_same_title_different_year_no_merge(self, db):
        """Même titre + journal mais année différente → pas de fusion."""
        jid = _create_journal(db)
        id1, _ = _create(
            db, title_normalized="mon article", pub_year=2023, journal_id=jid, doc_type="article"
        )
        id2, _ = _create(
            db, title_normalized="mon article", pub_year=2024, journal_id=jid, doc_type="article"
        )

        assert id1 != id2

    def test_same_title_different_journal_no_merge(self, db):
        """Même titre + année mais journal différent → pas de fusion."""
        j1 = _create_journal(db, "Journal A")
        j2 = _create_journal(db, "Journal B")
        id1, _ = _create(
            db, title_normalized="mon article", pub_year=2024, journal_id=j1, doc_type="article"
        )
        id2, _ = _create(
            db, title_normalized="mon article", pub_year=2024, journal_id=j2, doc_type="article"
        )

        assert id1 != id2

    def test_title_match_with_contradicting_doi_no_merge(self, db):
        """Même titre+année+journal mais DOI contradictoires → pas de fusion."""
        jid = _create_journal(db)
        id1, _ = _create(
            db,
            doi="10.1234/aaa",
            title_normalized="mon article",
            pub_year=2024,
            journal_id=jid,
            doc_type="article",
        )
        id2, _ = _create(
            db,
            doi="10.1234/bbb",
            title_normalized="mon article",
            pub_year=2024,
            journal_id=jid,
            doc_type="article",
        )

        assert id1 != id2

    def test_title_match_only_for_articles(self, db):
        """Le match par titre ne s'applique qu'aux articles (pas book_chapter, etc.)."""
        jid = _create_journal(db)
        id1, _ = _create(
            db,
            title_normalized="mon chapitre",
            pub_year=2024,
            journal_id=jid,
            doc_type="book_chapter",
        )
        id2, _ = _create(
            db,
            title_normalized="mon chapitre",
            pub_year=2024,
            journal_id=jid,
            doc_type="book_chapter",
        )

        assert id1 != id2

    def test_no_journal_no_title_match(self, db):
        """Sans journal_id, pas de match par titre (trop risqué)."""
        id1, _ = _create(db, title_normalized="mon article", pub_year=2024, doc_type="article")
        id2, _ = _create(db, title_normalized="mon article", pub_year=2024, doc_type="article")

        assert id1 != id2


# ── Pas de DOI → pas de faux positif ────────────────────────────


class TestNoDoi:
    def test_no_doi_no_journal_creates_separate(self, db):
        """Sans DOI ni journal, chaque appel crée une publication distincte."""
        id1, _ = _create(db, title="Article X", title_normalized="article x")
        id2, _ = _create(db, title="Article Y", title_normalized="article y")

        assert id1 != id2

    def test_no_doi_same_title_no_merge_without_journal(self, db):
        """Sans DOI, même titre mais sans journal → pas de fusion."""
        id1, _ = _create(db, title_normalized="article x", doc_type="article")
        id2, _ = _create(db, title_normalized="article x", doc_type="article")

        assert id1 != id2


# ── Enrichissement ───────────────────────────────────────────────


class TestRefreshFromSources:
    """Teste refresh_from_sources : recalcul des métadonnées depuis source_publications."""

    def _insert_sd(self, db, pub_id, source, **kwargs):
        """Insère un source_document rattaché à pub_id."""
        db.execute(
            """
            INSERT INTO source_publications (source, source_id, title, pub_year, publication_id,
                                          doc_type, oa_status, language, journal_id)
            VALUES (%s, %s, 'Test', 2024, %s, %s, %s, %s, %s)
        """,
            (
                source,
                f"{source}-{pub_id}-{kwargs.get('oa_status', '')}",
                pub_id,
                kwargs.get("doc_type"),
                kwargs.get("oa_status"),
                kwargs.get("language"),
                kwargs.get("journal_id"),
            ),
        )

    def test_language_from_source(self, db):
        """refresh_from_sources propage les métadonnées des source_publications."""
        id1, _ = _create(
            db, doi="10.1234/enrich", oa_status="closed", pub_year=2024, doc_type="article"
        )
        self._insert_sd(db, id1, "hal", language="en", oa_status="closed")
        refresh_from_sources(db, id1, repo=publication_repository(db))

        db.execute("SELECT language FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["language"] == "en"

    def test_oa_status_upgrade(self, db):
        """Le statut OA le plus ouvert gagne (closed + green → green)."""
        id1, _ = _create(db, doi="10.1234/oa", oa_status="closed")
        self._insert_sd(db, id1, "hal", oa_status="closed")
        self._insert_sd(db, id1, "openalex", oa_status="green")
        refresh_from_sources(db, id1, repo=publication_repository(db))

        db.execute("SELECT oa_status FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["oa_status"] == "green"

    def test_diamond_always_wins(self, db):
        """Diamond prime sur tout."""
        id1, _ = _create(db, doi="10.1234/dia", oa_status="gold")
        self._insert_sd(db, id1, "hal", oa_status="gold")
        self._insert_sd(db, id1, "openalex", oa_status="diamond")
        refresh_from_sources(db, id1, repo=publication_repository(db))

        db.execute("SELECT oa_status FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["oa_status"] == "diamond"

    def test_source_priority_hal_over_openalex(self, db):
        """HAL est prioritaire sur OpenAlex pour les champs scalaires."""
        id1, _ = _create(db, doi="10.1234/prio", pub_year=2024, doc_type="article")
        self._insert_sd(db, id1, "openalex", language="en")
        self._insert_sd(db, id1, "hal", language="fr")
        refresh_from_sources(db, id1, repo=publication_repository(db))

        db.execute("SELECT language FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["language"] == "fr"

    def test_thesis_priority_theses_over_hal(self, db):
        """Pour les thèses, theses.fr est prioritaire."""
        id1, _ = _create(db, doi="10.1234/thesis-prio", pub_year=2024, doc_type="thesis")
        self._insert_sd(db, id1, "hal", language="en", doc_type="THESE")
        self._insert_sd(db, id1, "theses", language="fr", doc_type="thesis")
        refresh_from_sources(db, id1, repo=publication_repository(db))

        db.execute("SELECT language FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["language"] == "fr"

    def test_doc_type_mapping(self, db):
        """Les doc_types bruts sont mappés vers l'enum canonique."""
        id1, _ = _create(db, pub_year=2024, doc_type="other")
        self._insert_sd(db, id1, "hal", doc_type="ART")
        refresh_from_sources(db, id1, repo=publication_repository(db))

        db.execute("SELECT doc_type FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["doc_type"] == "article"

    def test_ongoing_thesis_to_thesis(self, db):
        """Un ongoing_thesis passe à thesis quand theses.fr le dit."""
        id1, _ = _create(db, pub_year=2024, doc_type="ongoing_thesis")
        self._insert_sd(db, id1, "theses", doc_type="thesis")
        refresh_from_sources(db, id1, repo=publication_repository(db))

        db.execute("SELECT doc_type FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["doc_type"] == "thesis"

    def test_keywords_merged(self, db):
        """Les keywords sont fusionnés sans doublons."""
        id1, _ = _create(db, pub_year=2024, doc_type="article")
        db.execute(
            """
            INSERT INTO source_publications (source, source_id, title, pub_year, publication_id, keywords)
            VALUES ('hal', 'hal-kw1', 'Test', 2024, %s, ARRAY['python', 'data']),
                   ('openalex', 'oa-kw1', 'Test', 2024, %s, ARRAY['Data', 'machine learning'])
        """,
            (id1, id1),
        )
        refresh_from_sources(db, id1, repo=publication_repository(db))

        db.execute("SELECT keywords FROM publications WHERE id = %s", (id1,))
        kw = db.fetchone()["keywords"]
        # 'data' et 'Data' sont dédupliqués (case-insensitive), 3 mots-clés
        assert len(kw) == 3
        lower_kw = [k.lower() for k in kw]
        assert "python" in lower_kw
        assert "data" in lower_kw
        assert "machine learning" in lower_kw

    def test_topics_composite_by_source(self, db):
        """publications.topics est un composite {source: data}, chaque source
        garde sa forme native. Rien n'est perdu (même en cas de clés en
        conflit entre sources, avant le fix les données OpenAlex étaient
        silencieusement perdues si HAL était prioritaire)."""
        id1, _ = _create(db, pub_year=2024, doc_type="article")
        db.execute(
            """
            INSERT INTO source_publications (source, source_id, title, pub_year, publication_id, topics)
            VALUES ('hal', 'hal-tp1', 'Test', 2024, %s, '{"hal_domains": ["info"]}'),
                   ('openalex', 'oa-tp1', 'Test', 2024, %s, '{"concepts": ["AI"], "hal_domains": ["math"]}')
        """,
            (id1, id1),
        )
        refresh_from_sources(db, id1, repo=publication_repository(db))

        db.execute("SELECT topics FROM publications WHERE id = %s", (id1,))
        topics = db.fetchone()["topics"]
        # Chaque source garde sa forme sous sa propre clé
        assert topics["hal"] == {"hal_domains": ["info"]}
        assert topics["openalex"] == {"concepts": ["AI"], "hal_domains": ["math"]}

    def test_topics_composite_supports_openalex_list(self, db):
        """OpenAlex stocke les topics en liste (hiérarchie domain/field/subfield/topic).
        Avant le fix, cette liste était silencieusement ignorée (isinstance dict check).
        Maintenant elle est conservée sous la clé 'openalex'."""
        id1, _ = _create(db, pub_year=2024, doc_type="article")
        db.execute(
            """
            INSERT INTO source_publications (source, source_id, title, pub_year, publication_id, topics)
            VALUES ('openalex', 'oa-tp2', 'Test', 2024, %s,
                    '[{"domain": "SS", "field": "Eco", "subfield": "Micro", "topic": "Behav", "score": 0.95}]'::jsonb),
                   ('theses', 'th-tp2', 'Test', 2024, %s, '{"discipline": "Info", "rameau": ["Algo"]}')
        """,
            (id1, id1),
        )
        refresh_from_sources(db, id1, repo=publication_repository(db))

        db.execute("SELECT topics FROM publications WHERE id = %s", (id1,))
        topics = db.fetchone()["topics"]
        # La liste OpenAlex est préservée telle quelle
        assert isinstance(topics["openalex"], list)
        assert topics["openalex"][0]["domain"] == "SS"
        # Et le dict theses.fr aussi
        assert topics["theses"]["discipline"] == "Info"

    def test_is_retracted_or(self, db):
        """is_retracted = True si au moins une source le dit."""
        id1, _ = _create(db, pub_year=2024, doc_type="article")
        db.execute(
            """
            INSERT INTO source_publications (source, source_id, title, pub_year, publication_id, is_retracted)
            VALUES ('hal', 'hal-ret1', 'Test', 2024, %s, FALSE),
                   ('openalex', 'oa-ret1', 'Test', 2024, %s, TRUE)
        """,
            (id1, id1),
        )
        refresh_from_sources(db, id1, repo=publication_repository(db))

        db.execute("SELECT is_retracted FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["is_retracted"] is True

    def test_allow_create_false(self, db):
        """allow_create=False → retourne None si non trouvée."""
        result, _ = find_or_create(
            db,
            title="X",
            title_normalized="x",
            pub_year=2024,
            allow_create=False,
            repo=publication_repository(db),
        )
        assert result is None


# ── Déduplication par NNT ──────────────────────────────────────


def _create_source_doc_with_nnt(db, pub_id, source, source_id, nnt):
    """Helper : crée un source_document avec NNT dans external_ids."""
    db.execute(
        """
        INSERT INTO source_publications
            (source, source_id, title, pub_year, publication_id, external_ids)
        VALUES (%s, %s, 'Thesis', 2023, %s, %s)
    """,
        (source, source_id, pub_id, Json({"nnt": nnt})),
    )


class TestDedupByNnt:
    def test_nnt_dedup_theses_first(self, db):
        """Thèse créée par theses.fr, retrouvée par NNT quand OpenAlex arrive."""
        id1, new1 = _create(
            db,
            title="Ma thèse",
            title_normalized="ma these",
            pub_year=2023,
            doc_type="thesis",
            nnt="2023UCFA0069",
        )
        assert new1 is True
        _create_source_doc_with_nnt(db, id1, "theses", "2023UCFA0069", "2023UCFA0069")

        id2, new2 = _create(
            db,
            title="My thesis",
            title_normalized="my thesis",
            pub_year=2023,
            doc_type="thesis",
            nnt="2023UCFA0069",
        )
        assert new2 is False
        assert id1 == id2

    def test_nnt_dedup_openalex_first(self, db):
        """Thèse créée par OpenAlex, retrouvée par NNT quand theses.fr arrive."""
        id1, new1 = _create(
            db,
            title="My thesis",
            title_normalized="my thesis",
            pub_year=2023,
            doc_type="thesis",
            nnt="2023UCFA0069",
        )
        assert new1 is True
        _create_source_doc_with_nnt(db, id1, "openalex", "W123", "2023UCFA0069")

        id2, new2 = _create(
            db,
            title="Ma thèse",
            title_normalized="ma these",
            pub_year=2023,
            doc_type="thesis",
            nnt="2023UCFA0069",
        )
        assert new2 is False
        assert id1 == id2

    def test_nnt_not_stored_as_doi(self, db):
        """Le NNT ne doit jamais se retrouver dans publications.doi."""
        id1, _ = _create(
            db,
            title="Ma thèse",
            title_normalized="ma these",
            pub_year=2023,
            doc_type="thesis",
            nnt="2023UCFA0069",
        )
        db.execute("SELECT doi FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["doi"] is None

    def test_thesis_with_both_doi_and_nnt(self, db):
        """Thèse avec DOI réel + NNT : le DOI est stocké dans doi, NNT sert au dedup."""
        id1, _ = _create(
            db,
            title="Ma thèse",
            title_normalized="ma these",
            pub_year=2023,
            doc_type="thesis",
            doi="10.1234/thesis",
            nnt="2023UCFA0069",
        )
        db.execute("SELECT doi FROM publications WHERE id = %s", (id1,))
        assert db.fetchone()["doi"] == "10.1234/thesis"

    def test_doi_dedup_takes_priority(self, db):
        """Le DOI a priorité sur le NNT pour la déduplication."""
        id1, _ = _create(
            db,
            title="Ma thèse",
            title_normalized="ma these",
            pub_year=2023,
            doc_type="thesis",
            doi="10.1234/thesis",
        )
        id2, new2 = _create(
            db,
            title="Ma thèse",
            title_normalized="ma these",
            pub_year=2023,
            doc_type="thesis",
            doi="10.1234/thesis",
            nnt="2023UCFA0069",
        )
        assert id1 == id2
        assert new2 is False

    def test_find_by_nnt(self, db):
        """find_by_nnt retrouve une publication via external_ids."""
        id1, _ = _create(
            db, title="Ma thèse", title_normalized="ma these", pub_year=2023, doc_type="thesis"
        )
        _create_source_doc_with_nnt(db, id1, "theses", "2023UCFA0069", "2023UCFA0069")

        result = find_by_nnt(db, "2023UCFA0069", repo=publication_repository(db))
        assert result is not None
        assert result.id == id1

    def test_find_by_nnt_case_insensitive(self, db):
        """find_by_nnt normalise en uppercase."""
        id1, _ = _create(
            db, title="Ma thèse", title_normalized="ma these", pub_year=2023, doc_type="thesis"
        )
        _create_source_doc_with_nnt(db, id1, "theses", "2023UCFA0069", "2023UCFA0069")

        result = find_by_nnt(db, "2023ucfa0069", repo=publication_repository(db))
        assert result is not None
        assert result.id == id1
