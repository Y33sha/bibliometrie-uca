"""Saisie de l'administration sur une revue : champs appliqués et champs saisis à la main."""

import pytest

from domain.errors import ValidationError
from domain.serials.issns import IssnSupport, SerialIssn
from domain.serials.serial import ManualField, OaModel, Serial, SerialType


def _serial() -> Serial:
    return Serial(
        id=1,
        title="Nature",
        serial_type=SerialType.JOURNAL,
        oa_model=OaModel.FULL_OA,
    )


class TestSerialEdit:
    def test_resubmitted_values_are_not_manual(self):
        """Le formulaire renvoie tous les champs : seul un champ modifié devient saisi à la main."""
        serial = _serial()
        assert serial.edit(title="Nature", serial_type=SerialType.JOURNAL) == frozenset()
        assert serial.manual_fields == frozenset()

    def test_changed_fields_become_manual(self):
        serial = _serial()
        changed = serial.edit(title="Nature Medicine", oa_model=None)
        assert changed == {ManualField.TITLE, ManualField.OA_MODEL}
        assert (serial.title, serial.oa_model) == ("Nature Medicine", None)
        assert serial.manual_fields == changed

    def test_issns_are_normalized(self):
        serial = _serial()
        serial.edit(issns=[SerialIssn(issn="14764687", support=IssnSupport.ELECTRONIC)])
        assert [i.issn for i in serial.issns] == ["1476-4687"]
        assert serial.manual_fields == {ManualField.ISSNS}

    def test_invalid_issn_is_refused(self):
        with pytest.raises(ValidationError):
            _serial().edit(issns=[SerialIssn(issn="1234-5678")])

    def test_is_academic_is_not_a_manual_field(self):
        serial = _serial()
        assert serial.edit(is_academic=False) == frozenset()
        assert serial.is_academic is False
