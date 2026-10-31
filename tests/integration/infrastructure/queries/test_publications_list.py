"""Tests d'intégration pour `infrastructure.read_models.publications.list`."""

from functools import partial

from sqlalchemy import text

from domain.config import LABORATORY_TYPES_KEY
from infrastructure.read_models.publications.facets import _PublicationFacetsBuilder
from infrastructure.read_models.publications.filtering import FilterContext, filter_context
from infrastructure.read_models.publications.models import PublicationFilters
from infrastructure.read_models.stats.queries import StatsQueries
from tests.integration.helpers.alignment import align_source_contributions
from tests.integration.helpers.config import set_config
from tests.integration.helpers.contributions import contribution_id_of, insert_contribution
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.read_models import publications_queries
from tests.integration.helpers.serials import insert_doi_prefix, insert_publisher, insert_serial
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record
from tests.integration.helpers.structures import add_contribution_structure, insert_structure
from tests.integration.helpers.subjects import insert_publication_subject, insert_subject

# Laboratoire « LAB ».
_lab = partial(insert_structure, code="LAB")

# Enregistrement source de titre « T ».
_source_record = partial(insert_source_record, title="T")


def _attach(conn, publication_id, lab_id):
    """Insère une contribution du périmètre, d'une personne créée, qui relie la publication au laboratoire `lab_id`."""
    aid = insert_contribution(
        conn, publication_id, person_id=insert_person(conn), in_perimeter=True, roles=["author"]
    )
    add_contribution_structure(conn, aid, lab_id)


class TestSearch:
    def test_search_matches_title(self, sa_sync_conn):
        lab = _lab(sa_sync_conn)
        match = insert_publication(sa_sync_conn, "Quantum entanglement basics")
        other = insert_publication(sa_sync_conn, "Foo bar baz")
        _attach(sa_sync_conn, match, lab)
        _attach(sa_sync_conn, other, lab)

        res = publications_queries(sa_sync_conn).list_publications(
            filters=PublicationFilters(search="quantum", lab_ids=[lab]),
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p.id for p in res.publications]
        assert match in ids and other not in ids

    def test_search_matches_subject_label(self, sa_sync_conn):
        """Une publication dont le titre ne contient pas le terme figure dans les résultats si un de ses sujets le contient."""
        lab = _lab(sa_sync_conn)
        publication = insert_publication(sa_sync_conn, "Foo bar baz")
        unrelated = insert_publication(sa_sync_conn, "Hello world")
        _attach(sa_sync_conn, publication, lab)
        _attach(sa_sync_conn, unrelated, lab)

        sid = insert_subject(sa_sync_conn, "Quantum mechanics")
        insert_publication_subject(sa_sync_conn, publication, subject_id=sid)

        res = publications_queries(sa_sync_conn).list_publications(
            filters=PublicationFilters(search="quantum", lab_ids=[lab]),
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p.id for p in res.publications]
        assert publication in ids and unrelated not in ids

    def test_title_match_ranks_before_subject_only_match(self, sa_sync_conn):
        """Les publications dont le titre contient le terme passent avant celles qui le contiennent seulement dans un sujet, quel que soit le tri demandé."""
        lab = _lab(sa_sync_conn)
        # Titre qui contient « quantum ».
        title_match = insert_publication(sa_sync_conn, "Quantum entanglement basics")
        # Titre sans « quantum », sujet qui le contient.
        subject_match = insert_publication(sa_sync_conn, "Foo bar baz")
        _attach(sa_sync_conn, title_match, lab)
        _attach(sa_sync_conn, subject_match, lab)
        sid = insert_subject(sa_sync_conn, "Quantum mechanics")
        insert_publication_subject(sa_sync_conn, subject_match, subject_id=sid)

        res = publications_queries(sa_sync_conn).list_publications(
            filters=PublicationFilters(search="quantum", lab_ids=[lab]),
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p.id for p in res.publications]
        assert ids.index(title_match) < ids.index(subject_match)

    def test_search_unaccented_matches_accented_label(self, sa_sync_conn):
        """La recherche ignore les accents."""
        lab = _lab(sa_sync_conn)
        publication = insert_publication(sa_sync_conn, "Foo")
        _attach(sa_sync_conn, publication, lab)
        sid = insert_subject(sa_sync_conn, "Économétrie")
        insert_publication_subject(sa_sync_conn, publication, subject_id=sid)

        res = publications_queries(sa_sync_conn).list_publications(
            filters=PublicationFilters(search="econometrie", lab_ids=[lab]),
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p.id for p in res.publications]
        assert publication in ids

    def test_facets_respect_search(self, sa_sync_conn):
        """Les comptes de facettes suivent la recherche sur le titre, comme le tableau."""
        lab = _lab(sa_sync_conn)
        for title in ("quantum gravity", "classical mechanics"):
            pid = insert_publication(sa_sync_conn, title=title)
            _attach(sa_sync_conn, pid, lab)
            sa_sync_conn.execute(
                text("UPDATE publications SET perimeter_evidence = '{address}' WHERE id = :id"),
                {"id": pid},
            )

        def years_total(search: str) -> int:
            builder = _PublicationFacetsBuilder(
                sa_sync_conn,
                PublicationFilters(search=search, lab_ids=[lab]),
                FilterContext([], None),
            )
            return sum(r.count for r in builder._facet_years())

        assert years_total("") == 2
        assert years_total("quantum") == 1


