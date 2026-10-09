"""Tests d'intégration pour `infrastructure.read_models.publications.list`."""

from functools import partial

from sqlalchemy import text

from application.ports.read_models.publications_queries import PublicationFilters
from infrastructure.read_models.publications.facets import _PublicationFacetsBuilder
from infrastructure.read_models.publications.list import (
    export_publications_csv,
    export_theses_csv,
    list_publications,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_publication
from tests.integration.helpers.structures import add_authorship_structure

# Notice de titre « T ».
_notice = partial(insert_source_publication, title="T")


def _create_lab(conn):
    row = conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type) "
            "VALUES ('LAB', 'LAB', 'labo'::structure_type) RETURNING id"
        )
    ).one()
    return row.id


def _attach(conn, pub_id, lab_id):
    """Authorship reliant la publi à un labo via la matview authorship_structures
    (semée par la chaîne source minimale)."""
    aid = conn.execute(
        text(
            "INSERT INTO authorships (publication_id, in_perimeter, roles) "
            "VALUES (:pid, TRUE, ARRAY['author']::text[]) RETURNING id"
        ),
        {"pid": pub_id},
    ).scalar_one()
    add_authorship_structure(conn, aid, lab_id)


def _create_subject(conn, label):
    row = conn.execute(
        text("INSERT INTO subjects (label) VALUES (:l) RETURNING id"),
        {"l": label},
    ).one()
    return row.id


def _link_subject(conn, pub_id, sid):
    conn.execute(
        text(
            "INSERT INTO publication_subjects (publication_id, subject_id, source) "
            "VALUES (:pid, :sid, 'hal')"
        ),
        {"pid": pub_id, "sid": sid},
    )


class TestSearch:
    def test_search_matches_title(self, sa_sync_conn):
        lab = _create_lab(sa_sync_conn)
        match = insert_publication(sa_sync_conn, "Quantum entanglement basics")
        other = insert_publication(sa_sync_conn, "Foo bar baz")
        _attach(sa_sync_conn, match, lab)
        _attach(sa_sync_conn, other, lab)

        res = list_publications(
            sa_sync_conn,
            filters=PublicationFilters(search="quantum", lab_ids=[lab]),
            perimeter_structure_ids=[],
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p.id for p in res.publications]
        assert match in ids and other not in ids

    def test_search_matches_subject_label(self, sa_sync_conn):
        """Une publi dont le titre ne contient pas le terme mais qui est
        annotée par un sujet matchant doit remonter dans les résultats."""
        lab = _create_lab(sa_sync_conn)
        pub = insert_publication(sa_sync_conn, "Foo bar baz")
        unrelated = insert_publication(sa_sync_conn, "Hello world")
        _attach(sa_sync_conn, pub, lab)
        _attach(sa_sync_conn, unrelated, lab)

        sid = _create_subject(sa_sync_conn, "Quantum mechanics")
        _link_subject(sa_sync_conn, pub, sid)

        res = list_publications(
            sa_sync_conn,
            filters=PublicationFilters(search="quantum", lab_ids=[lab]),
            perimeter_structure_ids=[],
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p.id for p in res.publications]
        assert pub in ids and unrelated not in ids

    def test_title_match_ranks_before_subject_only_match(self, sa_sync_conn):
        """Les publis dont le titre matche remontent avant celles qui ne
        matchent que via un sujet — quitte à casser l'ordre par défaut."""
        lab = _create_lab(sa_sync_conn)
        # Titre contient "quantum"
        title_match = insert_publication(sa_sync_conn, "Quantum entanglement basics")
        # Titre ne contient pas "quantum", mais sujet associé oui
        subject_match = insert_publication(sa_sync_conn, "Foo bar baz")
        _attach(sa_sync_conn, title_match, lab)
        _attach(sa_sync_conn, subject_match, lab)
        sid = _create_subject(sa_sync_conn, "Quantum mechanics")
        _link_subject(sa_sync_conn, subject_match, sid)

        res = list_publications(
            sa_sync_conn,
            filters=PublicationFilters(search="quantum", lab_ids=[lab]),
            perimeter_structure_ids=[],
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p.id for p in res.publications]
        assert ids.index(title_match) < ids.index(subject_match)

    def test_search_unaccented_matches_accented_label(self, sa_sync_conn):
        """Les accents ne doivent pas bloquer le match (ILIKE + unaccent)."""
        lab = _create_lab(sa_sync_conn)
        pub = insert_publication(sa_sync_conn, "Foo")
        _attach(sa_sync_conn, pub, lab)
        sid = _create_subject(sa_sync_conn, "Économétrie")
        _link_subject(sa_sync_conn, pub, sid)

        res = list_publications(
            sa_sync_conn,
            filters=PublicationFilters(search="econometrie", lab_ids=[lab]),
            perimeter_structure_ids=[],
            page=1,
            per_page=50,
            sort="year_desc",
        )
        ids = [p.id for p in res.publications]
        assert pub in ids

    def test_facets_respect_search(self, sa_sync_conn):
        """Régression : les comptes de facettes suivent la recherche titre, pas
        seulement les autres filtres (la facette doit refléter le tableau)."""
        lab = _create_lab(sa_sync_conn)
        for title in ("quantum gravity", "classical mechanics"):
            pid = insert_publication(sa_sync_conn, title=title)
            _attach(sa_sync_conn, pid, lab)
            sa_sync_conn.execute(
                text("UPDATE publications SET in_perimeter = TRUE WHERE id = :id"), {"id": pid}
            )

        def years_total(search: str) -> int:
            builder = _PublicationFacetsBuilder(
                sa_sync_conn, PublicationFilters(search=search, lab_ids=[lab]), []
            )
            return sum(r.count for r in builder._facet_years())

        assert years_total("") == 2
        assert years_total("quantum") == 1


