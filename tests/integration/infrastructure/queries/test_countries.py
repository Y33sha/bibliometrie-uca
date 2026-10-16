"""Tests d'intégration pour `pipeline.transformation.structures.countries.countries_queries`."""

from sqlalchemy import text

from domain.country_detection import CountryDetectionMethod
from pipeline.transformation.structures.countries.countries_queries import CountryQueries
from tests.integration.helpers.addresses import ensure_country, insert_address
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import (
    insert_signature,
    insert_signature_address,
    insert_source_publication,
)

_Q = CountryQueries()


def _resolve(conn, address_id: int, codes: list[str]) -> None:
    """Donne à l'adresse le candidat `country_name` `codes`, puis la résout."""
    for code in codes:
        ensure_country(conn, code)
    _Q.insert_candidates(conn, CountryDetectionMethod.COUNTRY_NAME, [(address_id, codes)])
    _Q.resolve_address_countries(conn, [address_id])


def _candidates(conn, address_id: int) -> set[tuple[str, str]]:
    return {
        (r.country_code, r.method)
        for r in conn.execute(
            text(
                "SELECT country_code, method::text AS method FROM address_country_candidates"
                " WHERE address_id = :a"
            ),
            {"a": address_id},
        )
    }


def _field(conn, address_id: int, column: str):
    return conn.execute(
        text(f"SELECT {column} FROM addresses WHERE id = :id"), {"id": address_id}
    ).scalar_one()


class TestCandidatesAndResolution:
    def test_un_candidat_marque_l_adresse_et_ignore_un_code_inconnu(self, sa_sync_conn):
        ensure_country(sa_sync_conn, "fr")
        addr = insert_address(sa_sync_conn, "Lab, France", normalized_text="lab france")
        sa_sync_conn.execute(
            text("UPDATE addresses SET candidates_dirty = false WHERE id = :a"), {"a": addr}
        )

        added = _Q.insert_candidates(
            sa_sync_conn, CountryDetectionMethod.COUNTRY_NAME, [(addr, ["fr", "zz"])]
        )

        assert added == 1
        assert _candidates(sa_sync_conn, addr) == {("fr", "country_name")}
        assert _field(sa_sync_conn, addr, "candidates_dirty") is True

    def test_la_resolution_applique_la_preseance(self, sa_sync_conn):
        for code in ("ca", "ma"):
            ensure_country(sa_sync_conn, code)
        addr = insert_address(sa_sync_conn, "Univ Cadi Ayyad, Marrakech, Canada")
        _Q.insert_candidates(sa_sync_conn, CountryDetectionMethod.COUNTRY_NAME, [(addr, ["ca"])])
        _Q.insert_candidates(sa_sync_conn, CountryDetectionMethod.INSTITUTION, [(addr, ["ma"])])
        _Q.insert_candidates(sa_sync_conn, CountryDetectionMethod.CITY, [(addr, ["ma"])])

        assert _Q.resolve_address_countries(sa_sync_conn) >= 1

        assert _field(sa_sync_conn, addr, "countries") == ["ma"]
        assert _field(sa_sync_conn, addr, "countries_dirty") is True
        assert _field(sa_sync_conn, addr, "candidates_dirty") is False

    def test_une_adresse_sans_candidat_perd_son_pays(self, sa_sync_conn):
        addr = insert_address(sa_sync_conn, "Centre hospitalier universitaire", countries=["fr"])

        _Q.resolve_address_countries(sa_sync_conn, [addr])

        assert _field(sa_sync_conn, addr, "countries") is None

    def test_les_ror_de_l_affiliation_donnent_un_candidat(self, sa_sync_conn):
        ensure_country(sa_sync_conn, "fr")
        pub = insert_publication(sa_sync_conn)
        sa = insert_signature(sa_sync_conn, insert_source_publication(sa_sync_conn, pub))
        addr = insert_address(sa_sync_conn, "Institut Pascal")
        sa_sync_conn.execute(
            text(
                "INSERT INTO ror_organizations (ror_id, name, country_code, types, status)"
                " VALUES ('01a8ajp46', 'UCA', 'fr', '{education}', 'active')"
            )
        )
        sa_sync_conn.execute(
            text("INSERT INTO source_authorship_rors VALUES (:sa, '01a8ajp46', :a)"),
            {"sa": sa, "a": addr},
        )

        assert _Q.insert_ror_candidates(sa_sync_conn) == 1
        assert _candidates(sa_sync_conn, addr) == {("fr", "ror")}


