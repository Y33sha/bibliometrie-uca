"""Tests unitaires de `domain.normalize.drop_flattened_mathml`, sur des titres Crossref réels."""

from domain.normalize import clean_title, drop_flattened_mathml


def test_symboles_mathml_apres_la_formule():
    # 10.1140/epjc/s10052-017-5151-8
    title = (
        "Study of charmonium production in \n                $${b} $$\n"
        "                    b\n              -hadron decays and first evidence for the decay \n"
        "                $${{{B}} ^0_{{s}}} \\!\\rightarrow \\phi \\phi \\phi $$\n"
        "                          B\n                        s\n                        0\n"
        "                      →\n                      ϕ"
    )
    assert clean_title(drop_flattened_mathml(title)) == (
        "Study of charmonium production in $${b} $$ -hadron decays and first evidence"
        " for the decay $${{{B}} ^0_{{s}}} \\!\\rightarrow \\phi \\phi \\phi $$"
    )


def test_symboles_mathml_avant_la_formule():
    # 10.1007/jhep04(2017)162
    title = (
        "Evidence for the two-body charmless baryonic decay \n                      B\n"
        "                      +\n                    →\n                    p\n"
        "                $$ {B}^{+}\\to p\\overline{\\varLambda} $$"
    )
    assert clean_title(drop_flattened_mathml(title)) == (
        "Evidence for the two-body charmless baryonic decay $$ {B}^{+}\\to p\\overline{\\varLambda} $$"
    )


def test_formule_en_debut_de_ligne_garde_le_texte_moins_indente():
    # 10.1007/s40879-017-0185-x : la ligne qui suit la formule a l'indentation du bloc.
    title = (
        "Powers of Jacobi triple product, Cohen’s numbers and the Ramanujan \n$${\\Delta }$$\n"
        "                \n                    \n                        Δ\n"
        "                    \n                \n            -function"
    )
    assert clean_title(drop_flattened_mathml(title)) == (
        "Powers of Jacobi triple product, Cohen’s numbers and the Ramanujan $${\\Delta }$$ -function"
    )


def test_titre_sur_une_ligne_garde_ses_symboles():
    # Aucun repère d'indentation.
    title = "Study of charmonium production in $${b} $$ b -hadron decays"
    assert drop_flattened_mathml(title) == title


def test_les_espaces_insecables_restent():
    assert drop_flattened_mathml(" Les pratiques\xa0: une étude !\n") == (
        "Les pratiques\xa0: une étude !"
    )


def test_un_titre_blanc_devient_vide():
    assert drop_flattened_mathml(" \n   \n") == ""