class TestHalStatusMultipleHalEntries:
    """Une publication à plusieurs dépôts HAL est en collection dès qu'un de ses dépôts contient la collection du laboratoire. Le statut renvoyé avec chaque publication suit la même règle que le filtre."""

    def test_publication_in_collection_via_one_hal_entry_is_not_hors_collection(self, sa_sync_conn):
        """Deux dépôts HAL, dont un dans la collection du laboratoire : la publication est absente du filtre `hors_collection`."""
        lab = _lab(sa_sync_conn, hal_collection="CMH")
        publication = insert_publication(sa_sync_conn, "Two HAL deposits")
        _attach(sa_sync_conn, publication, lab)
        _source_record(
            sa_sync_conn, publication, source_id="hal-CMH", hal_collections=["CMH", "AO-DROIT"]
        )
        _source_record(
            sa_sync_conn, publication, source_id="hal-PAU", hal_collections=["UPPA-DROIT", "SHS"]
        )
        sa_sync_conn.execute(
            text("UPDATE publications SET oa_status = 'gold'::oa_type WHERE id = :id"),
            {"id": publication},
        )

        res = publications_queries(sa_sync_conn).list_publications(
            filters=PublicationFilters(lab_ids=[lab], hal_status_values=["hors_collection"]),
            page=1,
            per_page=50,
            sort="year_desc",
        )
        assert publication not in [p.id for p in res.publications]

    def test_listed_status_follows_the_filter_rule(self, sa_sync_conn):
        """Le statut renvoyé avec la publication est celui du filtre : en collection par l'un de ses dépôts, en open access, elle vaut `ok`."""
        lab = _lab(sa_sync_conn, hal_collection="CMH")
        publication = insert_publication(sa_sync_conn, "Two HAL deposits")
        _attach(sa_sync_conn, publication, lab)
        _source_record(
            sa_sync_conn, publication, source_id="hal-CMH", hal_collections=["CMH", "AO-DROIT"]
        )
        _source_record(
            sa_sync_conn, publication, source_id="hal-PAU", hal_collections=["UPPA-DROIT"]
        )
        sa_sync_conn.execute(
            text("UPDATE publications SET oa_status = 'gold'::oa_type WHERE id = :id"),
            {"id": publication},
        )

        res = publications_queries(sa_sync_conn).list_publications(
            filters=PublicationFilters(lab_ids=[lab]),
            page=1,
            per_page=50,
            sort="year_desc",
        )
        match = next(p for p in res.publications if p.id == publication)
        assert match.hal_status == "ok"

    def test_status_is_absent_without_a_single_lab(self, sa_sync_conn):
        lab = _lab(sa_sync_conn, hal_collection="CMH")
        publication = insert_publication(sa_sync_conn, "Lab-less listing")
        _attach(sa_sync_conn, publication, lab)
        _source_record(sa_sync_conn, publication, source_id="hal-X", hal_collections=["CMH"])

        res = publications_queries(sa_sync_conn).list_publications(
            filters=PublicationFilters(), page=1, per_page=200, sort="year_desc"
        )
        assert all(p.hal_status is None for p in res.publications)

    def test_publication_only_outside_collection_is_hors_collection(self, sa_sync_conn):
        """Aucun dépôt HAL dans la collection : la publication figure dans le filtre `hors_collection`."""
        lab = _lab(sa_sync_conn, hal_collection="CMH")
        publication = insert_publication(sa_sync_conn, "Outside only")
        _attach(sa_sync_conn, publication, lab)
        _source_record(
            sa_sync_conn, publication, source_id="hal-PAU", hal_collections=["UPPA-DROIT"]
        )

        res = publications_queries(sa_sync_conn).list_publications(
            filters=PublicationFilters(lab_ids=[lab], hal_status_values=["hors_collection"]),
            page=1,
            per_page=50,
            sort="year_desc",
        )
        assert publication in [p.id for p in res.publications]

    def test_ok_without_declared_collection_matches_nothing(self, sa_sync_conn):
        """Laboratoire sans collection HAL : le filtre `ok` (en collection et en open access) renvoie zéro publication."""
        lab = insert_structure(sa_sync_conn, "LABNC")
        publication = insert_publication(sa_sync_conn, "Open in HAL")
        _attach(sa_sync_conn, publication, lab)
        _source_record(sa_sync_conn, publication, source_id="hal-x", hal_collections=["SOME-COL"])
        sa_sync_conn.execute(
            text("UPDATE publications SET oa_status = 'gold'::oa_type WHERE id = :id"),
            {"id": publication},
        )

        res = publications_queries(sa_sync_conn).list_publications(
            filters=PublicationFilters(lab_ids=[lab], hal_status_values=["ok"]),
            page=1,
            per_page=50,
            sort="year_desc",
        )
        assert res.publications == []


