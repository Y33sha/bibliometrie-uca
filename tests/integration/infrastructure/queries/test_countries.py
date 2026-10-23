"""Tests d'intégration du SQL de la phase `countries` : candidats, résolution, recopie en cascade."""

import logging

from sqlalchemy import text

from domain.country_detection import CountryDetectionMethod
from infrastructure.db.queues import Queue
from pipeline.transformation.countries.refresh_publication_countries import (
    create_dirty_scope,
    delete_processed_marks,
    drop_dirty_scope,
    refresh,
    refresh_publication_countries,
    refresh_source_contribution_countries,
    refresh_source_record_countries,
)
from pipeline.transformation.countries.resolution import (
    resolve_address_countries,
    resolve_queued_addresses,
)
from pipeline.transformation.countries.store import CountryCandidatesStore
from tests.integration.helpers.addresses import ensure_country, insert_address
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import mark, queued, unmark
from tests.integration.helpers.sources import (
    insert_source_contribution,
    insert_source_contribution_address,
    insert_source_record,
)


def _refresh(conn, *steps) -> list[int]:
    """Exécute les étapes de recalcul dans le périmètre des contributions sources à recalculer, et rend leurs nombres de lignes modifiées."""
    create_dirty_scope(conn)
    try:
        return [refresh_step(conn) for refresh_step in steps]
    finally:
        drop_dirty_scope(conn)


def _resolve(conn, address_id: int, codes: list[str]) -> None:
    """Donne à l'adresse le candidat `country_name` `codes`, puis la résout."""
    for code in codes:
        ensure_country(conn, code)
    CountryCandidatesStore(conn).add(CountryDetectionMethod.COUNTRY_NAME, [(address_id, codes)])
    resolve_address_countries(conn, [address_id])


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
        unmark(sa_sync_conn, Queue.ADDRESS_CANDIDATES, addr)

        added = CountryCandidatesStore(sa_sync_conn).add(
            CountryDetectionMethod.COUNTRY_NAME, [(addr, ["fr", "zz"])]
        )

        assert added == 1
        assert _candidates(sa_sync_conn, addr) == {("fr", "country_name")}
        assert queued(sa_sync_conn, Queue.ADDRESS_CANDIDATES) == {addr}

    def test_la_detection_efface_les_pays_que_le_moyen_ne_trouve_pas(self, sa_sync_conn):
        """Régression : un candidat issu d'une forme retirée de `place_name_forms` restait en place."""
        for code in ("fr", "us"):
            ensure_country(sa_sync_conn, code)
        dirty = insert_address(sa_sync_conn, "Gilead Sciences, La Défense")
        clean = insert_address(sa_sync_conn, "Gilead, Foster City")
        sa_sync_conn.execute(
            text(
                "INSERT INTO address_country_candidates (address_id, country_code, method) VALUES"
                " (:d, 'fr', 'institution'), (:d, 'fr', 'city'), (:c, 'us', 'institution')"
            ),
            {"d": dirty, "c": clean},
        )
        unmark(sa_sync_conn, Queue.ADDRESS_CANDIDATES, clean)

        CountryCandidatesStore(sa_sync_conn).replace_for_queued_addresses(
            CountryDetectionMethod.INSTITUTION, []
        )

        assert _candidates(sa_sync_conn, dirty) == {("fr", "city")}
        assert _candidates(sa_sync_conn, clean) == {("us", "institution")}

    def test_la_resolution_applique_la_preseance(self, sa_sync_conn):
        for code in ("ca", "ma"):
            ensure_country(sa_sync_conn, code)
        addr = insert_address(sa_sync_conn, "Univ Cadi Ayyad, Marrakech, Canada")
        CountryCandidatesStore(sa_sync_conn).add(
            CountryDetectionMethod.COUNTRY_NAME, [(addr, ["ca"])]
        )
        CountryCandidatesStore(sa_sync_conn).add(
            CountryDetectionMethod.INSTITUTION, [(addr, ["ma"])]
        )
        CountryCandidatesStore(sa_sync_conn).add(CountryDetectionMethod.CITY, [(addr, ["ma"])])

        assert resolve_queued_addresses(sa_sync_conn) >= 1

        assert _field(sa_sync_conn, addr, "countries") == ["ma"]
        assert addr in queued(sa_sync_conn, Queue.ADDRESS_COUNTRIES)
        assert addr not in queued(sa_sync_conn, Queue.ADDRESS_CANDIDATES)

    def test_la_detection_ne_remarque_pas_les_adresses_en_file(self, sa_sync_conn):
        ensure_country(sa_sync_conn, "fr")
        addr = insert_address(sa_sync_conn, "Lab, France", normalized_text="lab france")
        (seq_before,) = sa_sync_conn.execute(
            text(f"SELECT seq FROM {Queue.ADDRESS_CANDIDATES} WHERE id = :a"), {"a": addr}
        ).one()

        CountryCandidatesStore(sa_sync_conn).replace_for_queued_addresses(
            CountryDetectionMethod.COUNTRY_NAME, [(addr, ["fr"])]
        )

        assert (
            sa_sync_conn.execute(
                text(f"SELECT seq FROM {Queue.ADDRESS_CANDIDATES} WHERE id = :a"), {"a": addr}
            ).scalar_one()
            == seq_before
        )

    def test_une_adresse_sans_candidat_perd_son_pays(self, sa_sync_conn):
        addr = insert_address(sa_sync_conn, "Centre hospitalier universitaire", countries=["fr"])

        resolve_address_countries(sa_sync_conn, [addr])

        assert _field(sa_sync_conn, addr, "countries") is None

    def test_les_ror_de_l_affiliation_donnent_un_candidat(self, sa_sync_conn):
        ensure_country(sa_sync_conn, "fr")
        publication = insert_publication(sa_sync_conn)
        sa = insert_source_contribution(
            sa_sync_conn, insert_source_record(sa_sync_conn, publication)
        )
        addr = insert_address(sa_sync_conn, "Institut Pascal")
        sa_sync_conn.execute(
            text(
                "INSERT INTO ror_organizations (ror_id, name, country_code, types, status)"
                " VALUES ('01a8ajp46', 'UCA', 'fr', '{education}', 'active')"
            )
        )
        sa_sync_conn.execute(
            text("INSERT INTO source_contribution_rors VALUES (:sa, '01a8ajp46', :a)"),
            {"sa": sa, "a": addr},
        )

        assert CountryCandidatesStore(sa_sync_conn).add_ror() == 1
        assert _candidates(sa_sync_conn, addr) == {("fr", "ror")}


