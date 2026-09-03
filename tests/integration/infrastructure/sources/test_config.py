"""Lecture de la configuration du pipeline, depuis la table `config` et le périmètre.

Trois réglages en dépendent : les années à couvrir, les collections HAL à moissonner et les identifiants de structure à interroger par source. Les deux derniers se dérivent du périmètre d'extraction — les structures qui le composent portent la collection et les identifiants — avec repli sur une valeur posée en configuration.

Une valeur de configuration illisible ne fait pas échouer le pipeline : elle est signalée et le réglage retombe sur son défaut. Sans ce repli, une saisie fautive dans l'interface d'administration arrêterait le moissonnage.
"""

import json

from sqlalchemy import text

from domain.dates import today
from infrastructure.pipeline.perimeter import refresh_perimeter_structures
from infrastructure.sources.config import (
    get_extraction_api_ids,
    get_hal_collections,
    get_years,
)


def _set_config(conn, key: str, value) -> None:
    conn.execute(text("DELETE FROM config WHERE key = :k"), {"k": key})
    conn.execute(
        text("INSERT INTO config (key, value) VALUES (:k, CAST(:v AS jsonb))"),
        {"k": key, "v": json.dumps(value)},
    )


def _structure(conn, code: str, *, hal_collection=None, api_ids=None) -> int:
    return conn.execute(
        text(
            "INSERT INTO structures (code, name, structure_type, hal_collection, api_ids) "
            "VALUES (:c, :c, CAST('labo' AS structure_type), :hal, CAST(:ids AS jsonb)) "
            "RETURNING id"
        ),
        {"c": code, "hal": hal_collection, "ids": json.dumps(api_ids) if api_ids else None},
    ).scalar_one()


def _perimeter(conn, code: str, roots: list[int]) -> None:
    """Crée le périmètre et matérialise sa clôture, que les lectures de configuration consultent."""
    conn.execute(
        text(
            "INSERT INTO perimeters (code, name, root_structure_ids) "
            "VALUES (:c, :c, CAST(:ids AS integer[]))"
        ),
        {"c": code, "ids": roots},
    )
    refresh_perimeter_structures(conn)


class TestGetYears:
    def test_uses_config_anchor_when_no_argument(self, sa_sync_conn):
        _set_config(sa_sync_conn, "pipeline_start_year_full", 2017)
        current = today().year
        assert get_years(sa_sync_conn) == list(range(2017, current + 1))

    def test_explicit_start_year_overrides_config(self, sa_sync_conn):
        _set_config(sa_sync_conn, "pipeline_start_year_full", 2017)
        current = today().year
        assert get_years(sa_sync_conn, start_year=2020) == list(range(2020, current + 1))

    def test_falls_back_to_current_year_when_unset(self, sa_sync_conn):
        sa_sync_conn.execute(text("DELETE FROM config WHERE key = 'pipeline_start_year_full'"))
        current = today().year
        assert get_years(sa_sync_conn) == [current]

    def test_falls_back_when_start_year_in_future(self, sa_sync_conn):
        current = today().year
        assert get_years(sa_sync_conn, start_year=current + 5) == [current]


class TestConfigIllisible:
    """Une valeur qui n'est pas une année laisse le réglage retomber sur son défaut."""

    def test_texte_a_la_place_d_une_annee(self, sa_sync_conn):
        _set_config(sa_sync_conn, "pipeline_start_year_full", "pas une année")

        assert get_years(sa_sync_conn) == [today().year]

    def test_booleen_a_la_place_d_une_annee(self, sa_sync_conn):
        """`True` vaut 1 pour Python : sans garde, l'ancre serait l'an 1."""
        _set_config(sa_sync_conn, "pipeline_start_year_full", True)

        assert get_years(sa_sync_conn) == [today().year]

    def test_annee_ecrite_en_toutes_lettres_de_chiffres(self, sa_sync_conn):
        """La valeur saisie dans l'interface peut arriver en texte : elle reste exploitable."""
        _set_config(sa_sync_conn, "pipeline_start_year_full", "2017")

        assert get_years(sa_sync_conn) == list(range(2017, today().year + 1))