class TestThesesExport:
    """Export CSV des thèses. La boucle de rendu lit chaque colonne de la requête : seul un test avec données vérifie l'accord entre la requête et le CSV."""

    def test_renders_a_thesis_with_each_source_url(self, sa_sync_conn):
        lab = _lab(sa_sync_conn)
        publication = insert_publication(sa_sync_conn, "Ma these", doc_type="thesis")
        _attach(sa_sync_conn, publication, lab)
        for src, sid in (
            ("hal", "hal-1"),
            ("openalex", "W1"),
            ("scanr", "sc-1"),
            ("theses", "2024NNT"),
        ):
            _source_record(sa_sync_conn, publication, source=src, source_id=sid)

        csv_text = "".join(
            publications_queries(sa_sync_conn).export_theses_csv(
                filters=PublicationFilters(lab_ids=[lab], doc_types=["thesis"]),
                sort="soutenance_desc",
                columns=[],
            )
        )

        line = next(row for row in csv_text.splitlines() if "Ma these" in row)
        assert "hal.science/hal-1" in line
        assert "openalex.org/W1" in line
        assert "scanr.enseignementsup-recherche.gouv.fr/publications/sc-1" in line
        assert "theses.fr/2024NNT" in line

    def test_l_acces_donne_l_adresse_du_texte_integral(self, sa_sync_conn):
        lab = _lab(sa_sync_conn)
        publication = insert_publication(
            sa_sync_conn, "Ma these", doc_type="thesis", oa_status="green"
        )
        sa_sync_conn.execute(
            text(
                "UPDATE publications SET best_copy_url = 'https://theses.hal.science/tel-1' WHERE id = :id"
            ),
            {"id": publication},
        )
        _attach(sa_sync_conn, publication, lab)

        csv_text = "".join(
            publications_queries(sa_sync_conn).export_theses_csv(
                filters=PublicationFilters(lab_ids=[lab], doc_types=["thesis"]),
                sort="soutenance_desc",
                columns=[],
            )
        )

        header, line = csv_text.lstrip("﻿").splitlines()[:2]
        assert header.split(",")[-1] == "Accès"
        assert line.split(",")[-1] == "https://theses.hal.science/tel-1"

    def test_emits_the_visible_columns_in_table_order(self, sa_sync_conn):
        """Les colonnes demandées, plus le titre et l'accès, dans l'ordre du tableau ; l'auteur est écrit comme à l'affichage."""
        lab = _lab(sa_sync_conn)
        publication = insert_publication(sa_sync_conn, "Ma these", doc_type="thesis")
        author = insert_person(sa_sync_conn, "DUPONT", first_name="jean")
        contribution = insert_contribution(
            sa_sync_conn, publication, person_id=author, in_perimeter=True, roles=["author"]
        )
        add_contribution_structure(sa_sync_conn, contribution, lab)

        csv_text = "".join(
            publications_queries(sa_sync_conn).export_theses_csv(
                filters=PublicationFilters(lab_ids=[lab], doc_types=["thesis"]),
                sort="soutenance_desc",
                columns=["status", "author"],
            )
        )

        header, line = csv_text.lstrip("﻿").splitlines()[:2]
        assert header == "Auteur,Titre,Statut,Accès"
        assert line.startswith("Jean Dupont,Ma these,Soutenue,")


