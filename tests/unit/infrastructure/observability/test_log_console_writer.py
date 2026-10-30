"""Détournement de l'écriture des lignes de console.

Le pipeline branche sur cette écriture un écrivain qui affiche les lignes au-dessus des barres de progression.
"""

import io

from infrastructure.observability import log as module


def test_sans_ecrivain_la_ligne_part_sur_le_flux():
    flux = io.StringIO()
    module._FluxConsole(flux).write("une ligne\n")
    assert flux.getvalue() == "une ligne\n"


def test_l_ecrivain_branche_recoit_la_ligne_et_le_flux():
    recu: list[tuple[str, object]] = []
    flux = io.StringIO()
    module.set_console_writer(lambda ligne, f: recu.append((ligne, f)))
    try:
        module._FluxConsole(flux).write("une ligne\n")
    finally:
        module.set_console_writer(None)
    assert recu == [("une ligne", flux)]
    assert flux.getvalue() == ""


def test_une_ligne_vide_part_sur_le_flux():
    """Un saut de ligne isolé, émis par un handler, part directement sur le flux sans passer par l'écrivain."""
    flux = io.StringIO()
    module.set_console_writer(lambda ligne, f: None)
    try:
        module._FluxConsole(flux).write("\n")
    finally:
        module.set_console_writer(None)
    assert flux.getvalue() == "\n"
