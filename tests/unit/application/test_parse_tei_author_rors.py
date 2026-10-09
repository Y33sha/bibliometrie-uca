"""Tests du parseur TEI HAL (ROR des structures d'affiliation par auteur)."""

from application.pipeline.normalize.normalize_hal import parse_tei_author_rors

_TEI = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body><listBibl><biblFull>
      <titleStmt>
        <author role="aut">
          <persName><surname>Chi</surname></persName>
          <affiliation ref="#struct-1"/>
          <affiliation ref="#struct-2"/>
          <affiliation ref="#struct-3"/>
        </author>
        <author role="aut"><persName><surname>Breul</surname></persName></author>
        <author role="aut">
          <persName><surname>Peyras</surname></persName>
          <affiliation ref="#struct-2"/>
        </author>
      </titleStmt>
    </biblFull></listBibl></body>
    <back>
      <listOrg type="structures">
        <org type="laboratory" xml:id="struct-1">
          <idno type="RNSR">199412376H</idno>
          <idno type="ROR">https://ror.org/03vgfxd91</idno>
        </org>
        <org type="institution" xml:id="struct-2">
          <idno type="ROR">https://ror.org/035xkbk20</idno>
        </org>
        <org type="laboratory" xml:id="struct-3">
          <idno type="IdRef">162152442</idno>
        </org>
      </listOrg>
    </back>
  </text>
</TEI>"""


def test_ror_des_structures_de_chaque_auteur_dans_l_ordre():
    assert parse_tei_author_rors(_TEI) == [
        ["https://ror.org/03vgfxd91", "https://ror.org/035xkbk20"],
        [],
        ["https://ror.org/035xkbk20"],
    ]


def test_tei_absent_ou_mal_forme():
    assert parse_tei_author_rors(None) == []
    assert parse_tei_author_rors("<not-xml>") == []
