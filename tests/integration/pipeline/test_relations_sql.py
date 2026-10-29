"""Phase `relations` : matching par titre, relations déclarées par les sources, paires de publications à clé partagée, reconstruction de `publication_relations`.

Le matching par titre relie un erratum (`fetch_erratum_title_matches`, suffixe de titre) ou un preprint (`fetch_preprint_title_matches`, titre identique) à son parent. Le parent doit être la seule publication substantielle de ce titre, hors autres formes de la même œuvre ; sinon, aucun lien. Le parent est désigné par son `publication_id`, avec ou sans DOI.
"""

import json
import logging
from contextlib import contextmanager
from functools import partial

from sqlalchemy import text

from pipeline.runtime.context import PhaseContext, RunOptions
from pipeline.transformation.publications import relations
from pipeline.transformation.publications.relations import (
    DoiPublication,
    RelationEdge,
    RelationsPhase,
)
from pipeline.transformation.publications.store import PublicationStore
from tests.integration.helpers.publications import insert_publication, insert_publication_relation
from tests.integration.helpers.sources import insert_source_record, secondary_identifiers

# Enregistrement source de titre « t ».
_source_record = partial(insert_source_record, title="t")

# Titre de parent au-dessus de la garde de longueur (plus de 30 caractères).
PARENT_TITLE = "measurement of differential cross sections in proton collisions"


def _add_doi_target(conn, doi, target_doi) -> None:
    conn.execute(
        text(
            "INSERT INTO doi_targets (doi, target_doi, rule)"
            " VALUES (:doi, :target, 'DATACITE_VERSION_TO_CONCEPT')"
        ),
        {"doi": doi, "target": target_doi},
    )


def _publication(conn, *, doc_type, title_normalized, doi, publication_year=2024) -> int:
    return insert_publication(
        conn,
        title_normalized,
        title_normalized=title_normalized,
        doc_type=doc_type,
        doi=doi,
        publication_year=publication_year,
    )


class TestFetchErratumTitleMatches:
    def test_unique_substantive_parent_matched(self, sa_sync_conn):
        parent = _publication(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/parent"
        )
        err = _publication(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
        )
        matches = relations.fetch_erratum_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id, m.parent_doi) for m in matches] == [
            (err, parent, "10.1/parent")
        ]

    def test_doiless_parent_still_matched(self, sa_sync_conn):
        # Le parent est sans DOI : le lien se fait, avec `parent_doi` à `None`.
        parent = _publication(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi=None
        )
        err = _publication(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
        )
        matches = relations.fetch_erratum_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id, m.parent_doi) for m in matches] == [(err, parent, None)]

    def test_two_substantive_same_title_blocked(self, sa_sync_conn):
        # Deux articles distincts au même titre : aucun lien.
        _publication(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/p1")
        _publication(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/p2")
        _publication(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
        )
        assert relations.fetch_erratum_title_matches(sa_sync_conn) == []

    def test_preprint_does_not_block_and_article_chosen(self, sa_sync_conn):
        # Le preprint a le même titre mais compte comme autre forme de l'œuvre : l'erratum est relié à l'article.
        article = _publication(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/article"
        )
        _publication(
            sa_sync_conn, doc_type="preprint", title_normalized=PARENT_TITLE, doi="10.1/preprint"
        )
        err = _publication(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
        )
        matches = relations.fetch_erratum_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id) for m in matches] == [(err, article)]

    def test_parent_outside_year_window_not_matched(self, sa_sync_conn):
        _publication(
            sa_sync_conn,
            doc_type="article",
            title_normalized=PARENT_TITLE,
            doi="10.1/parent",
            publication_year=2020,
        )
        _publication(
            sa_sync_conn,
            doc_type="erratum",
            title_normalized=f"erratum to {PARENT_TITLE}",
            doi="10.1/err",
            publication_year=2024,
        )
        assert relations.fetch_erratum_title_matches(sa_sync_conn) == []

    def test_short_title_not_matched(self, sa_sync_conn):
        short = "short title"  # 30 caractères au plus : sous la garde de longueur
        _publication(sa_sync_conn, doc_type="article", title_normalized=short, doi="10.1/parent")
        _publication(
            sa_sync_conn, doc_type="erratum", title_normalized=f"erratum to {short}", doi="10.1/err"
        )
        assert relations.fetch_erratum_title_matches(sa_sync_conn) == []