class TestRefreshAddressSourceCountries:
    def test_propagates_country_from_address(self, sa_sync_conn):
        ensure_country(sa_sync_conn, "FR")
        pub_id = insert_publication(sa_sync_conn)
        sd = insert_source_publication(sa_sync_conn, pub_id, source="openalex", source_id="oa-1")
        sa = insert_signature(sa_sync_conn, sd, source="openalex")
        addr = insert_address(
            sa_sync_conn, "Clermont", countries=["FR"], normalized_text="Clermont"
        )
        insert_signature_address(sa_sync_conn, sa, address_id=addr)

        _Q.refresh_signature_countries(sa_sync_conn)
        updated = _Q.refresh_address_source_countries(sa_sync_conn)
        assert updated == 1

        result = sa_sync_conn.execute(
            text("SELECT countries FROM source_publications WHERE id = :sd"),
            {"sd": sd},
        ).scalar_one()
        assert result == ["FR"]

    def test_noop_without_address_countries(self, sa_sync_conn):
        pub_id = insert_publication(sa_sync_conn)
        sd = insert_source_publication(sa_sync_conn, pub_id, source="openalex", source_id="oa-2")
        sa = insert_signature(sa_sync_conn, sd, source="openalex")
        addr = insert_address(sa_sync_conn, "X", countries=None, normalized_text="X")
        insert_signature_address(sa_sync_conn, sa, address_id=addr)

        updated = _Q.refresh_address_source_countries(sa_sync_conn)
        assert updated == 0


class TestRefreshPublicationCountries:
    def test_unions_all_source_countries(self, sa_sync_conn):
        pub_id = insert_publication(sa_sync_conn)
        sd1 = insert_source_publication(
            sa_sync_conn, pub_id, source="hal", source_id="hal-1", countries=["FR"]
        )
        sd2 = insert_source_publication(
            sa_sync_conn, pub_id, source="openalex", source_id="oa-1", countries=["US", "FR"]
        )
        # un sa (dirty par défaut) met la publication dans la portée du refresh.
        insert_signature(sa_sync_conn, sd1, source="hal")
        insert_signature(sa_sync_conn, sd2, source="openalex")

        updated = _Q.refresh_publication_countries(sa_sync_conn)
        assert updated == 1

        result = sa_sync_conn.execute(
            text("SELECT countries FROM publications WHERE id = :pid"),
            {"pid": pub_id},
        ).scalar_one()
        assert result == ["FR", "US"]

    def test_ignores_source_pubs_without_publication_id(self, sa_sync_conn):
        insert_source_publication(
            sa_sync_conn, None, source="hal", source_id="hal-orphan", countries=["FR"]
        )
        updated = _Q.refresh_publication_countries(sa_sync_conn)
        assert updated == 0

    def test_noop_when_already_up_to_date(self, sa_sync_conn):
        pub_id = insert_publication(sa_sync_conn)
        sd = insert_source_publication(
            sa_sync_conn, pub_id, source="hal", source_id="hal-1", countries=["FR"]
        )
        insert_signature(sa_sync_conn, sd, source="hal")  # dirty → publication dans la portée
        sa_sync_conn.execute(
            text("UPDATE publications SET countries = ARRAY['FR'] WHERE id = :pid"),
            {"pid": pub_id},
        )

        updated = _Q.refresh_publication_countries(sa_sync_conn)
        assert updated == 0


