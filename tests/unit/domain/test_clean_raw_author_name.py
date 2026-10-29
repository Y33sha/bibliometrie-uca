"""Tests unitaires de `domain.normalize.clean_raw_author_name`.

Certaines contributions sources OpenAlex contiennent un identifiant de source recopié dans le nom (« Emmanuel Moreau (1278759) »). Le nettoyage retire ce parasite et laisse intacts les noms légitimes.
"""

from __future__ import annotations

import time

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
            # Parenthèses non numériques : préservées.
            ("Smith (Jr.)", "Smith (Jr.)"),
            ("Durand (né Martin)", "Durand (né Martin)"),
            # Balisage et entités déposés dans la contribution source : retirés.
            ("<i>Emmanuel Moreau</i>", "Emmanuel Moreau"),
            ("Fran&ccedil;ois Durand", "François Durand"),
            # Année de naissance d'une forme d'autorité, et la ponctuation qu'elle laisse isolée.
            ("Candoni, Jean-François 1964-", "Candoni, Jean-François"),
            ("D'Andrea, Carlos, 1973-", "D'Andrea, Carlos"),
            ("Dupont, Jean (1920-2004)", "Dupont, Jean"),
            # Chiffre collé au nom ou en tête : renvoi d'affiliation.
            ("Sarhang Qadir Ibrahim1", "Sarhang Qadir Ibrahim"),
            ("2 Jean Dumont", "Jean Dumont"),
            # Parenthèse détachée de son contenu par le retrait des chiffres.
            (
                "Laboratoire de Recherche sur le Langage (EA 999)",
                "Laboratoire de Recherche sur le Langage (EA)",
            ),
            # Tiret, apostrophe et point d'initiale d'un nom légitime : préservés.
            ("Al- Hadithi, T. S.", "Al- Hadithi, T. S."),
            ("O'Neill, J.-P.", "O'Neill, J.-P."),
            # Nom fait seulement de chiffres (ORCID recopié) : inchangé.
            ("0000-0003-4887-7373", "0000-0003-4887-7373"),
            # Accents et lettres LaTeX : remplacés par leur caractère.
            ("Bayart, Fr\\'ed\\'eric", "Bayart, Frédéric"),
            ("Lev\\^eque, Jessica", "Levêque, Jessica"),
            ('Sch\\"afer, Uli', "Schäfer, Uli"),
            ("{\\'E}mile Besan\\c{c}on", "Émile Besançon"),
            ("Mar\\'{\\i}a J{\\o}rgensen", "María Jørgensen"),
            ("Ho\\v s\\'ek", "Hošék"),
            ("Gon\\C Calo, Ricardo", "GonÇalo, Ricardo"),
            ("Ge\\ssner, Gregor", "Geßner, Gregor"),
            # Accolades LaTeX sans commande : retirées.
            ("Geß{}ner, Gregor", "Geßner, Gregor"),
            ("{van der Berg}, Jan", "van der Berg, Jan"),
            # UTF-8 lu comme du Windows-1252 : réparé.
            ("TÃ©lesphore Sime-Ngando", "Télesphore Sime-Ngando"),
            ("NuÃ±ez LÃ³pez, Leslie", "Nuñez López, Leslie"),
            ("DelanoÃ«, Julien", "Delanoë, Julien"),
            ("Michel Peocâ€™h", "Michel Peoc’h"),
            ("FranÃ§ois, Ã‰mile", "François, Émile"),
            # UTF-8 lu comme du Latin-1 : réparé.
            ("GroÃ\x9f, Silke", "Groß, Silke"),
            ("MandiÄ\x87, Igor", "Mandić, Igor"),
            ("Posyniak, MichaÅ\x82", "Posyniak, Michał"),
            # Windows-1252 lu comme du GBK : réparé.
            ("Fran鏾is Bouchon", "François Bouchon"),
            ("M閘anie Brard", "Mélanie Brard"),
            # Lettres accentuées légitimes et nom en idéogrammes : inchangés.
            ("São João, Ângela", "São João, Ângela"),
            ("Ãlvaro Ñúñez", "Ãlvaro Ñúñez"),
            ("Wang王", "Wang王"),
            ("王小明", "王小明"),
        ],
    )
    def test_clean(self, raw: str, expected: str) -> None:
        assert clean_raw_author_name(raw) == expected

    def test_parse_ignores_parenthesized_id(self) -> None:
        # Sans nettoyage, le token « (1278759) » deviendrait le nom de famille.
        assert parse_raw_author_name("Emmanuel Moreau (1278759)") == ("Moreau", "Emmanuel")


@pytest.mark.parametrize(
    "raw",
    [
        "a" + " " * 100_000 + "b",
        "a " + "!" * 100_000 + "b",
        "<A" + "!" * 100_000,
        "<!--" * 25_000,
        "<ab" * 25_000 + ">" * 25_000,
    ],
    ids=["espaces", "ponctuation", "balise ouverte", "commentaires ouverts", "balises imbriquées"],
)
def test_long_input_cleaned_in_linear_time(raw: str) -> None:
    """Une entrée longue et répétitive se nettoie en temps linéaire : un temps quadratique dépasserait largement la borne."""
    start = time.perf_counter()
    clean_raw_author_name(raw)
    assert time.perf_counter() - start < 2
