"""Tests de la lecture des notices Sudoc de publications en série (`domain.sources.sudoc`)."""

from domain.sources.sudoc import MarcField, SudocSerialRecord, Support, parse_sudoc_serial_record


def _field(tag: str, *subfields: tuple[str, str], ind1: str = "#", ind2: str = "#") -> MarcField:
    return MarcField(tag, ind1, ind2, tuple(subfields))


class TestParseSudocSerialRecord:
    def test_electronic_record(self):
        """Notice électronique de la revue Hermès : ISSN-L et ISSN de l'autre support."""
        record = parse_sudoc_serial_record(
            "122563522",
            [
                _field("011", ("a", "1963-1006"), ("f", "0767-9513")),
                _field("135", ("a", "dr|||||||||||"), ind1=" ", ind2=" "),
                _field("182", ("c", "c")),
                _field("182", ("a", "b"), ind2="1"),
                _field("200", ("a", "Hermès")),
                _field(
                    "452", ("0", "039773515"), ("t", "Hermès (Paris. 1988)"), ("x", "0767-9513")
                ),
            ],
        )
        assert record == SudocSerialRecord(
            ppn="122563522",
            issn="1963-1006",
            issnl="0767-9513",
            cancelled_issns=(),
            support=Support.ELECTRONIC,
            other_support_issns=("0767-9513",),
            title="Hermès",
        )

    def test_print_record_with_cancelled_issn(self):
        record = parse_sudoc_serial_record(
            "038758717",
            [
                _field("011", ("a", "0028-0836"), ("f", "0028-0836"), ("y", "0302-2889")),
                _field("182", ("c", "n")),
                _field("200", ("a", "Nature")),
            ],
        )
        assert record.support is Support.PRINT
        assert record.cancelled_issns == ("0302-2889",)
        assert record.other_support_issns == ()

    def test_missing_fields(self):
        record = parse_sudoc_serial_record("1", [])
        assert record == SudocSerialRecord(
            ppn="1",
            issn=None,
            issnl=None,
            cancelled_issns=(),
            support=None,
            other_support_issns=(),
            title=None,
        )

    def test_invalid_issn_is_ignored(self):
        record = parse_sudoc_serial_record("1", [_field("011", ("a", "1234-5678"))])
        assert record.issn is None

    def test_unknown_mediation_code_gives_no_support(self):
        record = parse_sudoc_serial_record("1", [_field("182", ("c", "s"))])
        assert record.support is None
