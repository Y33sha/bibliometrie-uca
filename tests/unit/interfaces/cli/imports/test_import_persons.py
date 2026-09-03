"""Import du personnel depuis un export des ressources humaines.

Le fichier vient d'un tableur : son séparateur varie, ses intitulés de colonnes aussi, et ses dates prennent tous les formats — y compris la sérialisation numérique d'Excel. La lecture s'accommode de cette variabilité ; ces tests en fixent les bornes, et ce qu'elle refuse : un fichier sans colonne de nom.
"""

import sys
from types import SimpleNamespace

import pytest

from interfaces.cli.imports import import_persons as module
from interfaces.cli.imports.import_persons import (
    import_persons,
    main,
    parse_date,
    read_csv_tsv,
    resolve_columns,
)


class TestParseDate:
    @pytest.mark.parametrize(
        ("cellule", "attendu"),
        [
            ("2024-03-15", "2024-03-15"),
            ("15/03/2024", "2024-03-15"),
            ("15-03-2024", "2024-03-15"),
            ("2024/03/15", "2024-03-15"),
        ],
    )
    def test_formats_de_date_courants(self, cellule, attendu):
        assert parse_date(cellule) == attendu

    def test_serialisation_numerique_d_un_tableur(self):
        """Un tableur exporte parfois la date en nombre de jours depuis sa propre origine."""
        assert parse_date("45366") == "2024-03-15"

    @pytest.mark.parametrize("cellule", [None, "", "   ", "hier", "99999999"])
    def test_date_illisible(self, cellule):
        assert parse_date(cellule) is None


class TestResolveColumns:
    def test_intitules_reconnus_quels_que_soient_casse_et_separateur(self):
        entetes = ["Nom", "PRÉNOM", "e-mail", "Department-Name", "role title", "Date_Debut"]

        mapping = resolve_columns(entetes)

        assert mapping["last_name"] == 0
        assert mapping["first_name"] == 1
        assert mapping["email"] == 2
        assert mapping["department_name"] == 3
        assert mapping["start_date"] == 5  # « role title » n'est pas un alias connu

    def test_colonne_absente_absente_du_mapping(self):
        assert "end_date" not in resolve_columns(["nom", "prenom"])


class TestReadCsvTsv:
    def _fichier(self, tmp_path, contenu: str, nom: str = "rh.csv"):
        chemin = tmp_path / nom
        chemin.write_text(contenu, encoding="utf-8")
        return str(chemin)

    def test_lecture_d_un_fichier_a_virgules(self, tmp_path):
        chemin = self._fichier(
            tmp_path, "nom,prenom,email\nDupont,Marie,marie@uca.fr\nDurand,Jean,jean@uca.fr\n"
        )

        lignes = read_csv_tsv(chemin)

        assert [ligne["last_name"] for ligne in lignes] == ["Dupont", "Durand"]
        assert lignes[0]["email"] == "marie@uca.fr"

    def test_lecture_d_un_fichier_a_tabulations(self, tmp_path):
        chemin = self._fichier(tmp_path, "nom\tprenom\nDupont\tMarie\nDurand\tJean\n", nom="rh.tsv")

        assert read_csv_tsv(chemin)[0]["first_name"] == "Marie"

    def test_lignes_vides_ignorees(self, tmp_path):
        chemin = self._fichier(tmp_path, "nom,prenom\nDupont,Marie\n,\nDurand,Jean\n")

        assert len(read_csv_tsv(chemin)) == 2

    def test_cellule_manquante_en_fin_de_ligne(self, tmp_path):
        """Une ligne plus courte que l'en-tête ne fait pas échouer la lecture.

        Le séparateur se devine sur les premiers milliers d'octets : une ligne amputée au-delà de cette fenêtre échappe à la détection, et c'est la lecture qui doit s'en accommoder.
        """
        completes = "".join(f"Nom{i},Prenom{i},p{i}@uca.fr\n" for i in range(300))
        chemin = self._fichier(tmp_path, f"nom,prenom,email\n{completes}Dupont,Marie\n")

        lignes = read_csv_tsv(chemin)

        assert lignes[-1]["last_name"] == "Dupont"
        assert lignes[-1]["email"] == ""

    def test_balisage_recopie_depuis_une_page_web_mis_a_plat(self, tmp_path):
        chemin = self._fichier(tmp_path, "nom,prenom\n<b>Dupont</b>,Marie\nDurand,Jean\n")

        assert read_csv_tsv(chemin)[0]["last_name"] == "Dupont"

    @pytest.mark.parametrize(
        ("contenu", "manquante"),
        [
            ("prenom,email\nMarie,m@uca.fr\nJean,j@uca.fr\n", "nom"),
            ("nom,email\nDupont,d@uca.fr\nDurand,e@uca.fr\n", "prenom"),
        ],
    )
    def test_colonne_d_identite_absente_refuse_le_fichier(self, tmp_path, contenu, manquante):
        chemin = self._fichier(tmp_path, contenu)

        with pytest.raises(ValueError, match=manquante):
            read_csv_tsv(chemin)


