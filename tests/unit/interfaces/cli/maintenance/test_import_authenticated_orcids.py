"""Import des ORCID authentifiés par leur titulaire.

Le fichier associe un email à un ORCID que le chercheur a lui-même authentifié en se connectant à son compte. L'import confronte ces lignes aux personnes connues et n'authentifie que celles dont l'identité est certaine : un email inconnu ou porté par plusieurs personnes laisse la ligne de côté.

L'authentification faisant autorité sur l'identité, un ORCID déjà rattaché à quelqu'un d'autre est déplacé vers le titulaire — chaque déplacement est signalé, car il révèle en général un doublon de personne à fusionner.
"""

import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from application.ports.repositories.person_repository import AuthenticateOrcidOutcome
from interfaces.cli.maintenance import import_authenticated_orcids as module
from interfaces.cli.maintenance.import_authenticated_orcids import (
    _load_rows,
    find_reassignments,
    main,
    plan_authentications,
)

_ORCID = "0000-0002-1825-0097"
_AUTRE_ORCID = "0000-0001-5109-3700"


class TestLoadRows:
    def _fichier(self, tmp_path, contenu: str):
        chemin = tmp_path / "authenticated_orcids.csv"
        chemin.write_text(contenu, encoding="utf-8")
        return chemin

    def test_lignes_email_orcid(self, tmp_path):
        chemin = self._fichier(tmp_path, f"marie@uca.fr,{_ORCID}\njean@uca.fr,{_AUTRE_ORCID}\n")

        assert _load_rows(chemin) == [("marie@uca.fr", _ORCID), ("jean@uca.fr", _AUTRE_ORCID)]

    def test_lignes_incompletes_ignorees(self, tmp_path):
        chemin = self._fichier(tmp_path, f"marie@uca.fr,{_ORCID}\n\njean@uca.fr\n")

        assert _load_rows(chemin) == [("marie@uca.fr", _ORCID)]

    def test_email_vide_ignore(self, tmp_path):
        chemin = self._fichier(tmp_path, f"  ,{_ORCID}\n")

        assert _load_rows(chemin) == []

    def test_caracteres_invisibles_d_un_tableur_retires(self, tmp_path):
        """Un fichier composé dans un tableur glisse des espaces insécables, qui feraient échouer le rapprochement en silence."""
        chemin = self._fichier(tmp_path, f" marie@uca.fr , {_ORCID}\n")

        assert _load_rows(chemin) == [("marie@uca.fr", _ORCID)]


class TestPlanAuthentications:
    def test_email_resolu_donne_une_authentification(self):
        plan = plan_authentications([("marie@uca.fr", _ORCID)], {"marie@uca.fr": [7]})

        assert plan.entries == [(7, _ORCID)]
        assert (plan.malformed, plan.unmatched, plan.ambiguous) == ([], [], [])

    def test_rapprochement_insensible_a_la_casse(self):
        plan = plan_authentications([("Marie@UCA.fr", _ORCID)], {"marie@uca.fr": [7]})

        assert plan.entries == [(7, _ORCID)]

    def test_orcid_inexploitable_ecarte(self):
        plan = plan_authentications([("marie@uca.fr", "pas-un-orcid")], {"marie@uca.fr": [7]})

        assert plan.entries == []
        assert len(plan.malformed) == 1

    def test_email_inconnu_ecarte(self):
        plan = plan_authentications([("inconnu@uca.fr", _ORCID)], {"marie@uca.fr": [7]})

        assert plan.entries == []
        assert plan.unmatched == ["inconnu@uca.fr"]

    def test_email_partage_par_plusieurs_personnes_ecarte(self):
        """L'identité visée est indécidable : mieux vaut ne rien authentifier que se tromper de personne."""
        plan = plan_authentications([("marie@uca.fr", _ORCID)], {"marie@uca.fr": [7, 9]})

        assert plan.entries == []
        assert len(plan.ambiguous) == 1


