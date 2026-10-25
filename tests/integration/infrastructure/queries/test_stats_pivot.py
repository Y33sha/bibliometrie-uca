"""Tests d'intégration du moteur de pivot (`infrastructure.read_models.stats.pivot`)."""

from sqlalchemy import text

from application.ports.read_models.stats_queries import StatsFilters
from infrastructure.read_models.stats.pivot import run_pivot
from tests.integration.helpers.publications import insert_apc_payment, insert_publication
from tests.integration.helpers.rors import insert_author, insert_ror_tree, refresh_publication_rors
from tests.integration.helpers.structures import insert_structure


def _piv(conn, measure, groups, doc_types=("article", "review")):
    return run_pivot(
        conn,
        measure=measure,
        groups=list(groups),
        perimeter_structure_ids=[],
        filters=StatsFilters(doc_types=list(doc_types)),
    )


class TestPivotEngine:
    def test_oa_access_buckets(self, sa_sync_conn):
        insert_publication(
            sa_sync_conn, in_perimeter=True, oa_status="gold", sources=["hal", "openalex"]
        )
        insert_publication(sa_sync_conn, in_perimeter=True, oa_status="closed", sources=["hal"])
        insert_publication(
            sa_sync_conn,
            in_perimeter=True,
            oa_status="gold",
            sources=["openalex"],
            publication_year=2023,
        )

        res = _piv(sa_sync_conn, "publication_count", ["oa_access"])
        by_access = {r["oa_access"]: r["value"] for r in res.rows}
        assert by_access == {"ouvert": 2, "ferme": 1}

    def test_doc_type_grouped_expands_publications(self, sa_sync_conn):
        # Les publications au sens strict se ventilent par type fin ; les autres familles restent
        # agrégées sous leur clé de famille.
        insert_publication(
            sa_sync_conn, in_perimeter=True, oa_status="gold", sources=["hal"], doc_type="article"
        )  # → article
        insert_publication(
            sa_sync_conn, in_perimeter=True, oa_status="gold", sources=["hal"], doc_type="book"
        )  # → book
        insert_publication(
            sa_sync_conn, in_perimeter=True, oa_status="closed", sources=["hal"], doc_type="thesis"
        )  # → theses

        res = _piv(sa_sync_conn, "publication_count", ["doc_type_grouped"], doc_types=())
        by_type = {r["doc_type_grouped"]: r["value"] for r in res.rows}
        assert by_type == {"article": 1, "book": 1, "theses": 1}

    def test_group_by_lab_executes(self, sa_sync_conn):
        # Le groupement par laboratoire compose une requête valide (jointures de rattachement).
        # Smoke test : on vérifie que la requête s'exécute et renvoie la forme attendue, sans
        # dépendre des matviews de rattachement peuplées.
        insert_publication(sa_sync_conn, in_perimeter=True, oa_status="gold", sources=["hal"])
        res = _piv(sa_sync_conn, "publication_count", ["lab"])
        assert isinstance(res.rows, list)
        assert res.groups == ["lab"]

    def test_group_by_publisher_and_serial_execute(self, sa_sync_conn):
        # Éditeur et revue composent des requêtes valides (jointures internes). Smoke test : la
        # requête s'exécute et renvoie la forme attendue, sans dépendre de données peuplées.
        insert_publication(sa_sync_conn, in_perimeter=True, oa_status="gold", sources=["hal"])
        for dim in ("publisher", "serial"):
            res = _piv(sa_sync_conn, "publication_count", [dim])
            assert res.groups == [dim]

    def test_zero_groups_returns_single_total(self, sa_sync_conn):
        insert_publication(sa_sync_conn, in_perimeter=True, oa_status="gold", sources=["hal"])
        insert_publication(sa_sync_conn, in_perimeter=True, oa_status="closed", sources=["hal"])

        res = _piv(sa_sync_conn, "publication_count", [])
        assert res.rows == [{"value": 2}]

    def test_doc_type_is_a_filter_not_hardcoded(self, sa_sync_conn):
        # Un type hors article/review est exclu par le filtre, pas par le périmètre du moteur.
        insert_publication(
            sa_sync_conn, in_perimeter=True, oa_status="gold", sources=["hal"], doc_type="article"
        )
        insert_publication(
            sa_sync_conn, in_perimeter=True, oa_status="gold", sources=["hal"], doc_type="book"
        )

        restricted = _piv(sa_sync_conn, "publication_count", [], doc_types=("article", "review"))
        assert restricted.rows == [{"value": 1}]
        unrestricted = _piv(sa_sync_conn, "publication_count", [], doc_types=())
        assert unrestricted.rows == [{"value": 2}]


