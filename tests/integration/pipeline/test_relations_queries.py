"""Intégration : rapprochement par titre (signal #3) — erratums et preprints.

Valide sur vraie base `fetch_erratum_title_matches` (suffixe de titre) et
`fetch_preprint_title_matches` (titre identique), et leur garde d'ambiguïté commune : un seul parent
« substantiel » (hors formes de la même œuvre) doit porter le titre, sinon collision → abstention.
Le parent est désigné par son `publication_id` ; son DOI peut être absent (cible au corpus sans DOI).
"""

import json

from sqlalchemy import text

from application.ports.pipeline.relations import DoiPublication, RelationEdge
from infrastructure.pipeline.relations import PgPublicationRelationsQueries
from infrastructure.repositories import publication_repository

_Q = PgPublicationRelationsQueries()

# Titre de parent assez long pour franchir la garde de longueur (> 30 caractères).
PARENT_TITLE = "measurement of differential cross sections in proton collisions"


def _pub(conn, *, doc_type, title_normalized, doi, pub_year=2024) -> int:
    return publication_repository(conn).create(
        title=title_normalized,
        title_normalized=title_normalized,
        doc_type=doc_type,
        pub_year=pub_year,
        doi=doi,
        oa_status="unknown",
    )


class TestFetchErratumTitleMatches:
    def test_unique_substantive_parent_matched(self, sa_sync_conn):
        parent = _pub(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/parent"
        )
        err = _pub(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
        )
        matches = _Q.fetch_erratum_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id, m.parent_doi) for m in matches] == [
            (err, parent, "10.1/parent")
        ]

    def test_doiless_parent_still_matched(self, sa_sync_conn):
        # Le parent au corpus n'a pas de DOI : rapproché quand même, parent_doi None.
        parent = _pub(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi=None)
        err = _pub(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
        )
        matches = _Q.fetch_erratum_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id, m.parent_doi) for m in matches] == [(err, parent, None)]

    def test_two_substantive_same_title_blocked(self, sa_sync_conn):
        # Deux articles distincts au même titre = collision → abstention.
        _pub(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/p1")
        _pub(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/p2")
        _pub(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
        )
        assert _Q.fetch_erratum_title_matches(sa_sync_conn) == []

    def test_preprint_does_not_block_and_article_chosen(self, sa_sync_conn):
        # Le preprint partage le titre mais n'est pas un parent substantiel : on relie l'article.
        article = _pub(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/article"
        )
        _pub(sa_sync_conn, doc_type="preprint", title_normalized=PARENT_TITLE, doi="10.1/preprint")
        err = _pub(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
        )
        matches = _Q.fetch_erratum_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id) for m in matches] == [(err, article)]

    def test_parent_outside_year_window_not_matched(self, sa_sync_conn):
        _pub(
            sa_sync_conn,
            doc_type="article",
            title_normalized=PARENT_TITLE,
            doi="10.1/parent",
            pub_year=2020,
        )
        _pub(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
            pub_year=2024,
        )
        assert _Q.fetch_erratum_title_matches(sa_sync_conn) == []

    def test_short_title_not_matched(self, sa_sync_conn):
        short = "short title"  # <= 30 caractères → sous la garde de longueur
        _pub(sa_sync_conn, doc_type="article", title_normalized=short, doi="10.1/parent")
        _pub(
            sa_sync_conn, doc_type="erratum", title_normalized=f"erratum to {short}", doi="10.1/err"
        )
        assert _Q.fetch_erratum_title_matches(sa_sync_conn) == []