class TestFindReassignments:
    def test_orcid_detenu_par_une_autre_personne(self):
        deplacements = find_reassignments([(7, _ORCID)], {_ORCID: (3,)})

        assert deplacements == [(_ORCID, 3, 7)]

    def test_orcid_deja_sur_la_bonne_personne(self):
        assert find_reassignments([(7, _ORCID)], {_ORCID: (7,)}) == []

    def test_orcid_encore_detenu_par_personne(self):
        assert find_reassignments([(7, _ORCID)], {}) == []


class _FakeRepo:
    def __init__(self, emails, detenteurs) -> None:
        self._emails = emails
        self._detenteurs = detenteurs

    def map_rh_emails_to_person_ids(self) -> dict[str, list[int]]:
        return self._emails

    def find_identifier_holders(self, kind: str, values) -> dict[str, tuple[int, ...]]:
        return {v: self._detenteurs[v] for v in values if v in self._detenteurs}


class TestMain:
    @pytest.fixture
    def lancer(self, tmp_path, monkeypatch):
        """Écrit un fichier d'ORCID authentifiés et lance le script dessus."""

        @contextmanager
        def _contexte(valeur):
            yield valeur

        def _lancer(lignes, *, emails=None, detenteurs=None, arguments=()):
            chemin = tmp_path / "authenticated_orcids.csv"
            chemin.write_text("".join(f"{e},{o}\n" for e, o in lignes), encoding="utf-8")
            authentifies: list[list] = []
            monkeypatch.setattr(
                module,
                "get_sync_engine",
                lambda: SimpleNamespace(
                    connect=lambda: _contexte(object()), begin=lambda: _contexte(object())
                ),
            )
            monkeypatch.setattr(
                module,
                "person_repository",
                lambda conn: _FakeRepo(emails or {}, detenteurs or {}),
            )
            monkeypatch.setattr(
                module,
                "authenticate_orcids",
                lambda entries, *, repo: (
                    authentifies.append(entries) or dict.fromkeys(AuthenticateOrcidOutcome, 0)
                ),
            )
            monkeypatch.setattr(
                sys, "argv", ["import_authenticated_orcids", "--file", str(chemin), *arguments]
            )
            return main(), authentifies

        return _lancer

    def test_authentifie_les_lignes_resolues(self, lancer):
        code, authentifies = lancer([("marie@uca.fr", _ORCID)], emails={"marie@uca.fr": [7]})

        assert code == 0
        assert authentifies == [[(7, _ORCID)]]

    def test_rien_a_authentifier(self, lancer):
        """Aucune ligne exploitable : le script sort sans rien écrire."""
        code, authentifies = lancer([("inconnu@uca.fr", _ORCID)], emails={})

        assert code == 0
        assert authentifies == []

    def test_simulation_n_ecrit_rien(self, lancer):
        code, authentifies = lancer(
            [("marie@uca.fr", _ORCID)], emails={"marie@uca.fr": [7]}, arguments=["--dry-run"]
        )

        assert code == 0
        assert authentifies == []

    def test_lignes_ecartees_et_deplacement_signales(self, lancer, caplog):
        """Chaque motif d'écart, et chaque déplacement d'ORCID, laisse une trace dans le journal."""
        code, authentifies = lancer(
            [
                ("marie@uca.fr", _ORCID),
                ("mauvais@uca.fr", "pas-un-orcid"),
                ("inconnu@uca.fr", _AUTRE_ORCID),
                ("partage@uca.fr", _AUTRE_ORCID),
            ],
            emails={"marie@uca.fr": [7], "partage@uca.fr": [1, 2]},
            detenteurs={_ORCID: (3,)},
        )

        assert code == 0
        assert authentifies == [[(7, _ORCID)]]
        journal = caplog.text
        assert "malformé" in journal
        assert "inconnu" in journal
        assert "ambigu" in journal
        assert "déplacement" in journal