class _FakeConnection:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


class TestImportPersons:
    @pytest.fixture
    def personnes_importees(self, monkeypatch):
        """Retient les appels au cas d'usage, et laisse chaque test décider de leur issue."""
        appels: list[dict] = []
        issues: list = []

        def _import(last_name, first_name, **kw):
            appels.append({"last_name": last_name, "first_name": first_name, **kw})
            return issues.pop(0) if issues else module.RhImportOutcome.INSERTED

        monkeypatch.setattr(module, "import_rh_person", _import)
        monkeypatch.setattr(module, "person_repository", lambda conn: object())
        return appels, issues

    def test_personne_versee_et_transaction_close(self, personnes_importees):
        appels, _ = personnes_importees
        conn = _FakeConnection()
        records = [{"last_name": "Dupont", "first_name": "Marie", "start_date": "15/03/2024"}]

        assert import_persons(conn, records) == 1
        assert appels[0]["start_date"] == "2024-03-15"
        assert conn.commits == 1

    def test_ligne_sans_identite_ignoree(self, personnes_importees):
        appels, _ = personnes_importees
        records = [{"last_name": "Dupont", "first_name": ""}, {"last_name": "", "first_name": "J"}]

        assert import_persons(_FakeConnection(), records) == 0
        assert appels == []

    def test_doublon_non_compte(self, personnes_importees):
        _, issues = personnes_importees
        issues.append(module.RhImportOutcome.DUPLICATE)
        records = [{"last_name": "Dupont", "first_name": "Marie"}]

        assert import_persons(_FakeConnection(), records) == 0

    def test_dry_run_n_appelle_pas_le_cas_d_usage(self, personnes_importees):
        appels, _ = personnes_importees
        records = [{"last_name": "Dupont", "first_name": "Marie"}]

        assert import_persons(_FakeConnection(), records, dry_run=True) == 1
        assert appels == []

    def test_date_d_export_transmise(self, personnes_importees):
        appels, _ = personnes_importees
        records = [{"last_name": "Dupont", "first_name": "Marie"}]

        import_persons(_FakeConnection(), records, export_date="15/03/2024")

        assert appels[0]["export_date"] == "2024-03-15"

    def test_transaction_close_par_lots(self, personnes_importees):
        """Un import long commite en cours de route : sa progression survit à une interruption."""
        conn = _FakeConnection()
        records = [{"last_name": f"Nom{i}", "first_name": "X"} for i in range(500)]

        assert import_persons(conn, records) == 500
        assert conn.commits == 2  # un au 500e, un en sortie


class _FakeMainConnection:
    def __init__(self) -> None:
        self.closed = False

    def execute(self, statement):
        return SimpleNamespace(scalar_one=lambda: 42)

    def close(self) -> None:
        self.closed = True


class TestMain:
    """Le script : lecture du fichier, aperçu du contenu, puis versement — sauf en simulation."""

    @pytest.fixture
    def script(self, tmp_path, monkeypatch):
        """Prépare un fichier lisible et retient ce que le script en fait."""
        chemin = tmp_path / "rh.csv"
        chemin.write_text(
            "nom,prenom,departement\nDupont,Marie,LMBP\nDurand,Jean,LPC\n", encoding="utf-8"
        )
        conn = _FakeMainConnection()
        verses: list[list] = []
        monkeypatch.setattr(
            module, "get_sync_engine", lambda: SimpleNamespace(connect=lambda: conn)
        )
        monkeypatch.setattr(
            module,
            "import_persons",
            lambda c, records, **kw: verses.append(records) or len(records),
        )
        return SimpleNamespace(chemin=str(chemin), conn=conn, verses=verses)

    def _lancer(self, monkeypatch, *arguments):
        monkeypatch.setattr(sys, "argv", ["import_persons", *arguments])
        return main()

    def test_fichier_introuvable(self, monkeypatch, tmp_path):
        with pytest.raises(SystemExit) as sortie:
            self._lancer(monkeypatch, str(tmp_path / "absent.csv"))

        assert sortie.value.code == 1

    def test_versement_et_decompte(self, script, monkeypatch):
        self._lancer(monkeypatch, script.chemin)

        assert [r["last_name"] for r in script.verses[0]] == ["Dupont", "Durand"]
        assert script.conn.closed  # la connexion est refermée quoi qu'il arrive

    def test_simulation_ne_verse_rien(self, script, monkeypatch):
        self._lancer(monkeypatch, script.chemin, "--dry-run")

        assert script.verses == []

    def test_fichier_sans_donnee(self, tmp_path, monkeypatch):
        chemin = tmp_path / "vide.csv"
        chemin.write_text("nom,prenom\n", encoding="utf-8")
        monkeypatch.setattr(module, "read_csv_tsv", lambda f: [])
        appels: list = []
        monkeypatch.setattr(module, "get_sync_engine", lambda: appels.append(1))

        self._lancer(monkeypatch, str(chemin))

        assert appels == []  # rien à verser : la base n'est pas même ouverte
