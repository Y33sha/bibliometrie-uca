"""Tests d'intégration pour `infrastructure.read_models.publications.list`."""

from functools import partial

from sqlalchemy import text

from infrastructure.read_models.publications.facets import _PublicationFacetsBuilder
from infrastructure.read_models.publications.filtering import FilterContext, filter_context
from infrastructure.read_models.publications.models import PublicationFilters
from infrastructure.read_models.stats.queries import StatsQueries
from tests.integration.helpers.alignment import align_source_contributions
from tests.integration.helpers.contributions import contribution_id_of, insert_contribution
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.read_models import publications_queries
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record
from tests.integration.helpers.structures import add_contribution_structure, insert_structure
from tests.integration.helpers.subjects import insert_publication_subject, insert_subject

# Laboratoire « LAB ».
_lab = partial(insert_structure, code="LAB")

# Enregistrement source de titre « T ».
_source_record = partial(insert_source_record, title="T")


def _attach(conn, publication_id, lab_id):
    """Contribution reliant la publication à un labo par la vue `contribution_structures`, semée par la chaîne source minimale."""
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
        """Une publi dont le titre ne contient pas le terme mais qui est
        annotée par un sujet matchant doit remonter dans les résultats."""
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
        """Les publis dont le titre matche remontent avant celles qui ne
        matchent que via un sujet — quitte à casser l'ordre par défaut."""
        lab = _lab(sa_sync_conn)
        # Titre contient "quantum"
        title_match = insert_publication(sa_sync_conn, "Quantum entanglement basics")
        # Titre ne contient pas "quantum", mais sujet associé oui
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
        """Les accents ne doivent pas bloquer le match (ILIKE + unaccent)."""
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
        """Régression : les comptes de facettes suivent la recherche titre, pas
        seulement les autres filtres (la facette doit refléter le tableau)."""
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
    """Régression : une publi avec plusieurs entrées HAL (cas réel ~764 en
    base) ne doit pas tomber dans le filtre `hors_collection` dès qu'au moins
    une de ses entrées HAL contient la collection du labo. Et le champ
    `hal_collections` renvoyé doit fusionner les collections des entrées."""

    def test_publication_in_collection_via_one_hal_entry_is_not_hors_collection(self, sa_sync_conn):
        """Publi avec 2 dépôts HAL : l'un dans la collection du labo, l'autre
        non. Doit être exclue du filtre `hors_collection`."""
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

    def test_hal_collections_unions_all_hal_entries(self, sa_sync_conn):
        """`hal_collections` renvoyé par l'API = union des collections des
        entrées HAL (pas une entrée arbitraire prise au hasard)."""
        lab = _lab(sa_sync_conn, hal_collection="CMH")
        publication = insert_publication(sa_sync_conn, "Two HAL deposits")
        _attach(sa_sync_conn, publication, lab)
        _source_record(
            sa_sync_conn, publication, source_id="hal-CMH", hal_collections=["CMH", "AO-DROIT"]
        )
        _source_record(
            sa_sync_conn, publication, source_id="hal-PAU", hal_collections=["UPPA-DROIT"]
        )

        res = publications_queries(sa_sync_conn).list_publications(
            filters=PublicationFilters(lab_ids=[lab]),
            page=1,
            per_page=50,
            sort="year_desc",
        )
        match = next(p for p in res.publications if p.id == publication)
        assert set(match.hal_collections or []) == {"CMH", "AO-DROIT", "UPPA-DROIT"}

    def test_publication_only_outside_collection_is_hors_collection(self, sa_sync_conn):
        """Cas symétrique : si aucune entrée HAL n'est dans la collection,
        la publi tombe bien dans `hors_collection`."""
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
        """Labo dont la collection HAL est absente : le filtre `ok` (en collection + accès
        ouvert) rend zéro publication."""
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
    """Export CSV des thèses : la boucle de rendu lit chaque colonne du SELECT, donc un test avec données garde le contrat SQL du CSV et son projeté d'accord."""

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
            )
        )

        header, line = csv_text.lstrip("﻿").splitlines()[:2]
        assert header.split(",")[-1] == "Accès"
        assert line.split(",")[-1] == "https://theses.hal.science/tel-1"


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
    """La contribution source d'une personne exclue ne rattache pas sa publication au laboratoire de cette contribution source."""

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
    """Page personne : les contributions sont les contributions rattachées à une personne."""

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

    def test_corresponding_and_perimeter_filters_read_the_contribution(self, sa_sync_conn):
        person, _, publication = self._seed(sa_sync_conn)

        assert [
            p.id for p in self._list(sa_sync_conn, person_id=person, is_corresponding=["yes"])
        ] == [publication]
        assert self._list(sa_sync_conn, person_id=person, is_corresponding=["no"]) == []
        assert [p.id for p in self._list(sa_sync_conn, person_id=person, in_perimeter=["yes"])] == [
            publication
        ]

        builder = _PublicationFacetsBuilder(
            sa_sync_conn, PublicationFilters(person_id=person), FilterContext([], None)
        )
        assert {(o.value, o.count) for o in builder._facet_corresponding()} == {
            ("yes", 1),
            ("no", 0),
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
    """Les exports rendent des blocs, mais interrogent la base à l'appel.

    Non-régression sur une subtilité qui casserait en production sans faire échouer un test naïf : FastAPI referme la connexion de la requête *avant* d'envoyer le corps de la réponse. Si ces méthodes devenaient des générateurs, la requête ne partirait qu'à la première itération, c'est-à-dire une fois la connexion fermée. Le contenu doit donc rester lisible après la fermeture.

    Chaque test ouvre sa propre connexion sur le même engine, et la ferme : celle du fixture porte la transaction des autres tests.
    """

    def test_theses_export_survives_a_closed_connection(self, sa_sync_conn):
        with sa_sync_conn.engine.connect() as conn:
            chunks = publications_queries(conn).export_theses_csv(
                filters=PublicationFilters(doc_types=["thesis"]),
                sort="soutenance_desc",
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