class TestRefreshAddressSourceCountries:
    def test_propagates_country_from_address(self, sa_sync_conn):
        ensure_country(sa_sync_conn, "FR")
        publication_id = insert_publication(sa_sync_conn)
        source_record = insert_source_record(
            sa_sync_conn, publication_id, source="openalex", source_id="oa-1"
        )
        sa = insert_source_contribution(sa_sync_conn, source_record, source="openalex")
        addr = insert_address(
            sa_sync_conn, "Clermont", countries=["FR"], normalized_text="Clermont"
        )
        insert_source_contribution_address(sa_sync_conn, sa, address_id=addr)

        _, updated = _refresh(
            sa_sync_conn, refresh_source_contribution_countries, refresh_source_record_countries
        )
        assert updated == 1

        result = sa_sync_conn.execute(
            text("SELECT countries FROM source_records WHERE id = :sd"),
            {"sd": source_record},
        ).scalar_one()
        assert result == ["FR"]

    def test_le_journal_accorde_les_enregistrements_sources_mis_a_jour(self, sa_sync_conn, caplog):
        """Régression : le journal écrivait « enregistrements sources mises à jour »."""
        ensure_country(sa_sync_conn, "FR")
        source_record = insert_source_record(
            sa_sync_conn, insert_publication(sa_sync_conn), source="openalex", source_id="oa-j"
        )
        sa = insert_source_contribution(sa_sync_conn, source_record, source="openalex")
        addr = insert_address(sa_sync_conn, "Lyon", countries=["FR"], normalized_text="Lyon")
        insert_source_contribution_address(sa_sync_conn, sa, address_id=addr)

        with caplog.at_level(logging.INFO):
            refresh(sa_sync_conn, logging.getLogger(__name__))

        assert "1 enregistrement source mis à jour" in caplog.text

    def test_noop_without_address_countries(self, sa_sync_conn):
        publication_id = insert_publication(sa_sync_conn)
        source_record = insert_source_record(
            sa_sync_conn, publication_id, source="openalex", source_id="oa-2"
        )
        sa = insert_source_contribution(sa_sync_conn, source_record, source="openalex")
        addr = insert_address(sa_sync_conn, "X", countries=None, normalized_text="X")
        insert_source_contribution_address(sa_sync_conn, sa, address_id=addr)

        (updated,) = _refresh(sa_sync_conn, refresh_source_record_countries)
        assert updated == 0


