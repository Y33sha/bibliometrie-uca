"""Tests des value objects d'identifiants personne (ORCID, IdHAL, IdRef)."""

import pytest

from domain.errors import ValidationError
from domain.persons.identifiers import ORCID, IdHAL, IdRef, compact_identifiers

# ── ORCID ──────────────────────────────────────────────────────────


class TestORCID:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("0000-0001-2345-6789", "0000-0001-2345-6789"),  # canonique
            ("0000-0001-2345-678X", "0000-0001-2345-678X"),  # checksum X
            ("0000-0001-2345-678x", "0000-0001-2345-678X"),  # x minuscule → X
            ("https://orcid.org/0000-0001-2345-6789", "0000-0001-2345-6789"),  # strip https
            ("http://orcid.org/0000-0001-2345-6789", "0000-0001-2345-6789"),  # strip http
            ("orcid.org/0000-0001-2345-6789", "0000-0001-2345-6789"),  # strip préfixe nu
            ("0000000123456789", "0000-0001-2345-6789"),  # ajoute les tirets
        ],
    )
    def test_normalizes(self, raw, expected):
        assert ORCID(raw).value == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",  # vide
            "0000-0001-2345",  # trop court
            "0000-000A-2345-6789",  # corps non numérique
            "garbage",  # forme invalide
        ],
    )
    def test_raises_on_invalid(self, raw):
        with pytest.raises(ValidationError):
            ORCID(raw)

    def test_try_parse_none(self):
        assert ORCID.try_parse(None) is None

    def test_try_parse_invalid(self):
        assert ORCID.try_parse("not an orcid") is None

    def test_try_parse_valid(self):
        assert ORCID.try_parse("0000-0001-2345-6789") is not None


# ── IdHAL ──────────────────────────────────────────────────────────


class TestIdHAL:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("jean-dupont", "jean-dupont"),  # slug
            ("jdupont", "jdupont"),  # slug court
            ("123456", "123456"),  # legacy numérique (idHal_i)
            ("Jean-Dupont", "jean-dupont"),  # minuscules
            ("  jean-dupont  ", "jean-dupont"),  # strip whitespace
        ],
    )
    def test_normalizes(self, raw, expected):
        assert IdHAL(raw).value == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",  # vide
            "j",  # trop court
            "-jean-dupont",  # tiret en tête
            "jean_dupont",  # underscore
            "jean.dupont",  # caractère spécial
        ],
    )
    def test_raises_on_invalid(self, raw):
        with pytest.raises(ValidationError):
            IdHAL(raw)

    def test_try_parse_none(self):
        assert IdHAL.try_parse(None) is None

    def test_try_parse_invalid(self):
        assert IdHAL.try_parse("j") is None

    def test_try_parse_valid(self):
        assert IdHAL.try_parse("jean-dupont") is not None


# ── IdRef ──────────────────────────────────────────────────────────


class TestIdRef:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("252404955", "252404955"),  # PPN canonique
            ("05547854X", "05547854X"),  # PPN avec clé X
            ("05547854x", "05547854X"),  # x minuscule → X
            ("https://www.idref.fr/252404955/id", "252404955"),  # strip URL
            ("idref.fr/252404955", "252404955"),  # strip préfixe nu
        ],
    )
    def test_normalizes(self, raw, expected):
        assert IdRef(raw).value == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",  # vide
            "12345678",  # 8 chiffres, il manque la clé
            "1234567890",  # trop long
            "12A456789",  # lettre dans le corps
        ],
    )
    def test_raises_on_invalid(self, raw):
        with pytest.raises(ValidationError):
            IdRef(raw)


# ── compact_identifiers ─────────────────────────────────────────────


class TestCompactIdentifiers:
    def test_empty_returns_none(self):
        assert compact_identifiers() is None

    def test_all_none_returns_none(self):
        assert compact_identifiers(orcid=None, idref=None) is None

    def test_keeps_truthy_strips_falsy(self):
        result = compact_identifiers(
            orcid="0000-0001-2345-6789",
            idref=None,
            idhal="",
            researcher_id="ABC-1234",
        )
        assert result == {"orcid": "0000-0001-2345-6789", "researcher_id": "ABC-1234"}

    def test_strips_zero_int(self):
        """hal_person_id=0 (sentinelle HAL) doit être filtré comme falsy."""
        assert compact_identifiers(orcid="0000-0001-2345-6789", hal_person_id=0) == {
            "orcid": "0000-0001-2345-6789"
        }

    def test_keeps_int(self):
        assert compact_identifiers(hal_person_id=42) == {"hal_person_id": 42}