class TestGetHalCollections:
    def test_derivees_des_structures_du_perimetre(self, sa_sync_conn):
        conn = sa_sync_conn
        structure = _structure(conn, "cfg_labo_a", hal_collection="LABO-A")
        _perimeter(conn, "cfg_perim", [structure])
        _set_config(conn, "perimeter_extraction", "cfg_perim")

        assert get_hal_collections(conn) == {"LABO-A": "cfg_labo_a"}

    def test_repli_sur_la_valeur_configuree(self, sa_sync_conn):
        """Aucune structure du périmètre ne porte de collection : la configuration prend le relais."""
        conn = sa_sync_conn
        _set_config(conn, "perimeter_extraction", "cfg_perim_vide")
        _set_config(conn, "hal_collections", {"UCA": "Université"})

        assert get_hal_collections(conn) == {"UCA": "Université"}

    def test_perimetre_dont_aucune_structure_ne_depose_dans_hal(self, sa_sync_conn):
        """Le périmètre est peuplé, mais sans collection : la configuration prend le relais."""
        conn = sa_sync_conn
        structure = _structure(conn, "cfg_labo_sans_collection")
        _perimeter(conn, "cfg_perim_sans_collection", [structure])
        _set_config(conn, "perimeter_extraction", "cfg_perim_sans_collection")
        _set_config(conn, "hal_collections", {"UCA": "Université"})

        assert get_hal_collections(conn) == {"UCA": "Université"}

    def test_sans_collection_nulle_part(self, sa_sync_conn):
        conn = sa_sync_conn
        conn.execute(
            text("DELETE FROM config WHERE key IN ('perimeter_extraction', 'hal_collections')")
        )

        assert get_hal_collections(conn) == {}


class TestGetExtractionApiIds:
    def test_identifiants_des_structures_du_perimetre(self, sa_sync_conn):
        conn = sa_sync_conn
        premiere = _structure(conn, "cfg_labo_b", api_ids={"openalex": ["I1", "I2"]})
        seconde = _structure(conn, "cfg_labo_c", api_ids={"openalex": ["I2", "I3"]})
        _perimeter(conn, "cfg_perim_ids", [premiere, seconde])
        _set_config(conn, "perimeter_extraction", "cfg_perim_ids")

        # Dédupliqués, dans l'ordre de première rencontre.
        assert get_extraction_api_ids(conn, "openalex") == ["I1", "I2", "I3"]

    def test_identifiant_unique_ecrit_sans_liste(self, sa_sync_conn):
        conn = sa_sync_conn
        structure = _structure(conn, "cfg_labo_d", api_ids={"scanr": "S1"})
        _perimeter(conn, "cfg_perim_scalaire", [structure])
        _set_config(conn, "perimeter_extraction", "cfg_perim_scalaire")

        assert get_extraction_api_ids(conn, "scanr") == ["S1"]

    def test_identifiants_d_une_forme_inattendue_ignores(self, sa_sync_conn):
        """Une valeur qui n'est ni une liste ni une chaîne ne désigne aucun identifiant."""
        conn = sa_sync_conn
        premiere = _structure(conn, "cfg_labo_f", api_ids={"openalex": {"id": "I1"}})
        seconde = _structure(conn, "cfg_labo_g", api_ids={"openalex": ["I2"]})
        _perimeter(conn, "cfg_perim_formes", [premiere, seconde])
        _set_config(conn, "perimeter_extraction", "cfg_perim_formes")

        assert get_extraction_api_ids(conn, "openalex") == ["I2"]

    def test_source_absente_des_structures(self, sa_sync_conn):
        conn = sa_sync_conn
        structure = _structure(conn, "cfg_labo_e", api_ids={"openalex": ["I1"]})
        _perimeter(conn, "cfg_perim_autre", [structure])
        _set_config(conn, "perimeter_extraction", "cfg_perim_autre")

        assert get_extraction_api_ids(conn, "wos") == []

    def test_sans_perimetre_configure(self, sa_sync_conn):
        conn = sa_sync_conn
        conn.execute(text("DELETE FROM config WHERE key = 'perimeter_extraction'"))

        assert get_extraction_api_ids(conn, "openalex") == []

    def test_perimetre_configure_mais_vide(self, sa_sync_conn):
        conn = sa_sync_conn
        _set_config(conn, "perimeter_extraction", "cfg_perim_inexistant")

        assert get_extraction_api_ids(conn, "openalex") == []