class TestHalStatusMultipleHalEntries:
    """Régression : une publi avec plusieurs entrées HAL (cas réel ~764 en
    base) ne doit pas tomber dans le filtre `hors_collection` dès qu'au moins
    une de ses entrées HAL contient la collection du labo. Et le champ
    `hal_collections` renvoyé doit fusionner les collections des entrées."""

    @staticmethod
    def _make_lab_with_collection(conn, collection: str) -> int:
        row = conn.execute(
            text(
                "INSERT INTO structures (code, name, structure_type, hal_collection) "
                "VALUES ('LAB', 'LAB', 'labo'::structure_type, :col) RETURNING id"
            ),
            {"col": collection},
        ).one()
        return row.id

    def test_pub_in_collection_via_one_hal_entry_is_not_hors_collection(self, sa_sync_conn):
        """Publi avec 2 dépôts HAL : l'un dans la collection du labo, l'autre
        non. Doit être exclue du filtre `hors_collection`."""
        lab = self._make_lab_with_collection(sa_sync_conn, "CMH")
        pub = insert_publication(sa_sync_conn, "Two HAL deposits")
        _attach(sa_sync_conn, pub, lab)
        _notice(sa_sync_conn, pub, source_id="hal-CMH", hal_collections=["CMH", "AO-DROIT"])
        _notice(sa_sync_conn, pub, source_id="hal-PAU", hal_collections=["UPPA-DROIT", "SHS"])
        sa_sync_conn.execute(
            text("UPDATE publications SET oa_status = 'gold'::oa_type WHERE id = :id"),
            {"id": pub},
        )

        res = list_publications(
            sa_sync_conn,
            filters=PublicationFilters(lab_ids=[lab], hal_status_values=["hors_collection"]),
            perimeter_structure_ids=[],
            page=1,
            per_page=50,
            sort="year_desc",
        )
        assert pub not in [p.id for p in res.publications]

    def test_hal_collections_unions_all_hal_entries(self, sa_sync_conn):
        """`hal_collections` renvoyé par l'API = union des collections des
        entrées HAL (pas une entrée arbitraire prise au hasard)."""
        lab = self._make_lab_with_collection(sa_sync_conn, "CMH")
        pub = insert_publication(sa_sync_conn, "Two HAL deposits")
        _attach(sa_sync_conn, pub, lab)
        _notice(sa_sync_conn, pub, source_id="hal-CMH", hal_collections=["CMH", "AO-DROIT"])
        _notice(sa_sync_conn, pub, source_id="hal-PAU", hal_collections=["UPPA-DROIT"])

        res = list_publications(
            sa_sync_conn,
            filters=PublicationFilters(lab_ids=[lab]),
            perimeter_structure_ids=[],
            page=1,
            per_page=50,
            sort="year_desc",
        )
        match = next(p for p in res.publications if p.id == pub)
        assert set(match.hal_collections or []) == {"CMH", "AO-DROIT", "UPPA-DROIT"}

    def test_pub_only_outside_collection_is_hors_collection(self, sa_sync_conn):
        """Cas symétrique : si aucune entrée HAL n'est dans la collection,
        la publi tombe bien dans `hors_collection`."""
        lab = self._make_lab_with_collection(sa_sync_conn, "CMH")
        pub = insert_publication(sa_sync_conn, "Outside only")
        _attach(sa_sync_conn, pub, lab)
        _notice(sa_sync_conn, pub, source_id="hal-PAU", hal_collections=["UPPA-DROIT"])

        res = list_publications(
            sa_sync_conn,
            filters=PublicationFilters(lab_ids=[lab], hal_status_values=["hors_collection"]),
            perimeter_structure_ids=[],
            page=1,
            per_page=50,
            sort="year_desc",
        )
        assert pub in [p.id for p in res.publications]

    def test_ok_without_declared_collection_matches_nothing(self, sa_sync_conn):
        """Labo dont la collection HAL est absente : le filtre `ok` (en collection + accès
        ouvert) rend zéro publication."""
        lab = sa_sync_conn.execute(
            text(
                "INSERT INTO structures (code, name, structure_type) "
                "VALUES ('LABNC', 'LABNC', 'labo'::structure_type) RETURNING id"
            )
        ).scalar_one()
        pub = insert_publication(sa_sync_conn, "Open in HAL")
        _attach(sa_sync_conn, pub, lab)
        _notice(sa_sync_conn, pub, source_id="hal-x", hal_collections=["SOME-COL"])
        sa_sync_conn.execute(
            text("UPDATE publications SET oa_status = 'gold'::oa_type WHERE id = :id"),
            {"id": pub},
        )

        res = list_publications(
            sa_sync_conn,
            filters=PublicationFilters(lab_ids=[lab], hal_status_values=["ok"]),
            perimeter_structure_ids=[],
            page=1,
            per_page=50,
            sort="year_desc",
        )
        assert res.publications == []