class TestFetchPreprintTitleMatches:
    def test_unique_published_parent_matched(self, sa_sync_conn):
        # La version publiée suit le preprint (année + 1), titre identique.
        parent = _pub(
            sa_sync_conn,
            doc_type="article",
            title_normalized=PARENT_TITLE,
            doi="10.1/pub",
            pub_year=2025,
        )
        pre = _pub(
            sa_sync_conn,
            doc_type="preprint",
            title_normalized=PARENT_TITLE,
            doi="10.1/pre",
            pub_year=2024,
        )
        matches = _Q.fetch_preprint_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id, m.parent_doi) for m in matches] == [
            (pre, parent, "10.1/pub")
        ]

    def test_two_published_versions_blocked(self, sa_sync_conn):
        _pub(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/a")
        _pub(
            sa_sync_conn,
            doc_type="conference_paper",
            title_normalized=PARENT_TITLE,
            doi="10.1/b",
        )
        _pub(sa_sync_conn, doc_type="preprint", title_normalized=PARENT_TITLE, doi="10.1/pre")
        assert _Q.fetch_preprint_title_matches(sa_sync_conn) == []

    def test_dataset_does_not_block(self, sa_sync_conn):
        article = _pub(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/article"
        )
        _pub(sa_sync_conn, doc_type="dataset", title_normalized=PARENT_TITLE, doi="10.1/data")
        pre = _pub(sa_sync_conn, doc_type="preprint", title_normalized=PARENT_TITLE, doi="10.1/pre")
        matches = _Q.fetch_preprint_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id) for m in matches] == [(pre, article)]

    def test_parent_before_preprint_not_matched(self, sa_sync_conn):
        # Une publication antérieure au preprint n'est pas sa version publiée.
        _pub(
            sa_sync_conn,
            doc_type="article",
            title_normalized=PARENT_TITLE,
            doi="10.1/old",
            pub_year=2022,
        )
        _pub(
            sa_sync_conn,
            doc_type="preprint",
            title_normalized=PARENT_TITLE,
            doi="10.1/pre",
            pub_year=2024,
        )
        assert _Q.fetch_preprint_title_matches(sa_sync_conn) == []


class TestRelationTargetDeletionCascades:
    """Régression : supprimer la publication cible d'une relation rapprochée par titre (cible au
    corpus sans DOI) supprime la relation via `ON DELETE CASCADE`, au lieu de nuller sa cible — ce
    qui la laissait sans cible, violant le CHECK `target_present` et faisant planter la dissolution
    d'orphelins et le merge."""

    def test_repo_delete_of_target_removes_relation(self, sa_sync_conn):
        parent = _pub(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi=None)
        child = _pub(
            sa_sync_conn, doc_type="preprint", title_normalized=PARENT_TITLE, doi="10.1/child"
        )
        sa_sync_conn.execute(
            text("""
                INSERT INTO publication_relations
                    (from_publication_id, relation_type, target_publication_id, target_doi, source)
                VALUES (:child, 'is_preprint_of', :parent, NULL, 'title_match')
            """),
            {"child": child, "parent": parent},
        )

        # Le chemin qui plantait : refresh_from_sources → repo.delete sur la cible orpheline.
        publication_repository(sa_sync_conn).delete(parent)

        remaining = sa_sync_conn.execute(
            text("SELECT count(*) FROM publication_relations WHERE from_publication_id = :c"),
            {"c": child},
        ).scalar_one()
        assert remaining == 0


def _notice_datacite(conn, publication_id, *, doi, doi_d_origine, cible):
    """Notice DataCite dont l'étape de correction a substitué le DOI."""
    conn.execute(
        text("""
            INSERT INTO source_publications
                (source, source_id, title, doi, publication_id, meta, raw_metadata)
            VALUES ('datacite', :sid, 'T', :doi, :pub, CAST(:meta AS jsonb), CAST(:raw AS jsonb))
        """),
        {
            "sid": doi_d_origine,
            "doi": doi,
            "pub": publication_id,
            "meta": json.dumps(
                {"related_identifiers": [{"relation_type": "IsVersionOf", "doi": cible}]}
            ),
            "raw": json.dumps(
                {"doi": {"raw": doi_d_origine, "corrected_by": "DATACITE_VERSION_TO_CONCEPT"}}
            ),
        },
    )


class TestRelationsDeMemeOeuvre:
    def test_la_notice_expose_son_doi_d_origine_et_le_type_de_sa_publication(self, sa_sync_conn):
        """Le préfixe se juge sur le DOI que la notice déclare, pas sur le DOI substitué."""
        pub = _pub(
            sa_sync_conn, doc_type="preprint", title_normalized="preprint", doi="10.48550/arxiv.1"
        )
        _notice_datacite(
            sa_sync_conn,
            pub,
            doi="10.1007/article",
            doi_d_origine="10.48550/arxiv.1",
            cible="10.1007/article",
        )
        sources = [
            s for s in _Q.fetch_declared_relation_sources(sa_sync_conn) if s.publication_id == pub
        ]
        assert [(s.doi, s.doc_type) for s in sources] == [("10.48550/arxiv.1", "preprint")]

    def test_publications_retrouvees_par_doi_quelle_que_soit_la_casse(self, sa_sync_conn):
        pub = _pub(
            sa_sync_conn, doc_type="article", title_normalized="article", doi="10.1007/JHEP.A1"
        )
        assert _Q.fetch_publications_by_doi(sa_sync_conn, ["10.1007/jhep.a1"]) == {
            "10.1007/jhep.a1": DoiPublication(pub, "article")
        }

    def test_aucun_doi_aucune_requete(self, sa_sync_conn):
        assert _Q.fetch_publications_by_doi(sa_sync_conn, []) == {}