class TestThesesSort:
    """Tri des thèses par auteur (nom puis prénom) et par laboratoires (premier libellé affiché), thèses sans valeur en dernier."""

    def _seed(self, conn):
        alpha, beta, gamma = (insert_structure(conn, code) for code in ("Alpha", "Beta", "Gamma"))
        zola, abel = (
            insert_person(conn, last_name, first_name=first_name)
            for last_name, first_name in (("Zola", "Albert"), ("Abel", "Zoé"))
        )
        theses = []
        for title, author, labs in (("T1", zola, (gamma, alpha)), ("T2", abel, (beta,))):
            thesis = insert_publication(conn, title, doc_type="thesis", in_perimeter=True)
            contribution = insert_contribution(
                conn, thesis, person_id=author, in_perimeter=True, roles=["author"]
            )
            for lab in labs:
                add_contribution_structure(conn, contribution, lab)
            theses.append(thesis)
        theses.append(insert_publication(conn, "T3", doc_type="thesis", in_perimeter=True))
        return theses

    def _sorted(self, conn, sort):
        res = publications_queries(conn).list_publications(
            filters=PublicationFilters(doc_types=["thesis"]), page=1, per_page=50, sort=sort
        )
        return [p.id for p in res.publications]

    def test_author_sort_reads_the_last_name(self, sa_sync_conn):
        t1, t2, t3 = self._seed(sa_sync_conn)

        assert self._sorted(sa_sync_conn, "author_asc") == [t2, t1, t3]
        assert self._sorted(sa_sync_conn, "author_desc") == [t1, t2, t3]

    def test_labs_sort_reads_the_first_label(self, sa_sync_conn):
        t1, t2, t3 = self._seed(sa_sync_conn)

        assert self._sorted(sa_sync_conn, "labs_asc") == [t1, t2, t3]
        assert self._sorted(sa_sync_conn, "labs_desc") == [t2, t1, t3]


