"""Chargement du référentiel des structures HAL : alias, remontée des parents, source indisponible."""

import logging
from unittest.mock import MagicMock

from pipeline.ingestion.http.circuit_breaker import SourceUnavailableError
from pipeline.transformation.structures.hal_structures import (
    fetch_hal_structures,
    run_refresh_hal_structures,
)

_LOG = logging.getLogger("test")


def _doc(docid: int, *, parents=(), aliases=()):
    return {
        "docid": str(docid),
        "name_s": f"S{docid}",
        "type_s": "laboratory",
        "valid_s": "VALID",
        "parentDocid_i": [str(p) for p in parents],
        "aliasDocid_i": list(aliases),
    }


class _Source:
    """Référentiel HAL en mémoire : équipe 3 → laboratoire 2 → université 1 ; 9 est un alias de 2 ; 7 est introuvable."""

    def __init__(self):
        self.docs = {1: _doc(1), 2: _doc(2, parents=[1], aliases=[9]), 3: _doc(3, parents=[2])}
        self.requested: list[set[int]] = []

    def by_ids(self, ids):
        self.requested.append(set(ids))
        return [self.docs[i] for i in ids if i in self.docs]

    def by_aliases(self, ids):
        return [d for d in self.docs.values() if set(d["aliasDocid_i"]) & set(ids)]


class _Queries:
    def __init__(self, known=()):
        self.known = set(known)

    def known_ids(self, ids):
        return set(ids) & self.known


def test_remonte_les_parents_et_resout_les_alias():
    load = fetch_hal_structures({3, 9, 7}, source=_Source(), queries=_Queries())

    assert set(load.structures) == {1, 2, 3}
    assert load.aliases == {9: 2}
    assert load.not_found == {7}


def test_ne_relit_pas_un_parent_deja_dans_le_referentiel():
    source = _Source()

    load = fetch_hal_structures({3}, source=source, queries=_Queries(known={2}))

    assert set(load.structures) == {3}
    assert source.requested == [{3}]


def test_un_parent_cite_par_son_alias_est_lu_une_fois():
    source = _Source()
    source.docs[4] = _doc(4, parents=[9])

    load = fetch_hal_structures({4}, source=source, queries=_Queries())

    assert set(load.structures) == {1, 2, 4}
    assert load.aliases == {9: 2}
    assert source.requested == [{4}, {9}, {1}]


def test_source_indisponible_laisse_le_referentiel_en_l_etat():
    queries = MagicMock()
    queries.ids_to_fetch.return_value = {3}
    source = MagicMock()
    source.by_ids.side_effect = SourceUnavailableError("hal")
    conn = MagicMock()

    metrics = run_refresh_hal_structures(
        conn, source=source, queries=queries, logger=_LOG, refresh_stale=False
    )

    conn.rollback.assert_called_once()
    queries.save.assert_not_called()
    assert metrics.resume
