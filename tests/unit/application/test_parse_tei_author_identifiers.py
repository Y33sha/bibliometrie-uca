"""Tests du parseur TEI HAL (ORCID/IdRef/idhal par auteur)."""

from application.pipeline.normalize.normalize_hal import parse_tei_author_identifiers


def _tei(authors_xml: str) -> str:
    """Enveloppe un bloc <author> dans un TEI minimal valide."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text><body><listBibl><biblFull>
    <titleStmt>
      {authors_xml}
    </titleStmt>
  </biblFull></listBibl></body></text>
</TEI>"""


def test_returns_empty_when_xml_missing_or_malformed():
    assert parse_tei_author_identifiers(None) == []
    assert parse_tei_author_identifiers("") == []
    assert parse_tei_author_identifiers("<not-xml>") == []


def test_returns_empty_list_when_no_titlestmt():
    xml = '<?xml version="1.0"?><TEI xmlns="http://www.tei-c.org/ns/1.0"><text/></TEI>'
    assert parse_tei_author_identifiers(xml) == []


def test_strips_orcid_and_idref_url_prefixes():
    xml = _tei("""
      <author>
        <persName><forename>Cédric</forename><surname>Delattre</surname></persName>
        <idno type="idhal" notation="string">cedric-delattre</idno>
        <idno type="ORCID">https://orcid.org/0000-0003-3605-1929</idno>
        <idno type="IDREF">https://www.idref.fr/099757427</idno>
      </author>
    """)
    assert parse_tei_author_identifiers(xml) == [
        {"idhal": "cedric-delattre", "orcid": "0000-0003-3605-1929", "idref": "099757427"}
    ]


def test_preserves_author_positions_with_gaps():
    """Les auteurs sans identifiant gardent une entrée vide à leur position."""
    xml = _tei("""
      <author><persName><forename>A</forename><surname>Alpha</surname></persName></author>
      <author>
        <persName><forename>B</forename><surname>Beta</surname></persName>
        <idno type="ORCID">https://orcid.org/0000-0000-0000-0001</idno>
      </author>
      <author><persName><forename>C</forename><surname>Gamma</surname></persName></author>
    """)
    result = parse_tei_author_identifiers(xml)
    assert len(result) == 3
    assert result[0] == {}
    assert result[1] == {"orcid": "0000-0000-0000-0001"}
    assert result[2] == {}


def test_ignores_unknown_idno_types():
    """Seuls ORCID, IDREF et IDHAL sont extraits ; les autres types sont ignorés."""
    xml = _tei("""
      <author>
        <persName><forename>X</forename><surname>Doe</surname></persName>
        <idno type="halauthorid">1234-5678</idno>
        <idno type="GOOGLE SCHOLAR">https://scholar.google.fr/...</idno>
        <idno type="ORCID">0000-0000-0000-0002</idno>
      </author>
    """)
    assert parse_tei_author_identifiers(xml) == [{"orcid": "0000-0000-0000-0002"}]


def test_idno_type_is_case_insensitive():
    xml = _tei("""
      <author>
        <persName><forename>Y</forename><surname>Doe</surname></persName>
        <idno type="orcid">0000-0000-0000-0003</idno>
        <idno type="idref">123456789</idno>
      </author>
    """)
    assert parse_tei_author_identifiers(xml) == [
        {"orcid": "0000-0000-0000-0003", "idref": "123456789"}
    ]


def test_empty_idno_values_are_skipped():
    xml = _tei("""
      <author>
        <persName><forename>Z</forename><surname>Doe</surname></persName>
        <idno type="ORCID"></idno>
        <idno type="IDREF">   </idno>
        <idno type="idhal" notation="string">z-doe</idno>
      </author>
    """)
    assert parse_tei_author_identifiers(xml) == [{"idhal": "z-doe"}]


def test_idhal_keeps_only_string_notation():
    """HAL emet souvent deux <idno type="idhal"> par auteur :
    notation="string" (le slug `prenom-nom`, vrai idhal) et
    notation="numeric" (le hal_person_id, ré-étiqueté idhal). Seul
    notation="string" doit être capturé sous la clé `idhal`."""
    xml = _tei("""
      <author>
        <persName><forename>Pascal</forename><surname>André</surname></persName>
        <idno type="idhal" notation="string">pascal-andre</idno>
        <idno type="idhal" notation="numeric">1195</idno>
        <idno type="halauthorid" notation="string">1502-1195</idno>
      </author>
    """)
    assert parse_tei_author_identifiers(xml) == [{"idhal": "pascal-andre"}]


def test_idhal_without_notation_is_ignored():
    """Un <idno type="idhal"> sans attribut `notation` est ignoré : on
    ne sait pas si c'est un slug ou un hal_person_id mal étiqueté.
    Le composite Solr fournit l'idhal en fallback de toute façon."""
    xml = _tei("""
      <author>
        <persName><forename>Z</forename><surname>Doe</surname></persName>
        <idno type="idhal">unknown</idno>
      </author>
    """)
    assert parse_tei_author_identifiers(xml) == [{}]
