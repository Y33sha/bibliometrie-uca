"""Aucun test ne vide la table `config`.

La migration y pose des clés que des tests lisent ensuite, dans la même session. Un test retire seulement les clés qu'il a posées.
"""

import re
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]

_TRUNCATE_CONFIG = re.compile(r"TRUNCATE\s+TABLE[^\"']*\bconfig\b")
_TRUNCATE_HELPER_CONFIG = re.compile(r"truncate_after_module\([^)]*[\"']config[\"']")


def test_aucun_test_ne_vide_config() -> None:
    fautifs = [
        str(path.relative_to(TESTS_ROOT))
        for path in TESTS_ROOT.rglob("*.py")
        if path != Path(__file__).resolve()
        and (
            _TRUNCATE_CONFIG.search(text := path.read_text(encoding="utf-8"))
            or _TRUNCATE_HELPER_CONFIG.search(text)
        )
    ]
    assert fautifs == []
