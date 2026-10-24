"""Tests des plateformes (`domain.platforms.platform`)."""

import pytest

from domain.platforms.platform import is_catalog_record


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://doaj.org/article/abc", True),
        ("https://www.doaj.org/article/abc", True),
        ("https://hal.science/hal-1", False),
    ],
)
def test_fiche_de_catalogue(url, expected):
    assert is_catalog_record(url) is expected
