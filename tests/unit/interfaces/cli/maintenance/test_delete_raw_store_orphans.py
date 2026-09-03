"""Élagage des payloads archivés devenus orphelins.

L'archive des réponses des sources ne fait que croître : la normalisation y dépose, jamais n'en retire. Au fil des ré-imports et des purges, des payloads y subsistent sans ligne correspondante en attente de traitement. Le script confronte les clés de l'archive à ce que la base référence, et supprime le reste.

L'opération est destructrice, d'où le mode simulation, qui compte sans rien retirer. Sa réversibilité tient à ce que la base reste la source de vérité : un payload supprimé est ré-archivé au passage suivant s'il revient.
"""

import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from interfaces.cli.maintenance import delete_raw_store_orphans as module
from interfaces.cli.maintenance.delete_raw_store_orphans import main


class _FakeStore:
    """Archive dont on connaît les clés par source, et qui retient les suppressions."""

    def __init__(self, cles: dict[str, list[str]], deja_disparues: set[str] = frozenset()) -> None:
        self._cles = cles
        self._deja_disparues = deja_disparues
        self.supprimees: list[tuple[str, str]] = []

    def iter_keys(self, source: str):
        return iter(self._cles.get(source, []))

    def delete(self, source: str, key: str) -> bool:
        self.supprimees.append((source, key))
        return key not in self._deja_disparues


@pytest.fixture
def lancer(tmp_path, monkeypatch):
    """Monte une arborescence d'archive et lance le script dessus."""

    @contextmanager
    def _contexte():
        yield object()

    def _lancer(cles_par_source, referencees, *arguments, racine=None, deja_disparues=frozenset()):
        for source in cles_par_source:
            (tmp_path / source).mkdir(exist_ok=True)
        store = _FakeStore(cles_par_source, deja_disparues)
        monkeypatch.setattr(module, "get_raw_store", lambda uri: store)
        monkeypatch.setattr(
            module, "fetch_existing_source_ids", lambda conn, source: referencees.get(source, set())
        )
        monkeypatch.setattr(module, "get_sync_engine", lambda: SimpleNamespace(connect=_contexte))
        monkeypatch.setattr(
            sys,
            "argv",
            ["delete_raw_store_orphans", "--root", str(racine or tmp_path), *arguments],
        )
        return main(), store

    return _lancer


def test_seuls_les_payloads_sans_reference_sont_supprimes(lancer):
    code, store = lancer({"hal": ["hal-1", "hal-2", "hal-3"]}, {"hal": {"hal-1", "hal-3"}})

    assert code == 0
    assert store.supprimees == [("hal", "hal-2")]


def test_simulation_ne_supprime_rien(lancer):
    code, store = lancer({"hal": ["hal-1"]}, {"hal": set()}, "--dry-run")

    assert code == 0
    assert store.supprimees == []


def test_une_seule_source_visee(lancer):
    """Les autres sources de l'archive ne sont pas parcourues."""
    code, store = lancer(
        {"hal": ["hal-1"], "openalex": ["W1"]}, {"hal": set(), "openalex": set()}, "--source", "hal"
    )

    assert code == 0
    assert store.supprimees == [("hal", "hal-1")]


def test_toutes_les_sources_de_l_archive_parcourues(lancer):
    code, store = lancer({"hal": ["hal-1"], "openalex": ["W1"]}, {"hal": set(), "openalex": set()})

    assert code == 0
    assert sorted(store.supprimees) == [("hal", "hal-1"), ("openalex", "W1")]


def test_archive_introuvable(lancer, tmp_path):
    code, store = lancer({}, {}, racine=tmp_path / "absente")

    assert code == 1
    assert store.supprimees == []


def test_payload_deja_disparu_du_disque(lancer, caplog):
    """Un fichier retiré entre le relevé et la suppression n'est pas compté comme supprimé."""
    import logging

    with caplog.at_level(logging.INFO):
        code, store = lancer({"hal": ["hal-1", "hal-2"]}, {"hal": set()}, deja_disparues={"hal-1"})

    assert code == 0
    assert len(store.supprimees) == 2  # les deux tentatives ont eu lieu
    assert "1 orphelins supprimés (2 détectés)" in caplog.text