class TestFetchPreprintTitleMatches:
    def test_unique_published_parent_matched(self, sa_sync_conn):
        # La version publiée suit le preprint d'un an, sous le même titre.
        parent = _publication(
            sa_sync_conn,
            doc_type="article",
            title_normalized=PARENT_TITLE,
            doi="10.1/pub",
            publication_year=2025,
        )
        pre = _publication(
            sa_sync_conn,
            doc_type="preprint",
            title_normalized=PARENT_TITLE,
            doi="10.1/pre",
            publication_year=2024,
        )
        matches = relations.fetch_preprint_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id, m.parent_doi) for m in matches] == [
            (pre, parent, "10.1/pub")
        ]

    def test_two_published_versions_blocked(self, sa_sync_conn):
        _publication(sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/a")
        _publication(
            sa_sync_conn,
            doc_type="conference_paper",
            title_normalized=PARENT_TITLE,
            doi="10.1/b",
        )
        _publication(
            sa_sync_conn, doc_type="preprint", title_normalized=PARENT_TITLE, doi="10.1/pre"
        )
        assert relations.fetch_preprint_title_matches(sa_sync_conn) == []

    def test_dataset_does_not_block(self, sa_sync_conn):
        article = _publication(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/article"
        )
        _publication(
            sa_sync_conn, doc_type="dataset", title_normalized=PARENT_TITLE, doi="10.1/data"
        )
        pre = _publication(
            sa_sync_conn, doc_type="preprint", title_normalized=PARENT_TITLE, doi="10.1/pre"
        )
        matches = relations.fetch_preprint_title_matches(sa_sync_conn)
        assert [(m.child_id, m.parent_id) for m in matches] == [(pre, article)]

    def test_parent_before_preprint_not_matched(self, sa_sync_conn):
        # Une publication antérieure au preprint n'est pas sa version publiée.
        _publication(
            sa_sync_conn,
            doc_type="article",
            title_normalized=PARENT_TITLE,
            doi="10.1/old",
            publication_year=2022,
        )
        _publication(
            sa_sync_conn,
            doc_type="preprint",
            title_normalized=PARENT_TITLE,
            doi="10.1/pre",
            publication_year=2024,
        )
        assert relations.fetch_preprint_title_matches(sa_sync_conn) == []


class TestRelationTargetDeletionCascades:
    """Régression : la suppression de la cible sans DOI d'une relation trouvée par titre laissait la relation sans cible, ce qui violait la contrainte `target_present` et faisait échouer la suppression des publications et la fusion. La relation est supprimée en cascade."""

    def test_repo_delete_of_target_removes_relation(self, sa_sync_conn):
        parent = _publication(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi=None
        )
        child = _publication(
            sa_sync_conn, doc_type="preprint", title_normalized=PARENT_TITLE, doi="10.1/child"
        )
        insert_publication_relation(
            sa_sync_conn,
            child,
            relation_type="is_preprint_of",
            source="title_match",
            target_publication_id=parent,
        )

        # `lifecycle.refresh` supprime ainsi une publication devenue orpheline.
        PublicationStore(sa_sync_conn).delete(parent)

        remaining = sa_sync_conn.execute(
            text("SELECT count(*) FROM publication_relations WHERE from_publication_id = :c"),
            {"c": child},
        ).scalar_one()
        assert remaining == 0


def _source_record_datacite(conn, publication_id, *, doi, doi_d_origine, cible, doc_type=None):
    """Enregistrement source DataCite dont le DOI d'origine est gardé dans `corrections`."""
    insert_source_record(
        conn,
        publication_id,
        source="datacite",
        source_id=doi_d_origine,
        title="T",
        doi=doi,
        doc_type=doc_type,
        source_extras={"related_identifiers": [{"relation_type": "IsVersionOf", "doi": cible}]},
        corrections={"doi": {"raw": doi_d_origine, "corrected_by": "DATACITE_VERSION_TO_CONCEPT"}},
    )


class TestRelationsDeMemeOeuvre:
    def test_l_enregistrement_source_expose_son_doi_d_origine_et_le_type_de_sa_publication(
        self, sa_sync_conn
    ):
        """Le préfixe se juge sur le DOI que l'enregistrement source déclare, même retiré par une correction."""
        publication = _publication(
            sa_sync_conn, doc_type="preprint", title_normalized="preprint", doi="10.48550/arxiv.1"
        )
        _source_record_datacite(
            sa_sync_conn,
            publication,
            doi=None,
            doi_d_origine="10.48550/arxiv.1",
            cible="10.1007/article",
        )
        sources = [
            s
            for s in relations.fetch_declared_relation_sources(sa_sync_conn)
            if s.publication_id == publication
        ]
        assert [(s.doi, s.doc_type) for s in sources] == [("10.48550/arxiv.1", "preprint")]

    def test_l_enregistrement_source_expose_aussi_son_propre_type(self, sa_sync_conn):
        """La règle de même œuvre lit le type de l'enregistrement source, la relation celui de sa publication."""
        publication = _publication(
            sa_sync_conn, doc_type="article", title_normalized="article", doi="10.3204/pubdb-1"
        )
        _source_record_datacite(
            sa_sync_conn,
            publication,
            doi="10.3204/pubdb-1",
            doi_d_origine="10.3204/pubdb-1",
            cible="10.1140/article",
            doc_type="preprint",
        )
        sources = [
            s
            for s in relations.fetch_declared_relation_sources(sa_sync_conn)
            if s.publication_id == publication
        ]
        assert [(s.doc_type, s.source_record_doc_type) for s in sources] == [
            ("article", "preprint")
        ]

    def test_publications_retrouvees_par_doi_quelle_que_soit_la_casse(self, sa_sync_conn):
        publication = _publication(
            sa_sync_conn, doc_type="article", title_normalized="article", doi="10.1007/JHEP.A1"
        )
        assert relations.fetch_publications_by_doi(sa_sync_conn, ["10.1007/jhep.a1"]) == {
            "10.1007/jhep.a1": DoiPublication(publication, "article")
        }

    def test_aucun_doi_aucune_requete(self, sa_sync_conn):
        assert relations.fetch_publications_by_doi(sa_sync_conn, []) == {}

    def test_le_doi_d_une_forme_secondaire_designe_la_publication_de_sa_cible(self, sa_sync_conn):
        """Le DOI d'une version Zenodo désigne la publication de son concept."""
        concept = _publication(
            sa_sync_conn, doc_type="dataset", title_normalized="jeu", doi="10.5281/zenodo.100"
        )
        _add_doi_target(sa_sync_conn, "10.5281/zenodo.101", "10.5281/zenodo.100")
        assert relations.fetch_publications_by_doi(sa_sync_conn, ["10.5281/zenodo.101"]) == {
            "10.5281/zenodo.101": DoiPublication(concept, "dataset")
        }


class TestCountByRelationType:
    """Nombre de relations par type, affiché dans les `details` de la phase `relations`.

    Régression : l'alias SQL `t` masquait l'attribut `Row.t` de SQLAlchemy, et `r.t` renvoyait la ligne entière. Les `details` devenaient non sérialisables en JSON, et l'enregistrement de l'exécution de la phase échouait sans erreur visible.
    """

    def test_returns_json_serializable_str_int_pairs(self, sa_sync_conn):
        parent = _publication(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/a"
        )
        for relation_type, target_doi, source in (
            ("is_preprint_of", "10.9/x", "crossref"),
            ("is_preprint_of", "10.9/y", "crossref"),
            ("has_part", "10.9/z", "datacite"),
        ):
            insert_publication_relation(
                sa_sync_conn,
                parent,
                relation_type=relation_type,
                source=source,
                target_doi=target_doi,
            )

        result = relations.count_by_relation_type(sa_sync_conn)

        # Des types Python simples, sérialisables en JSON, comme l'exige l'enregistrement de l'exécution.
        assert all(isinstance(t, str) and isinstance(n, int) for t, n in result)
        json.dumps(result)  # sans exception
        assert dict(result) == {"is_preprint_of": 2, "has_part": 1}


class TestRebuildRelations:
    """Reconstruction complète de la table, et écart avec l'état précédent.

    La table est vidée puis réécrite à chaque run. `rebuild_relations` compare les relations d'avant et d'après : il compte les relations ajoutées, par type, et les relations disparues.
    """

    def _edge(self, from_id, relation_type, target_doi):
        return RelationEdge(from_id, relation_type, target_doi, "crossref")

    def test_la_cible_d_une_relation_au_doi_d_une_forme_secondaire_est_sa_cible(self, sa_sync_conn):
        """Une relation vers le DOI d'une version Zenodo pointe la publication du concept."""
        article = _publication(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/a"
        )
        concept = _publication(
            sa_sync_conn, doc_type="dataset", title_normalized="jeu", doi="10.5281/zenodo.100"
        )
        _add_doi_target(sa_sync_conn, "10.5281/zenodo.101", "10.5281/zenodo.100")

        relations.rebuild_relations(
            sa_sync_conn, [self._edge(article, "has_supplement", "10.5281/zenodo.101")]
        )

        assert sa_sync_conn.execute(
            text("SELECT target_publication_id, target_doi FROM publication_relations")
        ).all() == [(concept, "10.5281/zenodo.101")]

    def test_une_reconstruction_a_l_identique_ne_change_rien(self, sa_sync_conn):
        publication = _publication(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/a"
        )
        edges = [self._edge(publication, "is_preprint_of", "10.9/x")]

        relations.rebuild_relations(sa_sync_conn, edges)
        seconde = relations.rebuild_relations(sa_sync_conn, edges)

        assert seconde.written == 1
        assert seconde.added_by_type == []
        assert seconde.removed == 0

    def test_les_aretes_ajoutees_se_comptent_par_type(self, sa_sync_conn):
        publication = _publication(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/b"
        )
        relations.rebuild_relations(
            sa_sync_conn, [self._edge(publication, "is_preprint_of", "10.9/x")]
        )

        rebuild = relations.rebuild_relations(
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
        publication = _publication(
            sa_sync_conn, doc_type="article", title_normalized=PARENT_TITLE, doi="10.1/c"
        )
        relations.rebuild_relations(
            sa_sync_conn,
            [
                self._edge(publication, "is_preprint_of", "10.9/x"),
                self._edge(publication, "has_part", "10.9/z"),
            ],
        )

        rebuild = relations.rebuild_relations(
            sa_sync_conn, [self._edge(publication, "is_preprint_of", "10.9/x")]
        )

        assert rebuild.added_by_type == []
        assert rebuild.removed == 1


class TestFetchSharedKeyPairs:
    def test_publications_sans_doi_partageant_un_identifiant_hal(self, sa_sync_conn):
        """Deux publications distinctes qui partagent une clé forment une paire, avec ou sans DOI."""
        a = _publication(
            sa_sync_conn, doc_type="conference_paper", title_normalized="t-a", doi=None
        )
        b = _publication(sa_sync_conn, doc_type="poster", title_normalized="t-b", doi=None)
        _source_record(
            sa_sync_conn,
            a,
            source_id="hal-skp-1",
            identifiers=secondary_identifiers({"hal_id": ["hal-skp-1"]}),
        )
        _source_record(
            sa_sync_conn,
            b,
            source_id="hal-skp-2",
            identifiers=secondary_identifiers({"hal_id": ["hal-skp-2"]}),
        )
        _source_record(
            sa_sync_conn,
            a,
            source="openalex",
            source_id="W-skp",
            identifiers=secondary_identifiers({"hal_id": ["hal-skp-1", "hal-skp-2"]}),
        )

        pairs = [p for p in relations.fetch_shared_key_pairs(sa_sync_conn) if p.a_id == a]

        assert [(p.a_id, p.a_doi, p.b_id, p.b_doi) for p in pairs] == [(a, None, b, None)]


class TestPhaseRelations:
    def test_relation_declaree_ecarte_le_lien_vague_des_le_premier_run(self, sa_sync_conn):
        """Sur une table vide, une relation déclarée écarte le `is_related_to` d'une clé partagée par la même paire."""
        a = _publication(
            sa_sync_conn, doc_type="article", title_normalized="t-pr-a", doi="10.1/pr-a"
        )
        b = _publication(
            sa_sync_conn, doc_type="article", title_normalized="t-pr-b", doi="10.1/pr-b"
        )
        _source_record(
            sa_sync_conn,
            a,
            source_id="hal-pr-1",
            identifiers=secondary_identifiers({"hal_id": ["hal-pr-1"]}),
        )
        _source_record(
            sa_sync_conn,
            b,
            source_id="hal-pr-2",
            identifiers=secondary_identifiers({"hal_id": ["hal-pr-1"]}),
        )
        insert_source_record(
            sa_sync_conn,
            a,
            source="datacite",
            source_id="10.1/pr-a",
            title="t",
            doi="10.1/pr-a",
            source_extras={
                "related_identifiers": [{"relation_type": "IsSupplementTo", "doi": "10.1/pr-b"}]
            },
        )

        @contextmanager
        def open_tx():
            yield sa_sync_conn

        RelationsPhase().run(
            PhaseContext(
                open_tx=open_tx,
                logger=logging.getLogger("test"),
                options=RunOptions(),
                maintain=lambda operation: None,
                credentials_missing=lambda _source: None,
                request_budget=lambda _source: None,
            )
        )

        rows = sa_sync_conn.execute(
            text(
                "SELECT relation_type::text, source FROM publication_relations "
                "WHERE from_publication_id IN (:a, :b)"
            ),
            {"a": a, "b": b},
        ).all()
        assert [tuple(r) for r in rows] == [("is_supplement_to", "datacite")]
