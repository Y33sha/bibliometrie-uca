"""Tests de caractérisation pour `infrastructure.addresses.PgAddressLinker`."""

from psycopg2.extras import RealDictCursor

from infrastructure.addresses import PgAddressLinker


def _create_authorship_stub(db):
    """Crée une publication + source_publication + source_authorship minimaux
    pour pouvoir rattacher une adresse. Retourne source_authorship_id."""
    db.execute(
        """
        INSERT INTO publications (title, title_normalized, pub_year, doc_type)
        VALUES ('X', 'x', 2024, 'article') RETURNING id
        """
    )
    pub_id = db.fetchone()["id"]
    db.execute(
        """
        INSERT INTO source_publications (source, source_id, title, pub_year, publication_id)
        VALUES ('hal', 'hal-X', 'X', 2024, %s) RETURNING id
        """,
        (pub_id,),
    )
    sd_id = db.fetchone()["id"]
    db.execute(
        """
        INSERT INTO source_persons (source, source_id, full_name)
        VALUES ('hal', 'sp-X', 'Durand') RETURNING id
        """
    )
    sp_id = db.fetchone()["id"]
    db.execute(
        """
        INSERT INTO source_authorships
            (source, source_publication_id, source_person_id, author_position)
        VALUES ('hal', %s, %s, 0) RETURNING id
        """,
        (sd_id, sp_id),
    )
    return db.fetchone()["id"]


class TestLinkAddressesRealDictCursor:
    """Garantit que link() fonctionne avec un RealDictCursor, y compris
    sur le chemin fallback (SELECT après ON CONFLICT DO NOTHING).

    Régression d'un bug : `row[0]` sur un RealDictRow lève KeyError.
    """

    def test_reuses_existing_address_via_fallback_path(self, db):
        """Si l'adresse existe déjà, la branche fallback est exercée :
        ON CONFLICT DO NOTHING ne retourne rien, donc SELECT par md5
        doit pouvoir lire l'id même sur un curseur RealDictCursor."""
        sa_id = _create_authorship_stub(db)

        # Pré-insérer l'adresse pour forcer ON CONFLICT DO NOTHING
        db.execute(
            """
            INSERT INTO addresses (raw_text, normalized_text)
            VALUES (%s, %s) RETURNING id
            """,
            ("Université Clermont Auvergne", "universite clermont auvergne"),
        )
        existing_id = db.fetchone()["id"]

        # Utiliser un RealDictCursor comme en pipeline openalex/scanr
        dict_cur = db.connection.cursor(cursor_factory=RealDictCursor)
        try:
            linker = PgAddressLinker()
            links = linker.link(dict_cur, sa_id, ["Université Clermont Auvergne"])
            assert links == 1

            # Vérifier que le lien pointe bien sur l'adresse pré-existante
            db.execute(
                """
                SELECT address_id FROM source_authorship_addresses
                WHERE source_authorship_id = %s
                """,
                (sa_id,),
            )
            row = db.fetchone()
            assert row["address_id"] == existing_id
        finally:
            dict_cur.close()
