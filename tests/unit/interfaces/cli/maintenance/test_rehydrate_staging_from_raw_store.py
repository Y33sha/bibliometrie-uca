"""Réinjection des payloads archivés, pour rejouer une normalisation.

La normalisation archive le payload d'un document puis vide la colonne qui le portait : une fois la source normalisée, le brut ne subsiste qu'à l'archive. Ce script l'y reprend et le réinjecte, en remettant la ligne en attente de traitement.

Deux régimes s'y opposent. Par défaut, seules les lignes encore présentes sont mises à jour, et une clé sans ligne correspondante est signalée. En mode complet, ces clés orphelines sont recréées — le cas d'une table vidée, où tout l'est par définition. Le document y est alors reconstruit depuis le seul payload, ce qui demande d'en ré-extraire le DOI par la logique propre à chaque source.
"""

import json
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from interfaces.cli.maintenance import rehydrate_staging_from_raw_store as module
from interfaces.cli.maintenance.rehydrate_staging_from_raw_store import (
    _doi_for,
    _parse_sources,
    main,
)


class TestParseSources:
    def test_sources_connues(self):
        assert _parse_sources("hal, openalex") == ["hal", "openalex"]

    def test_source_inconnue_arrete_le_script(self):
        with pytest.raises(SystemExit, match="inexistante"):
            _parse_sources("hal,inexistante")

    def test_liste_vide_arrete_le_script(self):
        with pytest.raises(SystemExit, match="Aucune source"):
            _parse_sources(" , ")


class TestDoiFor:
    @pytest.mark.parametrize("source", ["crossref", "datacite"])
    def test_sources_dont_l_identifiant_est_le_doi(self, source):
        """Ces sources n'ont pas d'identifiant propre : leur clé d'archive est le DOI."""
        assert _doi_for(source, "10.1/a", {}) == "10.1/a"

    def test_doi_re_extrait_du_payload(self):
        """Ailleurs, le DOI se relit dans le payload, par la logique propre à la source."""
        assert _doi_for("hal", "hal-1", {"doiId_s": "10.1/a"}) == "10.1/a"


class _FakeStore:
    def __init__(self, payloads: dict[str, dict[str, dict]]) -> None:
        self._payloads = payloads

    def iter_keys(self, source: str):
        return iter(self._payloads.get(source, {}))

    def get(self, source: str, key: str) -> str:
        return json.dumps(self._payloads[source][key])


class _FakeConnection:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def lancer(monkeypatch):
    """Lance le script sur une archive donnée, et retient les réinjections demandées."""

    @contextmanager
    def _contexte(conn):
        yield conn

    def _lancer(payloads, *arguments, lignes_presentes=frozenset(), creations=frozenset()):
        conn = _FakeConnection()
        mises_a_jour: list[tuple[str, str]] = []
        creees: list[tuple[str, str, str | None]] = []

        def _rehydrate(c, source, source_id, raw_data):
            mises_a_jour.append((source, source_id))
            return source_id in lignes_presentes

        def _rehydrate_or_create(c, source, source_id, doi, raw_data):
            creees.append((source, source_id, doi))
            return source_id in creations

        monkeypatch.setattr(module, "get_raw_store", lambda: _FakeStore(payloads))
        monkeypatch.setattr(module, "rehydrate_staging_row", _rehydrate)
        monkeypatch.setattr(module, "rehydrate_or_create_staging_row", _rehydrate_or_create)
        monkeypatch.setattr(
            module,
            "get_sync_engine",
            lambda: SimpleNamespace(connect=lambda: _contexte(conn)),
        )
        monkeypatch.setattr(sys, "argv", ["rehydrate", *arguments])
        main()
        return SimpleNamespace(conn=conn, mises_a_jour=mises_a_jour, creees=creees)

    return _lancer


def test_lignes_presentes_mises_a_jour(lancer):
    resultat = lancer(
        {"hal": {"hal-1": {"doiId_s": "10.1/a"}}},
        "--sources",
        "hal",
        lignes_presentes={"hal-1"},
    )

    assert resultat.mises_a_jour == [("hal", "hal-1")]
    assert resultat.creees == []
    assert resultat.conn.commits == 1


def test_cle_sans_ligne_signalee_et_ignoree(lancer, caplog):
    import logging

    with caplog.at_level(logging.WARNING):
        resultat = lancer({"hal": {"hal-1": {}}}, "--sources", "hal")

    assert resultat.creees == []
    assert "orpheline" in caplog.text


def test_mode_complet_recree_les_orphelines(lancer):
    """Après une table vidée, tout est orphelin : le document est reconstruit depuis le payload."""
    resultat = lancer(
        {"hal": {"hal-1": {"doiId_s": "10.1/a"}}},
        "--sources",
        "hal",
        "--full",
        creations={"hal-1"},
    )

    assert resultat.creees == [("hal", "hal-1", "10.1/a")]
    assert resultat.mises_a_jour == []


def test_mode_complet_met_a_jour_ce_qui_existe_deja(lancer, caplog):
    """Une clé dont la ligne subsiste est mise à jour, non réinsérée."""
    import logging

    with caplog.at_level(logging.INFO):
        resultat = lancer({"hal": {"hal-1": {}}}, "--sources", "hal", "--full")

    assert resultat.creees == [("hal", "hal-1", None)]
    assert "0 insérés, 1 mis à jour" in caplog.text


def test_simulation_n_ouvre_pas_la_base(lancer, caplog):
    import logging

    with caplog.at_level(logging.INFO):
        resultat = lancer({"hal": {"hal-1": {}, "hal-2": {}}}, "--sources", "hal", "--dry-run")

    assert resultat.mises_a_jour == []
    assert resultat.conn.commits == 0
    assert "hal : 2 payloads" in caplog.text


def test_transaction_close_par_lots(lancer, monkeypatch):
    """Un parcours long commite en cours de route : sa progression survit à une interruption."""
    monkeypatch.setattr(module, "_COMMIT_BATCH", 2)
    cles = {f"hal-{i}": {} for i in range(5)}

    resultat = lancer({"hal": cles}, "--sources", "hal", lignes_presentes=set(cles))

    assert resultat.conn.commits == 3  # deux lots pleins, puis la fermeture