class TestRefreshPublicationCountries:
    def test_unions_all_source_countries(self, sa_sync_conn):
        publication_id = insert_publication(sa_sync_conn)
        sd1 = insert_source_record(
            sa_sync_conn, publication_id, source="hal", source_id="hal-1", countries=["FR"]
        )
        sd2 = insert_source_record(
            sa_sync_conn,
            publication_id,
            source="openalex",
            source_id="oa-1",
            countries=["US", "FR"],
        )
        # Une contribution source, marquée à l'insertion, met la publication dans la portée du refresh.
        insert_source_contribution(sa_sync_conn, sd1, source="hal")
        insert_source_contribution(sa_sync_conn, sd2, source="openalex")

        (updated,) = _refresh(sa_sync_conn, refresh_publication_countries)
        assert updated == 1

        result = sa_sync_conn.execute(
            text("SELECT countries FROM publications WHERE id = :pid"),
            {"pid": publication_id},
        ).scalar_one()
        assert result == ["FR", "US"]

    def test_ignores_source_records_without_publication_id(self, sa_sync_conn):
        insert_source_record(
            sa_sync_conn, None, source="hal", source_id="hal-orphan", countries=["FR"]
        )
        (updated,) = _refresh(sa_sync_conn, refresh_publication_countries)
        assert updated == 0

    def test_noop_when_already_up_to_date(self, sa_sync_conn):
        publication_id = insert_publication(sa_sync_conn)
        source_record = insert_source_record(
            sa_sync_conn, publication_id, source="hal", source_id="hal-1", countries=["FR"]
        )
        insert_source_contribution(
            sa_sync_conn, source_record, source="hal"
        )  # marquée → publication dans la portée
        sa_sync_conn.execute(
            text("UPDATE publications SET countries = ARRAY['FR'] WHERE id = :pid"),
            {"pid": publication_id},
        )

        (updated,) = _refresh(sa_sync_conn, refresh_publication_countries)
        assert updated == 0


def _source_record_countries(conn, source_record_id):
    return conn.execute(
        text("SELECT countries FROM source_records WHERE id = :i"), {"i": source_record_id}
    ).scalar_one()