class TestLicense:
    def test_group_and_filter_by_license(self, sa_sync_conn):
        licensed = insert_publication(sa_sync_conn, in_perimeter=True, oa_status="gold")
        insert_publication(sa_sync_conn, in_perimeter=True, oa_status="closed")
        sa_sync_conn.execute(
            text("UPDATE publications SET license = 'cc-by' WHERE id = :id"), {"id": licensed}
        )

        res = _piv(sa_sync_conn, "publication_count", ["license"], doc_types=())
        assert {r["license"]: r["value"] for r in res.rows} == {"cc-by": 1, "none": 1}

        filtered = run_pivot(
            sa_sync_conn,
            measure="publication_count",
            groups=[],
            perimeter_structure_ids=[],
            filters=StatsFilters(license=["none"]),
        )
        assert filtered.rows == [{"value": 1}]


class TestApcAmount:
    """Montant des APC : paiements imputés au budget d'une structure du périmètre, tous frais confondus."""

    def _seed(self, conn):
        inside = insert_structure(conn, "pivot_apc_inside", structure_type="universite")
        outside = insert_structure(conn, "pivot_apc_outside", structure_type="universite")
        paid = insert_publication(conn, in_perimeter=True, oa_status="gold", publication_year=2024)
        for amount, budget, oa_fee in (
            (100, inside, True),
            (50, inside, False),
            (1000, outside, True),
        ):
            insert_apc_payment(
                conn,
                publication_id=paid,
                amount_eur_ht=amount,
                budget_structure_id=budget,
                open_access_fee=oa_fee,
            )
        paid_elsewhere = insert_publication(
            conn, in_perimeter=True, oa_status="gold", publication_year=2024
        )
        insert_apc_payment(
            conn,
            publication_id=paid_elsewhere,
            amount_eur_ht=300,
            budget_structure_id=outside,
            open_access_fee=True,
        )
        insert_publication(conn, in_perimeter=True, oa_status="gold", publication_year=2023)
        return inside

    def _pivot(self, conn, inside, groups):
        return run_pivot(
            conn,
            measure="apc_amount",
            groups=list(groups),
            perimeter_structure_ids=[inside],
            filters=StatsFilters(),
        )

    def test_sums_only_institution_payments(self, sa_sync_conn):
        inside = self._seed(sa_sync_conn)

        assert self._pivot(sa_sync_conn, inside, []).rows == [{"value": 150.0}]

    def test_grouped_by_year(self, sa_sync_conn):
        inside = self._seed(sa_sync_conn)

        rows = self._pivot(sa_sync_conn, inside, ["year"]).rows
        assert {r["year"]: r["value"] for r in rows} == {2023: 0.0, 2024: 150.0}

    def test_apc_filter_keeps_institution_paid_publications(self, sa_sync_conn):
        inside = self._seed(sa_sync_conn)

        res = run_pivot(
            sa_sync_conn,
            measure="publication_count",
            groups=[],
            perimeter_structure_ids=[inside],
            filters=StatsFilters(has_apc=["yes"]),
        )
        assert res.rows == [{"value": 1}]


class TestPartner:
    def test_group_and_filter_by_partner(self, sa_sync_conn):
        """Un établissement compte les publications de ses laboratoires."""
        insert_ror_tree(sa_sync_conn)
        lab = insert_publication(sa_sync_conn, in_perimeter=True, oa_status="gold")
        insert_author(sa_sync_conn, lab, "W1", "0lab00001")
        other = insert_publication(sa_sync_conn, in_perimeter=True, oa_status="gold")
        insert_author(sa_sync_conn, other, "W2", "0ger00001")
        refresh_publication_rors(sa_sync_conn)

        res = _piv(sa_sync_conn, "publication_count", ["partner"])
        assert {r["partner"]: r["value"] for r in res.rows} == {
            "Université": 1,
            "Laboratoire": 1,
            "Labor": 1,
        }
        filtered = run_pivot(
            sa_sync_conn,
            measure="publication_count",
            groups=[],
            perimeter_structure_ids=[],
            filters=StatsFilters(partner_rors=["0univ0001"]),
        )
        assert filtered.rows == [{"value": 1}]
