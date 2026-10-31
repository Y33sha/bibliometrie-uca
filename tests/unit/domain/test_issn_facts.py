"""Faits sur un ISSN tirés de sa notice Sudoc (`domain.serials.issn_facts`)."""

from domain.serials.issn_facts import IssnFacts, IssnLink, IssnLinkType, read_sudoc_record
from domain.serials.issns import IssnStatus, IssnSupport
from domain.sources.sudoc import SudocSerialRecord


def _record(**fields) -> SudocSerialRecord:
    values = {
        "ppn": "1",
        "issn": "0028-0836",
        "issnl": "0028-0836",
        "cancelled_issns": (),
        "support": IssnSupport.PRINT,
        "other_support_issns": (),
        "title": "Nature",
    }
    return SudocSerialRecord(**(values | fields))


def test_sans_notice_sudoc_l_issn_est_non_verifie():
    reading = read_sudoc_record("1234-5679", None)
    assert reading.facts == (IssnFacts("1234-5679", None, None, IssnStatus.UNVERIFIED),)
    assert (reading.links, reading.title, reading.issnl) == ((), None, None)


def test_notice_de_l_issn_lu():
    reading = read_sudoc_record("0028-0836", _record(other_support_issns=("1476-4687",)))
    assert reading.facts == (
        IssnFacts("0028-0836", "0028-0836", IssnSupport.PRINT, IssnStatus.ACTIVE),
    )
    assert (reading.title, reading.issnl) == ("Nature", "0028-0836")
    assert reading.other_support_issns == ("1476-4687",)


def test_issn_annule_rejoint_l_issn_l_de_la_notice():
    """Cas réel : la notice Sudoc de Nature annule l'ISSN 0302-2889."""
    reading = read_sudoc_record("0302-2889", _record(cancelled_issns=("0302-2889",)))
    assert reading.facts == (
        IssnFacts("0302-2889", "0028-0836", None, IssnStatus.CANCELLED),
        IssnFacts("0028-0836", "0028-0836", IssnSupport.PRINT, IssnStatus.ACTIVE),
    )


def test_liens_orientes_du_titre_precedent_vers_le_suivant():
    reading = read_sudoc_record(
        "0028-0836",
        _record(
            continues=("1111-1111",),
            continued_by=("2222-2222",),
            supplements=("3333-3333",),
            supplement_of=("4444-4444",),
        ),
    )
    assert reading.links == (
        IssnLink("1111-1111", "0028-0836", IssnLinkType.CONTINUED_BY),
        IssnLink("0028-0836", "2222-2222", IssnLinkType.CONTINUED_BY),
        IssnLink("0028-0836", "3333-3333", IssnLinkType.SUPPLEMENT),
        IssnLink("4444-4444", "0028-0836", IssnLinkType.SUPPLEMENT),
    )


def test_un_lien_vers_soi_meme_est_ecarte():
    reading = read_sudoc_record("0028-0836", _record(continued_by=("0028-0836",)))
    assert reading.links == ()
