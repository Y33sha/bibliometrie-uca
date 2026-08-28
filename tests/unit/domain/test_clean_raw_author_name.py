"""Tests unitaires de `domain.normalize.clean_raw_author_name`.

Certaines signatures OpenAlex portent un identifiant de source recopié dans le nom (« Emmanuel Moreau (1278759) »). Le nettoyage doit retirer ce parasite sans toucher aux noms légitimes.
"""

from __future__ import annotations

import pytest

from domain.normalize import clean_raw_author_name
from domain.persons.name_matching import parse_raw_author_name


class TestCleanRawAuthorName:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            # Cas cible : identifiant numérique parenthésé en fin de nom.
            ("Emmanuel Moreau (1278759)", "Emmanuel Moreau"),
            ("H. Ouerdane (2281606)", "H. Ouerdane"),
            ("Jean-Marc A. Lobaccaro (9740193)", "Jean-Marc A. Lobaccaro"),
            # Identifiant au milieu de la chaîne.
            ("Emmanuel (123) Moreau", "Emmanuel Moreau"),
            # Aucun parasite : nom inchangé.
            ("Emmanuel Moreau", "Emmanuel Moreau"),
            ("Chiari, Sophie", "Chiari, Sophie"),
            ("", ""),
            # Parenthèses non numériques : préservées (ce n'est pas un identifiant).
            ("Smith (Jr.)", "Smith (Jr.)"),
            ("Durand (né Martin)", "Durand (né Martin)"),
            # Balisage et entités déposés dans la signature : retirés.
            ("<i>Emmanuel Moreau</i>", "Emmanuel Moreau"),
            ("Fran&ccedil;ois Durand", "François Durand"),
        ],
    )
    def test_clean(self, raw: str, expected: str) -> None:
        assert clean_raw_author_name(raw) == expected

    def test_parse_ignores_parenthesized_id(self) -> None:
        # Sans nettoyage, le token « (1278759) » deviendrait le nom de famille.
        assert parse_raw_author_name("Emmanuel Moreau (1278759)") == ("Moreau", "Emmanuel")
