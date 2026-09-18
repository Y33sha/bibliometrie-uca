"""Tests de la lecture des notices Sudoc de publications en série (`domain.sources.sudoc`)."""

from domain.sources.sudoc import MarcField, SudocSerialRecord, Support, parse_sudoc_serial_record


def _field(tag: str, *subfields: tuple[str, str], ind1: str = "#", ind2: str = "#") -> MarcField:
    return MarcField(tag, ind1, ind2, tuple(subfields))


class TestParseSudocSerialRecord:
    def test_online_record(self):
        """Notice en ligne de la revue Hermès : ISSN-L, ISSN de l'autre support, titre précédent."""
        record = parse_sudoc_serial_record(
            "122563522",
            [
                _field("011", ("a", "1963-1006"), ("f", "0767-9513")),
                _field("135", ("a", "dr|||||||||||"), ind1=" ", ind2=" "),
                _field("182", ("c", "c")),
                _field("183", ("a", "ceb")),
                _field("200", ("a", "Hermès")),
                _field("430", ("0", "001029967"), ("t", "Cahiers STS (Paris)"), ("x", "0762-5332")),
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
            preceding_issns=("0762-5332",),
            succeeding_issns=(),
            title="Hermès",
            continuation_issns=("0762-5332",),
        )

    def test_title_links_other_than_continuation(self):
        """Une scission (`446`) et une absorption (`434`) lient des titres sans continuer la revue ; `421` et `422` désignent un supplément."""
        record = parse_sudoc_serial_record(
            "000000000",
            [
                _field("011", ("a", "0031-899X")),
                _field("421", ("x", "0373-7934")),
                _field("422", ("x", "0001-5385")),
                _field("434", ("x", "0021-9606")),
                _field("446", ("x", "2469-9926"), ("x", "2469-9950")),
            ],
        )
        assert record.preceding_issns == ("0021-9606",)
        assert record.succeeding_issns == ("2469-9926", "2469-9950")
        assert record.continuation_issns == ()
        assert record.supplement_issns == ("0373-7934", "0001-5385")

    def test_print_record_with_cancelled_issn_and_successor(self):
        record = parse_sudoc_serial_record(
            "038758717",
            [
                _field("011", ("a", "0028-0836"), ("f", "0028-0836"), ("y", "0302-2889")),
                _field("182", ("c", "n")),
                _field("183", ("a", "ngb")),
                _field("200", ("a", "Nature")),
                _field("440", ("x", "1476-4687")),
            ],
        )
        assert record.support is Support.PRINT
        assert record.cancelled_issns == ("0302-2889",)
        assert record.succeeding_issns == ("1476-4687",)
        assert record.continuation_issns == ("1476-4687",)

    def test_cd_rom_record(self):
        """Le Sudoc code « électronique » un CD-ROM comme une ressource en ligne (`182$c`) : `183$a` les distingue."""
        record = parse_sudoc_serial_record(
            "040645134", [_field("182", ("c", "c")), _field("183", ("a", "cde"))]
        )
        assert record.support is Support.OTHER

    def test_cd_rom_named_in_title(self):
        """Cas réel : la notice « The L & O on CD-ROM » est codée comme une ressource en ligne."""
        record = parse_sudoc_serial_record(
            "118354507",
            [
                _field("182", ("c", "c")),
                _field("135", ("a", "dr|||||||||||"), ind1=" ", ind2=" "),
                _field("200", ("a", "The l & o on cd-rom")),
            ],
        )
        assert record.support is Support.OTHER

    def test_support_without_carrier_type(self):
        online = [_field("182", ("c", "c")), _field("135", ("a", "|r|||||||||||"))]
        assert parse_sudoc_serial_record("1", online).support is Support.ELECTRONIC
        assert parse_sudoc_serial_record("1", [_field("182", ("c", "c"))]).support is Support.OTHER
        assert parse_sudoc_serial_record("1", [_field("182", ("c", "n"))]).support is Support.PRINT

    def test_missing_fields(self):
        record = parse_sudoc_serial_record("1", [])
        assert record == SudocSerialRecord(
            ppn="1",
            issn=None,
            issnl=None,
            cancelled_issns=(),
            support=None,
            other_support_issns=(),
            preceding_issns=(),
            succeeding_issns=(),
            title=None,
        )

    def test_title_includes_part_number(self):
        """La notice de Physical review D porte « D » en `200$h`."""
        record = parse_sudoc_serial_record(
            "1", [_field("200", ("a", "Physical review"), ("h", "D"))]
        )
        assert record.title == "Physical review D"

    def test_support_mentioned_by_other_support_title(self):
        record = parse_sudoc_serial_record(
            "1",
            [
                _field(
                    "452", ("t", "The Journal of high energy physics (Print)"), ("x", "1126-6708")
                ),
                _field(
                    "452", ("t", "The Journal of high energy physics (CD-ROM)"), ("x", "1127-2236")
                ),
                _field("452", ("t", "Hermès (Paris. 1988)"), ("x", "0767-9513")),
            ],
        )
        assert record.other_support_hints == (
            ("1126-6708", Support.PRINT),
            ("1127-2236", Support.OTHER),
        )

    def test_invalid_issn_is_ignored(self):
        record = parse_sudoc_serial_record("1", [_field("011", ("a", "1234-5678"))])
        assert record.issn is None
