"""Métriques de la phase personnes, assemblées depuis les compteurs de ses tâches."""

from pipeline.transformation.persons.metrics import build_metrics


def _metrics():
    return build_metrics(
        resolution={
            "pinned": 2,
            "first_names_completed": 1,
            "groups": 10,
            "written": 6,
            "match:orcid": 4,
            "match:manual": 1,
            "match:name": 1,
            "skip:ambiguous_name_form": 3,
            "create": 1,
        },
        arbitration={"neutralized": 5, "marked_groups": 2, "transferred": 1},
        name_forms={"inserted": 7},
        purge={"reorphaned": 2, "deleted_attributions": 0, "deleted_persons": 3},
    )


def test_la_table_compte_les_rattachements_par_mode_epinglages_compris():
    rows = {row["key"]: row["count"] for row in _metrics().details["table"]["rows"]}
    assert rows == {
        "manual": 3,
        "orcid": 4,
        "hal_person_id": 0,
        "idref": 0,
        "name": 1,
        "compatible_name": 0,
        "created": 0,
    }


def test_le_resume_garde_les_compteurs_du_rattachement_et_des_autres_taches():
    summary = _metrics().details["summary"]
    assert summary["written"] == 6
    assert summary["skip:ambiguous_name_form"] == 3
    assert summary["create"] == 1
    assert summary["identifiers_transferred"] == 1
    assert summary["deleted_persons"] == 3
    assert summary["name_forms_inserted"] == 7


def test_les_compteurs_generiques_suivent_les_contributions_examinees_et_rattachees():
    metrics = _metrics()
    assert (metrics.seen, metrics.new, metrics.updated) == (10, 0, 8)