class TestPublicationsSort:
    """Tri des publications par revue, éditeur et laboratoires, sans égard à la casse, publications sans valeur en dernier."""

    def _publication(self, conn, title, *, serial=None, publisher=None, labs=(), person=None):
        serial_id = insert_serial(conn, serial) if serial else None
        publication = insert_publication(conn, title, serial_id=serial_id, in_perimeter=True)
        if publisher:
            conn.execute(
                text("UPDATE publications SET publisher_id = :pub WHERE id = :p"),
                {"pub": insert_publisher(conn, publisher), "p": publication},
            )
        if labs:
            contribution = insert_contribution(
                conn,
                publication,
                person_id=person or insert_person(conn),
                in_perimeter=True,
                roles=["author"],
            )
            for lab in labs:
                add_contribution_structure(conn, contribution, lab)
        return publication

    def _sorted(self, conn, sort, **filters):
        res = publications_queries(conn).list_publications(
            filters=PublicationFilters(**filters), page=1, per_page=50, sort=sort
        )
        return [p.id for p in res.publications]

    def test_serial_publisher_and_labs_sorts(self, sa_sync_conn):
        alpha, beta, gamma = (insert_structure(sa_sync_conn, c) for c in ("Alpha", "Beta", "Gamma"))
        p1 = self._publication(
            sa_sync_conn, "P1", serial="zeta journal", publisher="Alpha Press", labs=(beta,)
        )
        p2 = self._publication(
            sa_sync_conn, "P2", serial="Alpha Journal", publisher="beta press", labs=(gamma, alpha)
        )
        p3 = self._publication(sa_sync_conn, "P3")

        assert self._sorted(sa_sync_conn, "serial_asc") == [p2, p1, p3]
        assert self._sorted(sa_sync_conn, "serial_desc") == [p1, p2, p3]
        assert self._sorted(sa_sync_conn, "publisher_asc") == [p1, p2, p3]
        assert self._sorted(sa_sync_conn, "publisher_desc") == [p2, p1, p3]
        assert self._sorted(sa_sync_conn, "labs_asc") == [p2, p1, p3]
        assert self._sorted(sa_sync_conn, "labs_desc") == [p1, p2, p3]

    def test_labs_sort_reads_the_labs_of_the_person(self, sa_sync_conn):
        """Sur la vue d'une personne, la colonne affiche seulement ses laboratoires : le tri lit les mêmes."""
        alpha, beta, zeta = (insert_structure(sa_sync_conn, c) for c in ("Alpha", "Beta", "Zeta"))
        person = insert_person(sa_sync_conn, "Focus")
        q1 = self._publication(sa_sync_conn, "Q1", labs=(zeta,), person=person)
        contribution = insert_contribution(
            sa_sync_conn,
            q1,
            person_id=insert_person(sa_sync_conn),
            in_perimeter=True,
            roles=["author"],
        )
        add_contribution_structure(sa_sync_conn, contribution, alpha)
        q2 = self._publication(sa_sync_conn, "Q2", labs=(beta,), person=person)

        assert self._sorted(sa_sync_conn, "labs_asc", person_id=person) == [q2, q1]


class TestLabScope:
    """Les laboratoires sélectionnés délimitent l'ensemble, hors périmètre compris, pour la liste, ses facettes et les statistiques."""

    def _seed(self, conn):
        lab = _lab(conn)
        for in_perimeter in (True, False):
            _attach(conn, insert_publication(conn, in_perimeter=in_perimeter), lab)
        return lab

    def test_list_facets_and_stats_count_the_same_set(self, sa_sync_conn):
        lab = self._seed(sa_sync_conn)
        filters = PublicationFilters(lab_ids=[lab])

        listed = publications_queries(sa_sync_conn).list_publications(
            filters=filters, page=1, per_page=50, sort="year_desc"
        )
        builder = _PublicationFacetsBuilder(
            sa_sync_conn, filters, filter_context(sa_sync_conn, filters)
        )
        pivot = StatsQueries(sa_sync_conn).pivot(
            measure="publication_count", groups=[], filters=filters
        )

        assert listed.total == 2
        assert sum(o.count for o in builder._facet_years()) == 2
        assert pivot.rows == [{"value": 2}]

    def test_lab_facet_counts_within_the_perimeter(self, sa_sync_conn):
        """La facette des laboratoires écarte le filtre laboratoire : elle part du périmètre."""
        lab = self._seed(sa_sync_conn)
        filters = PublicationFilters(lab_ids=[lab])
        builder = _PublicationFacetsBuilder(
            sa_sync_conn, filters, filter_context(sa_sync_conn, filters)
        )

        labs, _ = builder._facet_labs()
        assert [(o.value, o.count) for o in labs] == [(str(lab), 1)]


class TestLaboratoryTypes:
    """La clé `laboratory_types` définit les types de structure traités comme laboratoires : facette, décompte « Sans laboratoire » et colonne de la liste."""

    def _seed(self, conn):
        institute = insert_structure(conn, "INST", structure_type="admin")
        _attach(conn, insert_publication(conn, in_perimeter=True), institute)
        return institute

    def _facet(self, conn):
        filters = PublicationFilters()
        return _PublicationFacetsBuilder(conn, filters, filter_context(conn, filters))._facet_labs()

    def _labs_column(self, conn):
        res = publications_queries(conn).list_publications(
            filters=PublicationFilters(), page=1, per_page=50, sort="year_desc"
        )
        return [[lab.label for lab in p.lab_items or []] for p in res.publications]

    def test_structure_outside_the_types_is_not_a_laboratory(self, sa_sync_conn):
        self._seed(sa_sync_conn)
        set_config(sa_sync_conn, LABORATORY_TYPES_KEY, ["labo"])

        assert self._facet(sa_sync_conn) == ([], 1)
        assert self._labs_column(sa_sync_conn) == [[]]

    def test_structure_of_a_listed_type_is_a_laboratory(self, sa_sync_conn):
        institute = self._seed(sa_sync_conn)
        set_config(sa_sync_conn, LABORATORY_TYPES_KEY, ["labo", "admin"])

        labs, no_lab_count = self._facet(sa_sync_conn)
        assert [(o.value, o.count) for o in labs] == [(str(institute), 1)]
        assert no_lab_count == 0
        assert self._labs_column(sa_sync_conn) == [["INST"]]


