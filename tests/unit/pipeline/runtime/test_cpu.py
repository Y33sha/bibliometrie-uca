"""Processeurs dont dispose le pipeline."""

import os

from pipeline.runtime.cpu import available_cpus


def test_le_quota_du_conteneur_plafonne_les_processeurs(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "process_cpu_count", lambda: 8)
    cpu_max = tmp_path / "cpu.max"
    cpu_max.write_text("200000 100000\n")
    assert available_cpus(cpu_max) == 2


def test_un_quota_fractionnaire_compte_un_processeur_entier(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "process_cpu_count", lambda: 8)
    cpu_max = tmp_path / "cpu.max"
    cpu_max.write_text("150000 100000\n")
    assert available_cpus(cpu_max) == 2


def test_sans_quota_les_processeurs_du_processus(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "process_cpu_count", lambda: 8)
    cpu_max = tmp_path / "cpu.max"
    cpu_max.write_text("max 100000\n")
    assert available_cpus(cpu_max) == 8
    assert available_cpus(tmp_path / "absent") == 8
