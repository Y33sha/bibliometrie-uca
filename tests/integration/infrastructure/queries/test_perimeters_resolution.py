"""Résolution des périmètres depuis `config` : une clé absente vaut périmètre vide, et le périmètre des personnes se rabat sur celui d'extraction."""

from sqlalchemy import text

from infrastructure.read_models.perimeters.queries import (
    PerimetersQueries,
    get_extraction_api_ids,
    get_extraction_structure_ids,
    get_hal_collections,
    get_institution_country,
    get_persons_perimeter_name,
    get_persons_perimeter_root_ids,
    get_persons_structure_ids,
)
from tests.integration.helpers.config import set_config
from tests.integration.helpers.rors import insert_ror_tree
from tests.integration.helpers.structures import insert_perimeter, insert_structure


def _clear_perimeter_config(conn) -> None:
    conn.execute(
        text("DELETE FROM config WHERE key IN ('perimeter_extraction', 'perimeter_persons')")
    )


def _perimeter(conn, code: str, name: str) -> int:
    """Crée un périmètre à une racine, matérialise sa clôture et renvoie l'identifiant de la racine."""
    root = insert_structure(conn, f"{code}_racine", structure_type="universite")
    insert_perimeter(conn, code, root_structure_ids=[root], name=name, materialize=True)
    return root


def test_absent_keys_give_empty_perimeters(sa_sync_conn):
    conn = sa_sync_conn
    _clear_perimeter_config(conn)

    assert get_extraction_structure_ids(conn) == set()
    assert get_persons_structure_ids(conn) == set()
    assert get_persons_perimeter_root_ids(conn) == []
    assert get_persons_perimeter_name(conn) == ""


def test_persons_perimeter_falls_back_to_extraction(sa_sync_conn):
    conn = sa_sync_conn
    _clear_perimeter_config(conn)
    root = _perimeter(conn, "res_extraction", "Extraction")
    set_config(conn, "perimeter_extraction", "res_extraction")

    assert get_persons_structure_ids(conn) == {root}
    assert get_persons_perimeter_root_ids(conn) == [root]
    assert get_persons_perimeter_name(conn) == "Extraction"


def test_configured_persons_perimeter_prevails(sa_sync_conn):
    conn = sa_sync_conn
    _clear_perimeter_config(conn)
    _perimeter(conn, "res_extraction", "Extraction")
    persons_root = _perimeter(conn, "res_personnes", "Personnes")
    set_config(conn, "perimeter_extraction", "res_extraction")
    set_config(conn, "perimeter_persons", "res_personnes")

    assert get_persons_structure_ids(conn) == {persons_root}
    assert get_persons_perimeter_name(conn) == "Personnes"


def test_institution_country_defaults_when_absent(sa_sync_conn):
    conn = sa_sync_conn
    conn.execute(text("DELETE FROM config WHERE key = 'institution_country'"))

    assert get_institution_country(conn) == "fr"


def test_persons_perimeter_countries_count_structures_by_ror_country(sa_sync_conn):
    conn = sa_sync_conn
    _clear_perimeter_config(conn)
    insert_ror_tree(conn)
    structures = []
    for code, ror in (
        ("res_fr_1", "0univ0001"),
        ("res_fr_2", "0lab00001"),
        ("res_de", "0ger00001"),
        ("res_sans_ror", None),
    ):
        structure = insert_structure(conn, code)
        conn.execute(
            text("UPDATE structures SET ror_id = :r WHERE id = :s"), {"r": ror, "s": structure}
        )
        structures.append(structure)
    insert_perimeter(conn, "res_pays", root_structure_ids=structures, materialize=True)
    set_config(conn, "perimeter_persons", "res_pays")

    countries = PerimetersQueries(conn).persons_perimeter_countries()

    assert [(c.code, c.structure_count) for c in countries] == [("fr", 2), ("de", 1)]