class TestHalStatusNeedsASingleLab:
    def test_facets_ignore_hal_status_with_two_labs(self, sa_sync_conn):
        labs = [insert_structure(sa_sync_conn, code) for code in ("LAB-A", "LAB-B")]
        for lab in labs:
            _attach(sa_sync_conn, insert_publication(sa_sync_conn, in_perimeter=True), lab)
        filters = PublicationFilters(lab_ids=labs, hal_status_values=["ok"])
        builder = _PublicationFacetsBuilder(
            sa_sync_conn, filters, filter_context(sa_sync_conn, filters)
        )

        assert sum(o.count for o in builder._facet_years()) == 2


class TestExcludedPersonLab:
    """La contribution d'une personne exclue ne rattache pas sa publication au laboratoire de cette contribution."""

    def test_lab_of_excluded_person_drops_the_publication(self, sa_sync_conn):
        lab_excluded, lab_kept = (
            insert_structure(sa_sync_conn, code) for code in ("LAB-EXCLUE", "LAB-RETENUE")
        )
        publication = insert_publication(sa_sync_conn, "Copublication")
        for exclusion, lab in (("out_of_perimeter", lab_excluded), (None, lab_kept)):
            person = insert_person(
                sa_sync_conn, "X", first_name="Y", exclusion=exclusion, normalizer="lower"
            )
            aid = insert_contribution(
                sa_sync_conn, publication, person_id=person, in_perimeter=True, roles=["author"]
            )
            add_contribution_structure(sa_sync_conn, aid, lab)

        def listed(lab):
            res = publications_queries(sa_sync_conn).list_publications(
                filters=PublicationFilters(lab_ids=[lab]),
                page=1,
                per_page=50,
                sort="year_desc",
            )
            return publication in {p.id for p in res.publications}

        assert not listed(lab_excluded)
        assert listed(lab_kept)


