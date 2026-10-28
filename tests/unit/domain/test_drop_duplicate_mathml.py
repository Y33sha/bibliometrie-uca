"""Tests unitaires de `domain.normalize.drop_duplicate_mathml`, sur des extraits de résumés réels."""

from domain.normalize import drop_duplicate_mathml


def test_mathml_apres_la_formule_latex():
    # Crossref, Nature Communications : LaTeX puis MathML, avec l'indentation du XML déposé.
    abstract = (
        "contains two charm quarks, a\n                      \n"
        "                        $$\\overline{{{{{u}}}}}$$\n"
        '                        <mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML">\n'
        "                          <mml:mover>\n"
        "                            <mml:mrow><mml:mi>u</mml:mi></mml:mrow>\n"
        "                            <mml:mo>¯</mml:mo>\n"
        "                          </mml:mover>\n"
        "                        </mml:math>\n"
        "                    and a"
    )
    assert drop_duplicate_mathml(abstract) == (
        "contains two charm quarks, a\n                      \n"
        "                        $$\\overline{{{{{u}}}}}$$\n"
        "                    and a"
    )


def test_mathml_apres_la_formule_latex_sur_une_ligne():
    # OpenAlex : le résumé reconstruit sépare chaque mot d'un espace.
    abstract = (
        "collision data at $$ \\sqrt{s} $$ "
        '<mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML"> <mml:msqrt> <mml:mi>s</mml:mi> '
        "</mml:msqrt> </mml:math> = 13 TeV"
    )
    assert drop_duplicate_mathml(abstract) == "collision data at $$ \\sqrt{s} $$ = 13 TeV"


def test_formules_latex_consecutives_puis_leurs_versions_mathml():
    # 10.1007/jhep07(2023)069 : trois formules LaTeX, puis leurs trois versions MathML.
    abstract = (
        "measured: $$ \\sigma_1 $$$$ \\sigma_2 $$$$ \\sigma_3 $$"
        "<mml:math><mml:mi>σ</mml:mi><mml:mn>1</mml:mn></mml:math>"
        "<mml:math><mml:mi>σ</mml:mi><mml:mn>2</mml:mn></mml:math>\n"
        "<mml:math><mml:mi>σ</mml:mi><mml:mn>3</mml:mn></mml:math> The"
    )
    assert drop_duplicate_mathml(abstract) == (
        "measured: $$ \\sigma_1 $$$$ \\sigma_2 $$$$ \\sigma_3 $$ The"
    )


def test_resume_tronque_en_pleine_formule_mathml():
    # OpenAlex W4404641639, W1583011294 : le résumé s'arrête dans la formule.
    after_tex = 'decay $$ {B}^0 $$ <mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML">'
    assert drop_duplicate_mathml(after_tex) == "decay $$ {B}^0 $$"
    with_annotation = (
        'class of order <mml:math alttext="alpha"> <mml:semantics> <mml:mi> α </mml:mi> '
        '<mml:annotation encoding="application/x-tex">\\alpha</mml:annotation>'
    )
    assert drop_duplicate_mathml(with_annotation) == "class of order $$\\alpha$$"


def test_annotation_latex_remplace_la_formule_mathml():
    # Crossref, American Mathematical Society.
    abstract = (
        "Given a hypergraph\n"
        '                    <inline-formula content-type="math/mathml">\n'
        '                      <mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML" alttext="upper W">\n'
        "                        <mml:semantics>\n"
        "                          <mml:mi>W</mml:mi>\n"
        '                          <mml:annotation encoding="application/x-tex">W</mml:annotation>\n'
        "                        </mml:semantics>\n"
        "                      </mml:math>\n"
        "                    </inline-formula>\n"
        "                    , every pair"
    )
    assert drop_duplicate_mathml(abstract) == (
        "Given a hypergraph\n"
        '                    <inline-formula content-type="math/mathml">\n'
        "                      $$W$$\n"
        "                    </inline-formula>\n"
        "                    , every pair"
    )


def test_mathml_seul_reste():
    # 10.5802/aif.3755 : l'éditeur dépose seulement la version MathML.
    abstract = (
        "a reductive algebraic group "
        '<mml:math xmlns:mml="http://www.w3.org/1998/Math/MathML"><mml:mi mathvariant="bold">G</mml:mi></mml:math>'
        " over a field of positive characteristic"
    )
    assert drop_duplicate_mathml(abstract) == abstract


def test_formule_latex_separee_du_mathml_par_du_texte():
    abstract = (
        "where $$\\ell$$ is prime and <mml:math><mml:mo>≥</mml:mo><mml:mn>3</mml:mn></mml:math>"
    )
    assert drop_duplicate_mathml(abstract) == abstract


def test_formule_mathml_sans_fermeture_reste():
    # Une ouverture sans fermeture n'emporte pas le texte jusqu'à la formule suivante.
    abstract = (
        "$$a$$ <mml:math><mml:mi>a</mml:mi> truncated text "
        '<mml:math><mml:semantics><mml:mi>b</mml:mi><mml:annotation encoding="application/x-tex">b'
        "</mml:annotation></mml:semantics></mml:math>"
    )
    assert drop_duplicate_mathml(abstract) == (
        "$$a$$ <mml:math><mml:mi>a</mml:mi> truncated text $$b$$"
    )


def test_resume_sans_mathml():
    assert drop_duplicate_mathml("Let $$K$$ be a field.") == "Let $$K$$ be a field."
    assert drop_duplicate_mathml(None) is None