class TestGetHalCollections:
    def test_derivees_des_structures_du_perimetre(self, sa_sync_conn):
        conn = sa_sync_conn
        structure = insert_structure(conn, "cfg_labo_a", hal_collection="LABO-A")
        insert_perimeter(conn, "cfg_perim", root_structure_ids=[structure], materialize=True)
        set_config(conn, "perimeter_extraction", "cfg_perim")

        assert get_hal_collections(conn) == {"LABO-A": "cfg_labo_a"}

    def test_perimetre_designe_mais_inexistant(self, sa_sync_conn):
        conn = sa_sync_conn
        set_config(conn, "perimeter_extraction", "cfg_perim_inexistant")

        assert get_hal_collections(conn) == {}

    def test_perimetre_dont_aucune_structure_ne_depose_dans_hal(self, sa_sync_conn):
        conn = sa_sync_conn
        structure = insert_structure(conn, "cfg_labo_sans_collection")
        insert_perimeter(
            conn, "cfg_perim_sans_collection", root_structure_ids=[structure], materialize=True
        )
        set_config(conn, "perimeter_extraction", "cfg_perim_sans_collection")

        assert get_hal_collections(conn) == {}

    def test_sans_perimetre_configure(self, sa_sync_conn):
        conn = sa_sync_conn
        conn.execute(text("DELETE FROM config WHERE key = 'perimeter_extraction'"))

        assert get_hal_collections(conn) == {}


class TestGetExtractionApiIds:
    def test_identifiants_des_structures_du_perimetre(self, sa_sync_conn):
        conn = sa_sync_conn
        premiere = insert_structure(conn, "cfg_labo_b", api_ids={"openalex": ["I1", "I2"]})
        seconde = insert_structure(conn, "cfg_labo_c", api_ids={"openalex": ["I2", "I3"]})
        insert_perimeter(
            conn, "cfg_perim_ids", root_structure_ids=[premiere, seconde], materialize=True
        )
        set_config(conn, "perimeter_extraction", "cfg_perim_ids")

        # Dédupliqués, dans l'ordre de première rencontre.
        assert get_extraction_api_ids(conn, "openalex") == ["I1", "I2", "I3"]

    def test_identifiant_unique_ecrit_sans_liste(self, sa_sync_conn):
        conn = sa_sync_conn
        structure = insert_structure(conn, "cfg_labo_d", api_ids={"scanr": "S1"})
        insert_perimeter(
            conn, "cfg_perim_scalaire", root_structure_ids=[structure], materialize=True
        )
        set_config(conn, "perimeter_extraction", "cfg_perim_scalaire")

        assert get_extraction_api_ids(conn, "scanr") == ["S1"]

    def test_identifiants_d_une_forme_inattendue_ignores(self, sa_sync_conn):
        """Une valeur qui n'est ni une liste ni une chaîne ne désigne aucun identifiant."""
        conn = sa_sync_conn
        premiere = insert_structure(conn, "cfg_labo_f", api_ids={"openalex": {"id": "I1"}})
        seconde = insert_structure(conn, "cfg_labo_g", api_ids={"openalex": ["I2"]})
        insert_perimeter(
            conn, "cfg_perim_formes", root_structure_ids=[premiere, seconde], materialize=True
        )
        set_config(conn, "perimeter_extraction", "cfg_perim_formes")

        assert get_extraction_api_ids(conn, "openalex") == ["I2"]

    def test_source_absente_des_structures(self, sa_sync_conn):
        conn = sa_sync_conn
        structure = insert_structure(conn, "cfg_labo_e", api_ids={"openalex": ["I1"]})
        insert_perimeter(conn, "cfg_perim_autre", root_structure_ids=[structure], materialize=True)
        set_config(conn, "perimeter_extraction", "cfg_perim_autre")

        assert get_extraction_api_ids(conn, "wos") == []

    def test_sans_perimetre_configure(self, sa_sync_conn):
        conn = sa_sync_conn
        conn.execute(text("DELETE FROM config WHERE key = 'perimeter_extraction'"))

        assert get_extraction_api_ids(conn, "openalex") == []

    def test_perimetre_configure_mais_vide(self, sa_sync_conn):
        conn = sa_sync_conn
        set_config(conn, "perimeter_extraction", "cfg_perim_inexistant")

        assert get_extraction_api_ids(conn, "openalex") == []
