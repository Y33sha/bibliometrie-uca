"""Réinjection des payloads archivés dans `staging`, pour rejouer une normalisation.

La normalisation archive chaque payload puis vide sa colonne dans `staging` : le payload subsiste alors seulement dans l'archive. Le script le lit dans l'archive, le réinjecte et remet la ligne en attente de traitement.

Par défaut, seules les lignes présentes sont mises à jour ; une clé sans ligne correspondante est ignorée. En mode complet (`--full`), ces clés orphelines sont recréées, par exemple après une table vidée. La ligne est alors reconstruite depuis le payload seul, et l'adaptateur de la source extrait le DOI du payload.
"""

import json
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from infrastructure.raw_store import UnreadablePayloadError
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
    """L'adaptateur de la source extrait le DOI du payload."""

    @pytest.mark.parametrize(
        ("source", "payload"),
        [
            ("crossref", {"DOI": "10.1/A"}),
            ("datacite", {"id": "10.1/a"}),
            ("hal", {"halId_s": "hal-1", "doiId_s": "10.1/a"}),
        ],
    )
    def test_doi_relu_dans_le_payload(self, source, payload):
        assert _doi_for(source, payload) == "10.1/a"


_ILLISIBLE = object()
"""Payload corrompu dans l'archive : sa lecture lève `UnreadablePayloadError`."""


class _FakeStore:
    def __init__(self, payloads: dict[str, dict[str, dict]]) -> None:
        self._payloads = payloads

    def iter_keys(self, source: str):
        return iter(self._payloads.get(source, {}))

    def get(self, source: str, key: str) -> str:
        payload = self._payloads[source][key]
        if payload is _ILLISIBLE:
            raise UnreadablePayloadError(f"{source}/{key}")
        return json.dumps(payload)


class _FakeConnection:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def lancer(monkeypatch):
    """Lance le script sur une archive donnée, et enregistre les réinjections demandées."""

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
        {"hal": {"hal-1": {"halId_s": "hal-1", "doiId_s": "10.1/a"}}},
        "--sources",
        "hal",
        lignes_presentes={"hal-1"},
    )

    assert resultat.mises_a_jour == [("hal", "hal-1")]
    assert resultat.creees == []
    assert resultat.conn.commits == 1


def test_cle_sans_ligne_ignoree(lancer):
    resultat = lancer({"hal": {"hal-1": {}}}, "--sources", "hal")

    assert resultat.creees == []


def test_mode_complet_recree_les_orphelines(lancer):
    """Après une table vidée, toutes les clés sont orphelines : la ligne est reconstruite depuis le payload."""
    resultat = lancer(
        {"hal": {"hal-1": {"halId_s": "hal-1", "doiId_s": "10.1/a"}}},
        "--sources",
        "hal",
        "--full",
        creations={"hal-1"},
    )

    assert resultat.creees == [("hal", "hal-1", "10.1/a")]
    assert resultat.mises_a_jour == []


def test_filtre_par_type_de_document(lancer, monkeypatch):
    """`--doc-type` garde les clés des enregistrements sources en base de ce type."""
    monkeypatch.setattr(
        module,
        "source_ids_of_type",
        lambda conn, source, doc_type: {"hal-2"} if doc_type == "patent" else set(),
    )
    resultat = lancer(
        {"hal": {"hal-1": {}, "hal-2": {}}},
        "--sources",
        "hal",
        "--doc-type",
        "patent",
        lignes_presentes={"hal-1", "hal-2"},
    )

    assert resultat.mises_a_jour == [("hal", "hal-2")]


def test_simulation_n_ouvre_pas_la_base(lancer):
    resultat = lancer({"hal": {"hal-1": {}, "hal-2": {}}}, "--sources", "hal", "--dry-run")

    assert resultat.mises_a_jour == []
    assert resultat.conn.commits == 0


def test_transaction_close_par_lots(lancer, monkeypatch):
    """Un parcours long commite par lots : sa progression survit à une interruption."""
    monkeypatch.setattr(module, "_COMMIT_BATCH", 2)
    cles = {f"hal-{i}": {} for i in range(5)}

    resultat = lancer({"hal": cles}, "--sources", "hal", lignes_presentes=set(cles))

    assert resultat.conn.commits == 3  # deux lots pleins, puis la fermeture


def test_payload_illisible_n_interrompt_pas(lancer):
    """Un payload illisible laisse sa ligne de `staging` inchangée ; les autres clés sont réinjectées."""
    resultat = lancer(
        {"hal": {"hal-1": _ILLISIBLE, "hal-2": {}}},
        "--sources",
        "hal",
        lignes_presentes={"hal-2"},
    )

    assert resultat.mises_a_jour == [("hal", "hal-2")]