def _sp_countries(conn, sp_id):
    return conn.execute(
        text("SELECT countries FROM source_publications WHERE id = :i"), {"i": sp_id}
    ).scalar_one()


def _sa_dirty(conn, sa_id):
    return conn.execute(
        text("SELECT countries_dirty FROM source_authorships WHERE id = :i"), {"i": sa_id}
    ).scalar_one()


def _addr_dirty(conn, addr_id):
    return conn.execute(
        text("SELECT countries_dirty FROM addresses WHERE id = :i"), {"i": addr_id}
    ).scalar_one()


class TestDirtyDrivenSourceCountries:
    """Refresh `source_publications.countries` borné aux documents dont un source_authorship
    est dirty : `source_authorships.countries_dirty` (nouveaux sa) OU lié à une adresse
    `countries_dirty` (pays changé). + orphelin (LEFT JOIN), flag adresse, clear."""

    def test_only_dirty_sources_recomputed(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        dirty_sd = insert_source_publication(
            sa_sync_conn, pub, source="openalex", source_id="oa-dirty"
        )
        clean_sd = insert_source_publication(sa_sync_conn, pub, source="hal", source_id="hal-clean")
        dirty_sa = insert_signature(sa_sync_conn, dirty_sd, source="openalex")  # dirty par défaut
        clean_sa = insert_signature(sa_sync_conn, clean_sd, source="hal")
        sa_sync_conn.execute(
            text("UPDATE source_authorships SET countries_dirty = false WHERE id = :i"),
            {"i": clean_sa},
        )
        insert_signature_address(
            sa_sync_conn,
            dirty_sa,
            address_id=insert_address(
                sa_sync_conn, "Lyon", countries=["FR"], normalized_text="Lyon"
            ),
        )
        insert_signature_address(
            sa_sync_conn,
            clean_sa,
            address_id=insert_address(
                sa_sync_conn, "Boston", countries=["US"], normalized_text="Boston"
            ),
        )

        _Q.refresh_signature_countries(sa_sync_conn)
        _Q.refresh_address_source_countries(sa_sync_conn)
        assert _sp_countries(sa_sync_conn, dirty_sd) == ["FR"]
        assert _sp_countries(sa_sync_conn, clean_sd) is None  # aucun sa dirty → pas recalculé

    def test_orphan_dirty_source_reset_to_null(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        sd = insert_source_publication(
            sa_sync_conn, pub, source="openalex", source_id="oa-o", countries=["FR"]
        )
        sa = insert_signature(sa_sync_conn, sd, source="openalex")  # dirty, adresse sans pays
        insert_signature_address(
            sa_sync_conn,
            sa,
            address_id=insert_address(sa_sync_conn, "X", countries=None, normalized_text="X"),
        )

        _Q.refresh_address_source_countries(sa_sync_conn)
        assert _sp_countries(sa_sync_conn, sd) is None  # orphelin → NULL

    def test_dirty_address_drives_source_recompute(self, sa_sync_conn):
        # Un document NON dirty est recalculé parce que l'adresse de son sa devient dirty.
        pub = insert_publication(sa_sync_conn)
        sd = insert_source_publication(sa_sync_conn, pub, source="openalex", source_id="oa-m")
        sa = insert_signature(sa_sync_conn, sd, source="openalex")
        sa_sync_conn.execute(
            text("UPDATE source_authorships SET countries_dirty = false WHERE id = :i"), {"i": sa}
        )
        addr = insert_address(sa_sync_conn, "Nantes", countries=None, normalized_text="Nantes")
        insert_signature_address(sa_sync_conn, sa, address_id=addr)

        # La résolution pose addresses.countries_dirty sur la ligne changée.
        _resolve(sa_sync_conn, addr, ["FR"])
        assert _addr_dirty(sa_sync_conn, addr) is True
        _Q.refresh_signature_countries(sa_sync_conn)
        _Q.refresh_address_source_countries(sa_sync_conn)
        assert _sp_countries(sa_sync_conn, sd) == ["FR"]  # recalculé via l'adresse dirty

    def test_le_pays_d_une_signature_sans_adresse_vient_de_sa_structure_hal(self, sa_sync_conn):
        """Régression : une signature HAL sans adresse donnait une notice sans pays."""
        pub = insert_publication(sa_sync_conn)
        sd = insert_source_publication(sa_sync_conn, pub, source="hal", source_id="hal-s")
        sa = insert_signature(sa_sync_conn, sd, source="hal")
        sa_sync_conn.execute(
            text(
                "INSERT INTO hal_structures (hal_structure_id, name, structure_type, country_code, status)"
                " VALUES (1, 'Laboratoire de Météorologie Physique', 'laboratory', 'fr', 'VALID')"
            )
        )
        sa_sync_conn.execute(
            text("INSERT INTO source_authorship_hal_structures VALUES (:sa, 1)"), {"sa": sa}
        )

        _Q.refresh_signature_countries(sa_sync_conn)
        _Q.refresh_address_source_countries(sa_sync_conn)

        assert _sp_countries(sa_sync_conn, sd) == ["fr"]

    def test_une_structure_hal_citee_par_un_alias_donne_son_pays(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        sd = insert_source_publication(sa_sync_conn, pub, source="hal", source_id="hal-a")
        sa = insert_signature(sa_sync_conn, sd, source="hal")
        sa_sync_conn.execute(
            text(
                "INSERT INTO hal_structures (hal_structure_id, name, structure_type, country_code, status)"
                " VALUES (1, 'Laboratoire de Météorologie Physique', 'laboratory', 'fr', 'VALID');"
                " INSERT INTO hal_structure_aliases (alias_id, hal_structure_id) VALUES (7, 1)"
            )
        )
        sa_sync_conn.execute(
            text("INSERT INTO source_authorship_hal_structures VALUES (:sa, 7)"), {"sa": sa}
        )

        _Q.refresh_signature_countries(sa_sync_conn)

        assert sa_sync_conn.execute(
            text("SELECT countries FROM source_authorships WHERE id = :sa"), {"sa": sa}
        ).scalar_one() == ["fr"]

    def test_un_intervalle_d_identifiants_borne_le_recalcul_des_signatures(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        sd = insert_source_publication(sa_sync_conn, pub, source="hal", source_id="hal-r")
        first = insert_signature(sa_sync_conn, sd, source="hal")
        second = insert_signature(sa_sync_conn, sd, source="hal", author_position=1)
        sa_sync_conn.execute(
            text(
                "INSERT INTO hal_structures (hal_structure_id, name, structure_type, country_code, status)"
                " VALUES (1, 'Laboratoire de Météorologie Physique', 'laboratory', 'fr', 'VALID')"
            )
        )
        sa_sync_conn.execute(
            text("INSERT INTO source_authorship_hal_structures VALUES (:a, 1), (:b, 1)"),
            {"a": first, "b": second},
        )

        changed = _Q.refresh_signature_countries(sa_sync_conn, id_range=(first, first))

        assert changed == 1
        countries = sa_sync_conn.execute(
            text("SELECT id, countries FROM source_authorships WHERE id IN (:a, :b)"),
            {"a": first, "b": second},
        ).all()
        assert dict(countries) == {first: ["fr"], second: None}

    def test_clear_dirty_clears_both_flags(self, sa_sync_conn):
        pub = insert_publication(sa_sync_conn)
        sd = insert_source_publication(sa_sync_conn, pub, source="openalex", source_id="oa-c")
        sa = insert_signature(sa_sync_conn, sd, source="openalex")  # sa dirty par défaut
        addr = insert_address(sa_sync_conn, "Paris", countries=None, normalized_text="Paris")
        _resolve(sa_sync_conn, addr, ["FR"])  # addr dirty
        _Q.clear_countries_dirty(sa_sync_conn)
        assert _sa_dirty(sa_sync_conn, sa) is False
        assert _addr_dirty(sa_sync_conn, addr) is False
