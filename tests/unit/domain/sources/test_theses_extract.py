"""Tests unitaires de `domain/sources/theses_extract.py`."""

from __future__ import annotations

import argparse

from domain.sources.theses_extract import (
    build_query,
    extract_doi,
    extract_theses_id,
    resolve_statuses,
)


class TestBuildQuery:
    def test_ppn_only(self):
        assert build_query(ppn="196200032") == "etabSoutenancePpn:(196200032)"

    def test_ppn_with_status(self):
        assert build_query(ppn="196200032", status="soutenue") == (
            "etabSoutenancePpn:(196200032) AND status:(soutenue)"
        )

    def test_status_empty_string_treated_as_none(self):
        # Branche `if status:` — chaîne vide n'ajoute pas de filtre.
        assert build_query(ppn="X", status="") == "etabSoutenancePpn:(X)"


class TestExtractThesesId:
    def test_returns_nnt_for_defended(self):
        # Thèse soutenue : NNT préfixé YYYY.
        assert extract_theses_id({"id": "2021UCFAC022", "nnt": "2021UCFAC022"}) == ("2021UCFAC022")

    def test_returns_internal_id_for_ongoing(self):
        # Thèse en cours : id theses.fr `s...` ; pas de NNT.
        assert extract_theses_id({"id": "s367812", "nnt": None}) == "s367812"

    def test_empty_when_missing(self):
        assert extract_theses_id({}) == ""


class TestExtractDoi:
    def test_returns_stripped_doi(self):
        assert extract_doi({"doi": "  10.1000/abc  "}) == "10.1000/abc"

    def test_returns_none_when_absent(self):
        assert extract_doi({}) is None

    def test_returns_none_when_empty_string(self):
        # `doi` présent mais string vide → None.
        assert extract_doi({"doi": ""}) is None

    def test_returns_none_when_whitespace_only(self):
        assert extract_doi({"doi": "   "}) is None

    def test_returns_none_when_not_string(self):
        # Cas anormal mais à pinner : `doi` non-str → None silencieux.
        assert extract_doi({"doi": 12345}) is None


class TestResolveStatuses:
    def test_both_flags(self):
        args = argparse.Namespace(soutenues=True, en_cours=True)
        assert resolve_statuses(args) == ["soutenue", "enCours"]

    def test_neither_flag_defaults_to_both(self):
        args = argparse.Namespace(soutenues=False, en_cours=False)
        assert resolve_statuses(args) == ["soutenue", "enCours"]

    def test_soutenues_only(self):
        args = argparse.Namespace(soutenues=True, en_cours=False)
        assert resolve_statuses(args) == ["soutenue"]

    def test_en_cours_only(self):
        args = argparse.Namespace(soutenues=False, en_cours=True)
        assert resolve_statuses(args) == ["enCours"]