class TestCountByRelationType:
    """Distribution par type, exposée en `details` de la phase `relations`.

    Régression : l'alias SQL `t` entrait en collision avec l'attribut déprécié
    `Row.t` de SQLAlchemy, si bien que `r.t` renvoyait la Row entière. Ce `Row`
    atterrissait dans `details["table"]` et rendait le payload non sérialisable en
    JSON — l'INSERT de l'exécution de phase (best-effort) échouait silencieusement
    et la phase `relations` disparaissait de l'observabilité.
    """

    def test_returns_json_serializable_str_int_pairs(self, sa_sync_conn):
        parent = _pub(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/a")
        sa_sync_conn.execute(
            text("""
                INSERT INTO publication_relations
                    (from_publication_id, relation_type, target_doi, source)
                VALUES (:p, 'is_preprint_of', '10.9/x', 'crossref'),
                       (:p, 'is_preprint_of', '10.9/y', 'crossref'),
                       (:p, 'has_part', '10.9/z', 'datacite')
            """),
            {"p": parent},
        )

        result = _Q.count_by_relation_type(sa_sync_conn)

        # Types natifs (pas de Row) → sérialisable, condition de l'enregistrement.
        assert all(isinstance(t, str) and isinstance(n, int) for t, n in result)
        json.dumps(result)  # ne doit pas lever
        assert dict(result) == {"is_preprint_of": 2, "has_part": 1}


class TestRebuildRelations:
    """Reconstruction complète et écart avec l'état précédent.

    La table est purgée puis réécrite à chaque run : le nombre d'arêtes écrites ne dit pas ce qui a
    changé. `rebuild_relations` compare les arêtes d'avant à celles d'après pour rendre les
    ajoutées, par type, et le nombre de disparues.
    """

    def _edge(self, from_id, relation_type, target_doi):
        return RelationEdge(from_id, relation_type, target_doi, "crossref")

    def test_une_reconstruction_a_l_identique_ne_change_rien(self, sa_sync_conn):
        publication = _pub(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/a"
        )
        edges = [self._edge(publication, "is_preprint_of", "10.9/x")]

        _Q.rebuild_relations(sa_sync_conn, edges)
        seconde = _Q.rebuild_relations(sa_sync_conn, edges)

        assert seconde.written == 1
        assert seconde.added_by_type == []
        assert seconde.removed == 0

    def test_les_aretes_ajoutees_se_comptent_par_type(self, sa_sync_conn):
        publication = _pub(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/b"
        )
        _Q.rebuild_relations(sa_sync_conn, [self._edge(publication, "is_preprint_of", "10.9/x")])

        rebuild = _Q.rebuild_relations(
            sa_sync_conn,
            [
                self._edge(publication, "is_preprint_of", "10.9/x"),
                self._edge(publication, "is_preprint_of", "10.9/y"),
                self._edge(publication, "has_part", "10.9/z"),
            ],
        )

        assert dict(rebuild.added_by_type) == {"is_preprint_of": 1, "has_part": 1}
        assert rebuild.removed == 0

    def test_les_aretes_disparues_se_comptent(self, sa_sync_conn):
        publication = _pub(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/c"
        )
        _Q.rebuild_relations(
            sa_sync_conn,
            [
                self._edge(publication, "is_preprint_of", "10.9/x"),
                self._edge(publication, "has_part", "10.9/z"),
            ],
        )

        rebuild = _Q.rebuild_relations(
            sa_sync_conn, [self._edge(publication, "is_preprint_of", "10.9/x")]
        )

        assert rebuild.added_by_type == []
        assert rebuild.removed == 1
