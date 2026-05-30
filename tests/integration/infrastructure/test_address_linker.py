"""Tests de caractérisation pour `infrastructure.repositories.address_linker.PgAddressLinker`."""

from sqlalchemy import text

from infrastructure.repositories.address_linker import PgAddressLinker


def _create_authorship_stub(conn):
    """Crée une publication + source_publication + source_authorship minimaux
    pour pouvoir rattacher une adresse. Retourne source_authorship_id."""
    pub_id = conn.execute(
        text("""
            INSERT INTO publications (title, title_normalized, pub_year, doc_type)
            VALUES ('X', 'x', 2024, 'article') RETURNING id
        """)
    ).scalar_one()
    sd_id = conn.execute(
        text("""
            INSERT INTO source_publications (source, source_id, title, pub_year, publication_id)
            VALUES ('hal', 'hal-X', 'X', 2024, :pub_id) RETURNING id
        """),
        {"pub_id": pub_id},
    ).scalar_one()
    return conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position)
            VALUES ('hal', :sd_id, 0) RETURNING id
        """),
        {"sd_id": sd_id},
    ).scalar_one()


class TestLinkAddresses:
    """Garantit que link() fonctionne, y compris sur le chemin fallback
    (SELECT après ON CONFLICT DO NOTHING).
    """

    def test_reuses_existing_address_via_fallback_path(self, sa_sync_conn):
        """Si l'adresse existe déjà, la branche fallback est exercée :
        ON CONFLICT DO NOTHING ne retourne rien, donc SELECT par md5
        doit pouvoir lire l'id."""
        sa_id = _create_authorship_stub(sa_sync_conn)

        # Pré-insérer l'adresse pour forcer ON CONFLICT DO NOTHING
        existing_id = sa_sync_conn.execute(
            text("""
                INSERT INTO addresses (raw_text, normalized_text)
                VALUES (:raw, :norm) RETURNING id
            """),
            {"raw": "Université Clermont Auvergne", "norm": "universite clermont auvergne"},
        ).scalar_one()

        linker = PgAddressLinker()
        links = linker.link(sa_sync_conn, sa_id, ["Université Clermont Auvergne"])
        assert links == 1

        # Vérifier que le lien pointe bien sur l'adresse pré-existante
        addr_id = sa_sync_conn.execute(
            text("""
                SELECT address_id FROM source_authorship_addresses
                WHERE source_authorship_id = :sa_id
            """),
            {"sa_id": sa_id},
        ).scalar_one()
        assert addr_id == existing_id

    def test_suggested_countries_written_when_unresolved(self, sa_sync_conn):
        """`suggested_countries` est écrit sur une adresse sans pays ni suggestion,
        sans toucher `countries` (autorité)."""
        sa_id = _create_authorship_stub(sa_sync_conn)
        linker = PgAddressLinker()
        linker.link(sa_sync_conn, sa_id, ["Inst One, Some City"], suggested_countries=["FR"])
        row = sa_sync_conn.execute(
            text("""
                SELECT a.countries, a.suggested_countries
                FROM source_authorship_addresses saa
                JOIN addresses a ON a.id = saa.address_id
                WHERE saa.source_authorship_id = :sa_id
            """),
            {"sa_id": sa_id},
        ).one()
        assert row.countries is None
        assert [c.strip() for c in row.suggested_countries] == ["FR"]

    def test_suggested_countries_skipped_when_already_resolved(self, sa_sync_conn):
        """Si l'adresse a déjà un `countries` (autorité), aucune suggestion n'est posée."""
        sa_id = _create_authorship_stub(sa_sync_conn)
        addr_id = sa_sync_conn.execute(
            text("""
                INSERT INTO addresses (raw_text, normalized_text, countries)
                VALUES (:r, :n, ARRAY['US']::char(2)[]) RETURNING id
            """),
            {"r": "Resolved Place", "n": "resolved place"},
        ).scalar_one()
        linker = PgAddressLinker()
        linker.link(sa_sync_conn, sa_id, ["Resolved Place"], suggested_countries=["FR"])
        row = sa_sync_conn.execute(
            text("SELECT countries, suggested_countries FROM addresses WHERE id = :id"),
            {"id": addr_id},
        ).one()
        assert [c.strip() for c in row.countries] == ["US"]
        assert row.suggested_countries is None