class TestPersonView:
    """Vue d'une personne : la liste lit la contribution de la personne. L'auteur d'une thèse est une contribution rattachée à une personne."""

    def _seed(self, conn):
        person, coauthor = (
            insert_person(conn, name, first_name="Y", normalizer="lower")
            for name in ("Focus", "Coauteur")
        )
        lab, coauthor_lab = (insert_structure(conn, code) for code in ("LAB-P", "LAB-C"))
        publication = insert_publication(conn, "Copublication")
        for author, author_lab in ((person, lab), (coauthor, coauthor_lab)):
            contribution = insert_contribution(
                conn, publication, person_id=author, in_perimeter=True, roles=["author"]
            )
            add_contribution_structure(conn, contribution, author_lab)
        conn.execute(
            text(
                "UPDATE contributions SET is_corresponding = TRUE"
                " WHERE publication_id = :p AND person_id = :person"
            ),
            {"p": publication, "person": person},
        )
        return person, lab, publication

    def _list(self, conn, **filters):
        return (
            publications_queries(conn)
            .list_publications(
                filters=PublicationFilters(**filters),
                page=1,
                per_page=50,
                sort="year_desc",
            )
            .publications
        )

    def test_item_reads_the_contribution_of_the_person(self, sa_sync_conn):
        person, lab, publication = self._seed(sa_sync_conn)

        [item] = self._list(sa_sync_conn, person_id=person)

        assert item.contribution_id == contribution_id_of(sa_sync_conn, publication, person)
        assert item.is_corresponding is True
        assert [i.id for i in item.lab_items or []] == [lab]

    def test_author_position_and_perimeter_filters_read_the_contribution(self, sa_sync_conn):
        person, _, publication = self._seed(sa_sync_conn)

        def by_position(*positions):
            return [
                p.id
                for p in self._list(sa_sync_conn, person_id=person, author_position=list(positions))
            ]

        assert by_position("corresponding") == [publication]
        assert by_position("other") == []
        assert by_position("corresponding", "other") == [publication]
        assert [p.id for p in self._list(sa_sync_conn, person_id=person, in_perimeter=["yes"])] == [
            publication
        ]

        builder = _PublicationFacetsBuilder(
            sa_sync_conn, PublicationFilters(person_id=person), FilterContext([], None)
        )
        assert {(o.value, o.count) for o in builder._facet_author_positions()} == {
            ("corresponding", 1),
            ("other", 0),
        }
        assert {(o.value, o.count) for o in builder._facet_in_perimeter()} == {
            ("yes", 1),
            ("no", 0),
        }

    def test_thesis_author_is_a_contribution_with_person(self, sa_sync_conn):
        """Une contribution d'auteur sans personne n'est pas l'auteur de la thèse."""
        author = insert_person(sa_sync_conn, "Doctorant", first_name="Y", normalizer="lower")
        lab = _lab(sa_sync_conn)
        thesis = insert_publication(sa_sync_conn, "These", doc_type="thesis")
        source_record = _source_record(sa_sync_conn, thesis, source="theses", source_id="2024X")
        orphan = insert_source_contribution(sa_sync_conn, source_record, roles=["author"])
        align_source_contributions(sa_sync_conn, thesis, [(orphan, source_record)])
        sa_sync_conn.execute(
            text("UPDATE contributions SET roles = ARRAY['author'] WHERE publication_id = :p"),
            {"p": thesis},
        )
        contribution = insert_contribution(
            sa_sync_conn, thesis, person_id=author, in_perimeter=True, roles=["author"]
        )
        add_contribution_structure(sa_sync_conn, contribution, lab)

        [item] = self._list(sa_sync_conn, lab_ids=[lab])

        assert item.thesis_author_person_id == author


class TestExportsRunTheirQueryBeforeStreaming:
    """Les exports renvoient des blocs, mais interrogent la base à l'appel.

    FastAPI referme la connexion de la requête avant d'envoyer le corps de la réponse. Un générateur lancerait la requête à la première itération, sur une connexion fermée. Le contenu doit donc rester lisible après la fermeture.

    Chaque test ouvre et ferme sa propre connexion sur le même engine : celle du fixture contient la transaction des autres tests.
    """

    def test_theses_export_survives_a_closed_connection(self, sa_sync_conn):
        with sa_sync_conn.engine.connect() as conn:
            chunks = publications_queries(conn).export_theses_csv(
                filters=PublicationFilters(doc_types=["thesis"]),
                sort="soutenance_desc",
                columns=[],
            )
        assert "Soutenance" in "".join(chunks)

    def test_publications_export_survives_a_closed_connection(self, sa_sync_conn):
        with sa_sync_conn.engine.connect() as conn:
            chunks = publications_queries(conn).export_publications_csv(
                filters=PublicationFilters(),
                sort="year_desc",
                columns=[],
            )
        assert "Titre" in "".join(chunks)


class TestLicense:
    """Filtre et facette de la licence de la version éditeur ; `none` désigne une publication sans licence."""

    def _seed(self, conn):
        lab = _lab(conn)
        cc_by = insert_publication(conn, "Licensed", in_perimeter=True)
        unlicensed = insert_publication(conn, "Unlicensed", in_perimeter=True)
        conn.execute(
            text("UPDATE publications SET license = 'cc-by' WHERE id = :id"), {"id": cc_by}
        )
        for publication in (cc_by, unlicensed):
            _attach(conn, publication, lab)
        return lab, cc_by, unlicensed

    def _ids(self, conn, lab, license):  # noqa: A002
        res = publications_queries(conn).list_publications(
            filters=PublicationFilters(lab_ids=[lab], license=license),
            page=1,
            per_page=50,
            sort="year_desc",
        )
        return {p.id: p.license for p in res.publications}

    def test_filter(self, sa_sync_conn):
        lab, cc_by, unlicensed = self._seed(sa_sync_conn)

        assert self._ids(sa_sync_conn, lab, ["cc-by"]) == {cc_by: "cc-by"}
        assert self._ids(sa_sync_conn, lab, ["none"]) == {unlicensed: None}
        assert self._ids(sa_sync_conn, lab, ["cc-by", "none"]).keys() == {cc_by, unlicensed}

    def test_facet_counts_and_labels(self, sa_sync_conn):
        lab, _, _ = self._seed(sa_sync_conn)

        builder = _PublicationFacetsBuilder(
            sa_sync_conn,
            PublicationFilters(lab_ids=[lab], license=["cc-by"]),
            FilterContext([], None),
        )
        facet = {(o.value, o.label, o.count) for o in builder._facet_licenses()}
        assert facet == {("cc-by", "CC BY", 1), ("none", "Aucune licence", 1)}