class TestThesesExport:
    """Export CSV des thèses : la boucle de rendu lit chaque colonne du SELECT, donc un test avec données garde le contrat SQL du CSV et son projeté d'accord."""

    def test_renders_a_thesis_with_each_source_url(self, sa_sync_conn):
        lab = _create_lab(sa_sync_conn)
        pub = sa_sync_conn.execute(
            text(
                "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
                "VALUES ('Ma these', 'ma these', 2024, 'thesis'::doc_type) RETURNING id"
            )
        ).scalar_one()
        _attach(sa_sync_conn, pub, lab)
        for src, sid in (
            ("hal", "hal-1"),
            ("openalex", "W1"),
            ("scanr", "sc-1"),
            ("theses", "2024NNT"),
        ):
            _notice(sa_sync_conn, pub, source=src, source_id=sid)

        csv_text = "".join(
            export_theses_csv(
                sa_sync_conn,
                filters=PublicationFilters(lab_ids=[lab], doc_types=["thesis"]),
                perimeter_structure_ids=[],
                sort="soutenance_desc",
            )
        )

        line = next(row for row in csv_text.splitlines() if "Ma these" in row)
        assert "hal.science/hal-1" in line
        assert "openalex.org/W1" in line
        assert "scanr.enseignementsup-recherche.gouv.fr/publications/sc-1" in line
        assert "theses.fr/2024NNT" in line


class TestExcludedPersonLab:
    """La signature d'une personne exclue ne rattache pas sa publication au laboratoire de cette signature."""

    def test_lab_of_excluded_person_drops_the_publication(self, sa_sync_conn):
        lab_excluded, lab_kept = (
            sa_sync_conn.execute(
                text(
                    "INSERT INTO structures (code, name, structure_type) "
                    "VALUES (:c, :c, 'labo'::structure_type) RETURNING id"
                ),
                {"c": code},
            ).scalar_one()
            for code in ("LAB-EXCLUE", "LAB-RETENUE")
        )
        pub = insert_publication(sa_sync_conn, "Copublication")
        for exclusion, lab in (("out_of_perimeter", lab_excluded), (None, lab_kept)):
            person = sa_sync_conn.execute(
                text(
                    "INSERT INTO persons (last_name, first_name, last_name_normalized, "
                    "first_name_normalized, exclusion) "
                    "VALUES ('X', 'Y', 'x', 'y', CAST(:e AS person_exclusion)) RETURNING id"
                ),
                {"e": exclusion},
            ).scalar_one()
            aid = sa_sync_conn.execute(
                text(
                    "INSERT INTO authorships (publication_id, person_id, in_perimeter, roles) "
                    "VALUES (:pub, :pe, TRUE, ARRAY['author']::text[]) RETURNING id"
                ),
                {"pub": pub, "pe": person},
            ).scalar_one()
            add_authorship_structure(sa_sync_conn, aid, lab)

        def listed(lab):
            res = list_publications(
                sa_sync_conn,
                filters=PublicationFilters(lab_ids=[lab]),
                perimeter_structure_ids=[],
                page=1,
                per_page=50,
                sort="year_desc",
            )
            return pub in {p.id for p in res.publications}

        assert not listed(lab_excluded)
        assert listed(lab_kept)


class TestExportsRunTheirQueryBeforeStreaming:
    """Les exports rendent des blocs, mais interrogent la base à l'appel.

    Non-régression sur une subtilité qui casserait en production sans faire échouer un test naïf : FastAPI referme la connexion de la requête *avant* d'envoyer le corps de la réponse. Si ces fonctions devenaient des générateurs, la requête ne partirait qu'à la première itération, c'est-à-dire une fois la connexion fermée. Le contenu doit donc rester lisible après la fermeture.

    Chaque test ouvre sa propre connexion sur le même engine, et la ferme : celle du fixture porte la transaction des autres tests.
    """

    def test_theses_export_survives_a_closed_connection(self, sa_sync_conn):
        with sa_sync_conn.engine.connect() as conn:
            chunks = export_theses_csv(
                conn,
                filters=PublicationFilters(doc_types=["thesis"]),
                perimeter_structure_ids=[],
                sort="soutenance_desc",
            )
        assert "Soutenance" in "".join(chunks)

    def test_publications_export_survives_a_closed_connection(self, sa_sync_conn):
        with sa_sync_conn.engine.connect() as conn:
            chunks = export_publications_csv(
                conn,
                filters=PublicationFilters(),
                perimeter_structure_ids=[],
                sort="year_desc",
                columns=[],
            )
        assert "Titre" in "".join(chunks)
