"""Détournement de l'écriture des lignes de console.

Le pipeline y branche un écrivain qui pose ses lignes au-dessus des barres de progression.
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
    """Le saut de ligne isolé qu'un handler émet ne vaut pas un message."""
    flux = io.StringIO()
    module.set_console_writer(lambda ligne, f: None)
    try:
        module._FluxConsole(flux).write("\n")
    finally:
        module.set_console_writer(None)
    assert flux.getvalue() == "\n"