class TestDoiAgency:
    """Filtre et facette de l'agence d'enregistrement du DOI, lue par le préfixe dans `doi_prefixes`."""

    def _seed(self, conn):
        lab = _lab(conn)
        insert_doi_prefix(conn, "10.1", ra="Crossref")
        insert_doi_prefix(conn, "10.2", ra="DataCite")
        insert_doi_prefix(conn, "10.3", ra="mEDRA")
        publications = {
            "crossref": insert_publication(conn, "Crossref", doi="10.1/a"),
            "datacite": insert_publication(conn, "DataCite", doi="10.2/a"),
            "medra": insert_publication(conn, "mEDRA", doi="10.3/a"),
            "unresolved": insert_publication(conn, "Préfixe inconnu", doi="10.4/a"),
            "none": insert_publication(conn, "Sans DOI"),
        }
        for publication in publications.values():
            _attach(conn, publication, lab)
        return lab, publications

    def _ids(self, conn, lab, doi_agency):
        res = publications_queries(conn).list_publications(
            filters=PublicationFilters(lab_ids=[lab], doi_agency=doi_agency),
            page=1,
            per_page=50,
            sort="year_desc",
        )
        return {p.id for p in res.publications}

    def test_filter(self, sa_sync_conn):
        lab, publications = self._seed(sa_sync_conn)

        assert self._ids(sa_sync_conn, lab, ["crossref"]) == {publications["crossref"]}
        assert self._ids(sa_sync_conn, lab, ["datacite"]) == {publications["datacite"]}
        assert self._ids(sa_sync_conn, lab, ["other"]) == {
            publications["medra"],
            publications["unresolved"],
        }
        assert self._ids(sa_sync_conn, lab, ["none"]) == {publications["none"]}
        assert self._ids(sa_sync_conn, lab, ["crossref", "none"]) == {
            publications["crossref"],
            publications["none"],
        }

    def test_facet_counts_and_labels(self, sa_sync_conn):
        lab, _ = self._seed(sa_sync_conn)

        builder = _PublicationFacetsBuilder(
            sa_sync_conn,
            PublicationFilters(lab_ids=[lab], doi_agency=["crossref"]),
            FilterContext([], None),
        )
        assert [(o.value, o.label, o.count) for o in builder._facet_doi_agencies()] == [
            ("crossref", "Crossref", 1),
            ("datacite", "DataCite", 1),
            ("other", "Autre", 2),
            ("none", "Pas de DOI", 1),
        ]


def test_le_lien_d_acces_suit_la_meilleure_copie_et_le_statut(sa_sync_conn):
    lab = _lab(sa_sync_conn)
    deposited = insert_publication(sa_sync_conn, "Deposited", oa_status="green")
    gold = insert_publication(sa_sync_conn, "Gold", oa_status="gold", doi="10.1/gold")
    embargoed = insert_publication(sa_sync_conn, "Embargoed", oa_status="embargoed")
    sa_sync_conn.execute(
        text(
            "UPDATE publications SET best_copy_url = 'https://hal.science/hal-1' WHERE id = ANY(:ids)"
        ),
        {"ids": [deposited, embargoed]},
    )
    for publication in (deposited, gold, embargoed):
        _attach(sa_sync_conn, publication, lab)

    res = publications_queries(sa_sync_conn).list_publications(
        filters=PublicationFilters(lab_ids=[lab]), page=1, per_page=50, sort="year_desc"
    )

    assert {p.id: p.access_url for p in res.publications} == {
        deposited: "https://hal.science/hal-1",
        gold: "https://doi.org/10.1/gold",
        embargoed: None,
    }
