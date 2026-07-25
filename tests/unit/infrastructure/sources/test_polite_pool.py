"""Test du helper User-Agent polite pool partagé."""

from infrastructure.sources.polite_pool import build_user_agent


def test_build_user_agent_includes_email():
    ua = build_user_agent("foo@bar.fr")
    assert "mailto:foo@bar.fr" in ua
    assert "BibliometrieUCA" in ua
