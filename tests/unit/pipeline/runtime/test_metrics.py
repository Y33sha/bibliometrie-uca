"""Métriques de phase : `total`, au moins égal à la somme de la ventilation, et sérialisation."""

from pipeline.runtime.observability.metrics import PhaseMetrics


def test_total_derives_from_breakdown_without_explicit_denominator():
    # Sans dénominateur renseigné, `total` vaut la somme de new, updated et unchanged.
    m = PhaseMetrics()
    m.add(new=204)
    m.add(updated=3891)
    m.add(unchanged=19101)
    assert m.total == 204 + 3891 + 19101


def test_total_uses_explicit_denominator_when_larger():
    # Cas de fetch_missing : les DOI cherchés (`seen`) dépassent les enregistrements sources insérés.
    m = PhaseMetrics()
    m.add(new=10, seen=100)
    assert m.total == 100


def test_total_never_below_breakdown():
    # Un dénominateur inférieur à la ventilation : `total` vaut la ventilation.
    m = PhaseMetrics(seen=2)
    m.add(new=5)
    assert m.total == 5


def test_merge_sums_denominator_and_breakdown():
    a = PhaseMetrics()
    a.add(new=1, seen=3)
    b = PhaseMetrics()
    b.add(updated=2, seen=4)
    a.merge(b)
    assert (a.new, a.updated) == (1, 2)
    assert a.total == 7  # seen 3 + 4, au-dessus de la ventilation (3)


def test_to_payload():
    metrics = PhaseMetrics(new=3, updated=1)
    metrics.extras["tagged"] = 2
    assert metrics.to_payload(duration_s=12.5) == {
        "new": 3,
        "updated": 1,
        "unchanged": 0,
        "total": 4,
        "errors": 0,
        "extras": {"tagged": 2},
        "duration_s": 12.5,
    }
