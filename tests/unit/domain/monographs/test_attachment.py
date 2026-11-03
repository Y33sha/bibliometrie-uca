"""`group_volumes` : rattachement en lot des enregistrements sources à leur monographie."""

from itertools import permutations

from domain.monographs.attachment import ExistingMonograph, Volume, VolumeRecord, group_volumes

_I1 = "9783031123450"
_I2 = "9783031123467"
_E1 = "9783031123474"


def _record(
    record_id: int,
    title: str | None = "Proceedings of ICBBM",
    *,
    isbns: tuple[str, ...] = (),
    eisbns: tuple[str, ...] = (),
    publisher_id: int | None = None,
    proceedings: bool = False,
) -> VolumeRecord:
    return VolumeRecord(record_id, title, isbns, eisbns, proceedings, 2025, publisher_id)


def _attachment(volumes: list[Volume]) -> set[tuple[int, ...]]:
    return {v.record_ids for v in volumes}


def test_les_enregistrements_d_un_meme_isbn_forment_un_volume():
    volumes = group_volumes([_record(1, isbns=(_I1,)), _record(2, eisbns=(_I1,))], [])
    assert volumes == [
        Volume(
            record_ids=(1, 2),
            monograph_ids=(),
            title="Proceedings of ICBBM",
            isbn=_I1,
            eisbn=None,
            proceedings=False,
            year=2025,
            publisher_id=None,
        )
    ]


def test_un_isbn_et_un_eisbn_d_un_meme_enregistrement_reunissent_deux_enregistrements():
    volumes = group_volumes(
        [_record(1, isbns=(_I1,), eisbns=(_E1,)), _record(2, eisbns=(_E1,))], []
    )
    assert _attachment(volumes) == {(1, 2)}
    assert (volumes[0].isbn, volumes[0].eisbn) == (_I1, _E1)


def test_un_enregistrement_sans_isbn_reste_seul_entre_deux_volumes_de_son_titre():
    records = [_record(1, isbns=(_I1,)), _record(2, isbns=(_I2,)), _record(3)]
    assert _attachment(group_volumes(records, [])) == {(1,), (2,)}


def test_le_rattachement_est_independant_de_l_ordre():
    """Exemple de l'inventaire : deux volumes d'ISBN I1 et I2, un enregistrement source B sans ISBN."""
    records = [_record(1, isbns=(_I1,)), _record(2, isbns=(_I2,)), _record(3)]
    results = {frozenset(_attachment(group_volumes(order, []))) for order in permutations(records)}
    assert len(results) == 1


def test_un_enregistrement_sans_isbn_rejoint_le_seul_volume_a_isbn_de_son_titre():
    records = [_record(1, isbns=(_I1,), publisher_id=7), _record(2, publisher_id=7)]
    assert _attachment(group_volumes(records, [])) == {(1, 2)}


def test_le_volume_a_isbn_du_meme_editeur_passe_avant_celui_sans_editeur():
    """Cas réel : « Passions géométriques », un ISBN chez l'éditeur, un autre sans éditeur."""
    records = [
        _record(1, isbns=(_I1,), publisher_id=7),
        _record(2, isbns=(_I2,)),
        _record(3, publisher_id=7),
    ]
    assert _attachment(group_volumes(records, [])) == {(1, 3), (2,)}


def test_un_editeur_different_ecarte_le_volume_a_isbn():
    records = [_record(1, isbns=(_I1,), publisher_id=7), _record(2, publisher_id=8)]
    assert _attachment(group_volumes(records, [])) == {(1,), (2,)}


def test_sans_isbn_un_volume_par_titre_ou_par_editeur():
    records = [
        _record(1, publisher_id=7),
        _record(2, publisher_id=8),
        _record(3),
        _record(4, "Autre titre"),
        _record(5, "Autre titre", publisher_id=7),
    ]
    assert _attachment(group_volumes(records, [])) == {(1,), (2,), (4, 5)}


def test_la_monographie_existante_de_l_isbn_est_reprise():
    existing = [ExistingMonograph(10, "proceedings of icbbm", _I1, None, None)]
    volumes = group_volumes([_record(1, isbns=(_I1,))], existing)
    assert volumes[0].monograph_ids == (10,)


def test_deux_monographies_existantes_reunies_par_un_enregistrement():
    existing = [
        ExistingMonograph(10, "proceedings of icbbm", _I1, None, None),
        ExistingMonograph(11, "proceedings of icbbm", None, _E1, None),
    ]
    volumes = group_volumes([_record(1, isbns=(_I1,), eisbns=(_E1,))], existing)
    assert volumes[0].monograph_ids == (10, 11)


def test_la_monographie_sans_isbn_du_meme_editeur_passe_avant_celle_sans_editeur():
    existing = [
        ExistingMonograph(10, "proceedings of icbbm", None, None, None),
        ExistingMonograph(11, "proceedings of icbbm", None, None, 7),
    ]
    volumes = group_volumes([_record(1, publisher_id=7)], existing)
    assert volumes[0].monograph_ids == (11,)


def test_un_enregistrement_sans_editeur_rejoint_la_monographie_sans_isbn_de_son_titre():
    """Cas réel : HAL ne donne pas l'éditeur d'un livre de Classiques Garnier."""
    existing = [ExistingMonograph(10, "proceedings of icbbm", None, None, 14001)]
    assert group_volumes([_record(1)], existing)[0].monograph_ids == (10,)


def test_un_volume_sans_titre_ni_monographie_existante_est_ecarte():
    assert group_volumes([_record(1, None, isbns=(_I1,))], []) == []