class TestDirtyDrivenSourceCountries:
    """Recalcul borné aux enregistrements sources dont une contribution source est en file, ou liée à une adresse en file."""

    def test_only_dirty_sources_recomputed(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        dirty_source_record = insert_source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-dirty"
        )
        clean_source_record = insert_source_record(
            sa_sync_conn, publication, source="hal", source_id="hal-clean"
        )
        dirty_source_contribution = insert_source_contribution(
            sa_sync_conn, dirty_source_record, source="openalex"
        )
        clean_source_contribution = insert_source_contribution(
            sa_sync_conn, clean_source_record, source="hal"
        )
        unmark(sa_sync_conn, Queue.SOURCE_CONTRIBUTION_COUNTRIES, clean_source_contribution)
        insert_source_contribution_address(
            sa_sync_conn,
            dirty_source_contribution,
            address_id=insert_address(
                sa_sync_conn, "Lyon", countries=["FR"], normalized_text="Lyon"
            ),
        )
        insert_source_contribution_address(
            sa_sync_conn,
            clean_source_contribution,
            address_id=insert_address(
                sa_sync_conn, "Boston", countries=["US"], normalized_text="Boston"
            ),
        )

        _refresh(
            sa_sync_conn, refresh_source_contribution_countries, refresh_source_record_countries
        )
        assert _source_record_countries(sa_sync_conn, dirty_source_record) == ["FR"]
        assert (
            _source_record_countries(sa_sync_conn, clean_source_record) is None
        )  # aucune contribution source en file → pas recalculé

    def test_orphan_dirty_source_reset_to_null(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-o", countries=["FR"]
        )
        sa = insert_source_contribution(
            sa_sync_conn, source_record, source="openalex"
        )  # en file, adresse sans pays
        insert_source_contribution_address(
            sa_sync_conn,
            sa,
            address_id=insert_address(sa_sync_conn, "X", countries=None, normalized_text="X"),
        )

        _refresh(sa_sync_conn, refresh_source_record_countries)
        assert _source_record_countries(sa_sync_conn, source_record) is None  # orphelin → NULL

    def test_dirty_address_drives_source_recompute(self, sa_sync_conn):
        # Une contribution source hors file est recalculée parce que son adresse entre en file.
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-m"
        )
        sa = insert_source_contribution(sa_sync_conn, source_record, source="openalex")
        unmark(sa_sync_conn, Queue.SOURCE_CONTRIBUTION_COUNTRIES, sa)
        addr = insert_address(sa_sync_conn, "Nantes", countries=None, normalized_text="Nantes")
        insert_source_contribution_address(sa_sync_conn, sa, address_id=addr)

        # La résolution marque l'adresse dont le pays change.
        _resolve(sa_sync_conn, addr, ["FR"])
        assert addr in queued(sa_sync_conn, Queue.ADDRESS_COUNTRIES)
        _refresh(
            sa_sync_conn, refresh_source_contribution_countries, refresh_source_record_countries
        )
        assert _source_record_countries(sa_sync_conn, source_record) == ["FR"]

    def test_le_pays_d_une_contribution_source_sans_adresse_vient_de_sa_structure_hal(
        self, sa_sync_conn
    ):
        """Régression : une contribution source HAL sans adresse donnait un enregistrement source sans pays."""
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(
            sa_sync_conn, publication, source="hal", source_id="hal-s"
        )
        sa = insert_source_contribution(sa_sync_conn, source_record, source="hal")
        sa_sync_conn.execute(
            text(
                "INSERT INTO hal_structures (hal_structure_id, name, structure_type, country_code, status)"
                " VALUES (1, 'Laboratoire de Météorologie Physique', 'laboratory', 'fr', 'VALID')"
            )
        )
        sa_sync_conn.execute(
            text("INSERT INTO source_contribution_hal_structures VALUES (:sa, 1)"), {"sa": sa}
        )

        _refresh(
            sa_sync_conn, refresh_source_contribution_countries, refresh_source_record_countries
        )

        assert _source_record_countries(sa_sync_conn, source_record) == ["fr"]

    def test_une_structure_hal_citee_par_un_alias_donne_son_pays(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(
            sa_sync_conn, publication, source="hal", source_id="hal-a"
        )
        sa = insert_source_contribution(sa_sync_conn, source_record, source="hal")
        sa_sync_conn.execute(
            text(
                "INSERT INTO hal_structures (hal_structure_id, name, structure_type, country_code, status)"
                " VALUES (1, 'Laboratoire de Météorologie Physique', 'laboratory', 'fr', 'VALID');"
                " INSERT INTO hal_structure_aliases (alias_id, hal_structure_id) VALUES (7, 1)"
            )
        )
        sa_sync_conn.execute(
            text("INSERT INTO source_contribution_hal_structures VALUES (:sa, 7)"), {"sa": sa}
        )

        _refresh(sa_sync_conn, refresh_source_contribution_countries)

        assert sa_sync_conn.execute(
            text("SELECT countries FROM source_contributions WHERE id = :sa"), {"sa": sa}
        ).scalar_one() == ["fr"]

    def test_les_marquages_traites_sont_supprimes_des_deux_files(self, sa_sync_conn):
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-c"
        )
        insert_source_contribution(sa_sync_conn, source_record, source="openalex")
        addr = insert_address(sa_sync_conn, "Paris", countries=None, normalized_text="Paris")
        _resolve(sa_sync_conn, addr, ["FR"])

        create_dirty_scope(sa_sync_conn)
        delete_processed_marks(sa_sync_conn)
        drop_dirty_scope(sa_sync_conn)

        assert queued(sa_sync_conn, Queue.SOURCE_CONTRIBUTION_COUNTRIES) == set()
        assert queued(sa_sync_conn, Queue.ADDRESS_COUNTRIES) == set()

    def test_un_marquage_fait_pendant_la_phase_reste_en_file(self, sa_sync_conn):
        """Régression : l'effacement de fin de phase emportait les marquages faits pendant la phase, même ceux d'une ligne déjà marquée."""
        publication = insert_publication(sa_sync_conn)
        source_record = insert_source_record(
            sa_sync_conn, publication, source="openalex", source_id="oa-p"
        )
        remarked = insert_source_contribution(sa_sync_conn, source_record, source="openalex")
        insert_source_contribution(
            sa_sync_conn, source_record, source="openalex", author_position=1
        )

        create_dirty_scope(sa_sync_conn)
        mark(sa_sync_conn, Queue.SOURCE_CONTRIBUTION_COUNTRIES, [remarked])
        added = insert_source_contribution(
            sa_sync_conn, source_record, source="openalex", author_position=2
        )
        delete_processed_marks(sa_sync_conn)
        drop_dirty_scope(sa_sync_conn)

        assert queued(sa_sync_conn, Queue.SOURCE_CONTRIBUTION_COUNTRIES) == {remarked, added}
