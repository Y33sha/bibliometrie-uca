"""Snapshots de runs pipeline (Phase 2 du chantier observabilité).

`build_run_snapshot(conn, mode, metrics_per_phase, ...)` calcule les observables
courants, les compare au dernier snapshot du même mode (daily/weekly/full), et
construit le `RunSnapshot` à persister.
`persist_snapshot(conn, snapshot)` écrit dans `pipeline_run_snapshots`.
`render_summary(snapshot)` produit un résumé console à logger en fin de pipeline.

Pas d'exit code non-zéro : les observations sont signalées comme « suspectes »
si leur delta dépasse un seuil hardcodé, sans hiérarchie de sévérité. Les
métriques d'exécution (`metrics_per_phase`) sont persistées telles quelles, sans
seuil de drift — ce sont des compteurs informatifs, pas un signal d'alerte.

Les runs partiels (`--only` / `--from` / `--dry-run`) ne doivent pas appeler ces
fonctions : le snapshot n'a de sens que sur un run complet (cf. fiche).
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import TypedDict, cast

from sqlalchemy import Connection, text

from application.ports.pipeline.runs import (
    ObservablesPayload,
    Observation,
    PhaseMetricsPayload,
    RunSnapshot,
    RunSnapshotPayload,
)

log = logging.getLogger(__name__)

_VOLUME_DELTA_PCT = 5.0
_ORPHANS_DELTA_PCT = 20.0
_DISTRIBUTION_RATIO_DELTA_PTS = 3.0
_MATCHING_AMBIGUOUS_DELTA_PCT = 10.0


class _PreviousSnapshot(TypedDict):
    ran_at: datetime.datetime
    payload: RunSnapshotPayload


def build_run_snapshot(
    conn: Connection,
    *,
    mode: str,
    metrics_per_phase: dict[str, PhaseMetricsPayload],
    sources: list[str],
    phases_run: list[str],
    total_duration_s: float,
) -> RunSnapshot:
    """Calcule les observables, les compare au dernier snapshot du même mode, et
    construit le snapshot complet (observables + métriques + métadonnées run).
    """
    previous = _fetch_previous_snapshot(conn, mode)
    observables = _compute_observables(conn)
    prev_observables = previous["payload"]["observables"] if previous else None
    observations = _build_observations(observables, prev_observables)
    payload: RunSnapshotPayload = {
        "observables": observables,
        "metrics_per_phase": metrics_per_phase,
        "total_duration_s": total_duration_s,
        "sources": sources,
        "phases_run": phases_run,
    }
    return RunSnapshot(
        mode=mode,
        ran_at=datetime.datetime.now(datetime.UTC),
        previous_snapshot_at=previous["ran_at"] if previous else None,
        current=payload,
        observations=observations,
    )


def persist_snapshot(conn: Connection, snapshot: RunSnapshot) -> None:
    """Persiste le payload courant du snapshot dans `pipeline_run_snapshots`."""
    conn.execute(
        text(
            "INSERT INTO pipeline_run_snapshots (mode, payload) "
            "VALUES (:mode, CAST(:payload AS jsonb))"
        ),
        {"mode": snapshot.mode, "payload": json.dumps(snapshot.current)},
    )
    conn.commit()


def render_summary(snapshot: RunSnapshot) -> str:
    """Résumé multi-ligne pour affichage console en fin de pipeline."""
    lines = [f"Snapshot post-pipeline (mode={snapshot.mode})"]
    if snapshot.previous_snapshot_at is None:
        lines.append("  (premier snapshot pour ce mode, aucune comparaison possible)")
    else:
        prev = snapshot.previous_snapshot_at.astimezone().strftime("%Y-%m-%d %H:%M")
        lines.append(f"  Comparé au snapshot du {prev}")
    suspects = snapshot.suspect_observations
    if not suspects:
        lines.append(
            f"  Aucune observation suspecte sur {len(snapshot.observations)} observable(s)."
        )
    else:
        lines.append(
            f"  {len(suspects)} observation(s) suspecte(s) sur {len(snapshot.observations)} :"
        )
        for o in suspects:
            prev_str = "—" if o.previous is None else f"{o.previous:g}"
            lines.append(f"    - {o.label} : {o.current:g} (préc. {prev_str}, {o.threshold_note})")
    return "\n".join(lines)


# ── internes ──────────────────────────────────────────────────────────


def _fetch_previous_snapshot(conn: Connection, mode: str) -> _PreviousSnapshot | None:
    row = conn.execute(
        text(
            "SELECT ran_at, payload FROM pipeline_run_snapshots "
            "WHERE mode = :mode ORDER BY ran_at DESC LIMIT 1"
        ),
        {"mode": mode},
    ).first()
    if row is None:
        return None
    # Le payload JSONB est désérialisé par SA en dict natif ; on cast vers le
    # TypedDict attendu — le runtime ne valide pas, c'est juste une hint mypy.
    return _PreviousSnapshot(ran_at=row[0], payload=cast(RunSnapshotPayload, row[1]))


def _compute_observables(conn: Connection) -> ObservablesPayload:
    return {
        "volumes": _q_volumes(conn),
        "orphans": _q_orphans(conn),
        "distributions": _q_distributions(conn),
        "matching_quality": _q_matching_quality(conn),
    }


def _q_volumes(conn: Connection) -> dict[str, int]:
    return {
        "publications": _scalar(conn, "SELECT COUNT(*) FROM publications"),
        "persons": _scalar(conn, "SELECT COUNT(*) FROM persons WHERE NOT rejected"),
        "authorships": _scalar(conn, "SELECT COUNT(*) FROM authorships WHERE NOT excluded"),
        "addresses": _scalar(conn, "SELECT COUNT(*) FROM addresses"),
        "person_identifiers": _scalar(
            conn, "SELECT COUNT(*) FROM person_identifiers WHERE status <> 'rejected'"
        ),
        "person_name_forms": _scalar(conn, "SELECT COUNT(*) FROM person_name_forms"),
    }


def _q_orphans(conn: Connection) -> dict[str, int]:
    publications_no_authorships = _scalar(
        conn,
        """
        SELECT COUNT(*) FROM publications p
        WHERE NOT EXISTS (
            SELECT 1 FROM authorships a
            WHERE a.publication_id = p.id AND NOT a.excluded
        )
        """,
    )
    persons_no_publications = _scalar(
        conn,
        """
        SELECT COUNT(*) FROM persons p
        WHERE NOT p.rejected AND NOT EXISTS (
            SELECT 1 FROM authorships a
            WHERE a.person_id = p.id AND NOT a.excluded
        )
        """,
    )
    return {
        "publications_no_authorships": publications_no_authorships,
        "persons_no_publications": persons_no_publications,
    }


def _q_distributions(conn: Connection) -> dict[str, dict[str, float]]:
    doc_type_rows = conn.execute(
        text("SELECT doc_type::text, COUNT(*) FROM publications GROUP BY doc_type")
    ).all()
    doc_type_counts: dict[str, int] = {str(r[0]): int(r[1]) for r in doc_type_rows}
    source_rows = conn.execute(
        text("SELECT source::text, COUNT(*) FROM source_publications GROUP BY source")
    ).all()
    source_counts: dict[str, int] = {str(r[0]): int(r[1]) for r in source_rows}
    return {
        "doc_type": _to_ratios(doc_type_counts),
        "source": _to_ratios(source_counts),
    }


def _q_matching_quality(conn: Connection) -> dict[str, int]:
    ambiguous = _scalar(
        conn,
        """
        SELECT COUNT(*) FROM (
            SELECT name_form FROM person_name_forms
            GROUP BY name_form
            HAVING COUNT(DISTINCT person_id) >= 2
        ) t
        """,
    )
    return {"ambiguous_name_forms": ambiguous}


def _scalar(conn: Connection, sql: str) -> int:
    result = conn.execute(text(sql)).scalar()
    return int(result) if result is not None else 0


def _to_ratios(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values())
    if total == 0:
        return {k: 0.0 for k in counts}
    return {k: v / total for k, v in counts.items()}


def _build_observations(
    current: ObservablesPayload, previous: ObservablesPayload | None
) -> list[Observation]:
    obs: list[Observation] = []
    obs.extend(_volume_observations(current, previous))
    obs.extend(_orphan_observations(current, previous))
    obs.extend(_distribution_observations(current, previous))
    obs.extend(_matching_observations(current, previous))
    return obs


def _volume_observations(
    current: ObservablesPayload, previous: ObservablesPayload | None
) -> list[Observation]:
    prev_section: dict[str, int] = previous["volumes"] if previous else {}
    return [
        _drift_observation(
            key=f"volumes.{name}",
            label=f"volume {name}",
            current=value,
            previous=prev_section.get(name),
            threshold_pct=_VOLUME_DELTA_PCT,
            symmetric=True,
        )
        for name, value in current["volumes"].items()
    ]


def _orphan_observations(
    current: ObservablesPayload, previous: ObservablesPayload | None
) -> list[Observation]:
    prev_section: dict[str, int] = previous["orphans"] if previous else {}
    return [
        _drift_observation(
            key=f"orphans.{name}",
            label=f"orphelins {name}",
            current=value,
            previous=prev_section.get(name),
            threshold_pct=_ORPHANS_DELTA_PCT,
            symmetric=True,
        )
        for name, value in current["orphans"].items()
    ]


def _distribution_observations(
    current: ObservablesPayload, previous: ObservablesPayload | None
) -> list[Observation]:
    out: list[Observation] = []
    prev_dists: dict[str, dict[str, float]] = previous["distributions"] if previous else {}
    for dist_name, ratios in current["distributions"].items():
        prev_ratios = prev_dists.get(dist_name, {})
        for ratio_key in sorted(set(ratios) | set(prev_ratios)):
            curr_v = ratios.get(ratio_key, 0.0)
            prev_v = prev_ratios.get(ratio_key)
            shift_pts = None if prev_v is None else (curr_v - prev_v) * 100
            suspect = shift_pts is not None and abs(shift_pts) > _DISTRIBUTION_RATIO_DELTA_PTS
            note = (
                f"shift {shift_pts:+.1f} pts (seuil ±{_DISTRIBUTION_RATIO_DELTA_PTS} pts)"
                if shift_pts is not None
                else "premier snapshot"
            )
            out.append(
                Observation(
                    key=f"distributions.{dist_name}.{ratio_key}",
                    label=f"ratio {dist_name}={ratio_key}",
                    current=curr_v,
                    previous=prev_v,
                    delta_pct=shift_pts,
                    suspect=suspect,
                    threshold_note=note,
                )
            )
    return out


def _matching_observations(
    current: ObservablesPayload, previous: ObservablesPayload | None
) -> list[Observation]:
    prev_section: dict[str, int] = previous["matching_quality"] if previous else {}
    return [
        _drift_observation(
            key=f"matching_quality.{name}",
            label=f"qualité matching {name}",
            current=value,
            previous=prev_section.get(name),
            threshold_pct=_MATCHING_AMBIGUOUS_DELTA_PCT,
            symmetric=False,
        )
        for name, value in current["matching_quality"].items()
    ]


def _drift_observation(
    *,
    key: str,
    label: str,
    current: float,
    previous: float | None,
    threshold_pct: float,
    symmetric: bool,
) -> Observation:
    if previous is None:
        return Observation(
            key=key,
            label=label,
            current=current,
            previous=None,
            delta_pct=None,
            suspect=False,
            threshold_note="premier snapshot",
        )
    if previous == 0:
        return Observation(
            key=key,
            label=label,
            current=current,
            previous=previous,
            delta_pct=None,
            suspect=current > 0,
            threshold_note="précédent à 0",
        )
    delta_pct = (current - previous) / previous * 100
    if symmetric:
        suspect = abs(delta_pct) > threshold_pct
        note = f"delta {delta_pct:+.1f}% (seuil ±{threshold_pct}%)"
    else:
        suspect = delta_pct > threshold_pct
        note = f"delta {delta_pct:+.1f}% (seuil +{threshold_pct}%)"
    return Observation(
        key=key,
        label=label,
        current=current,
        previous=previous,
        delta_pct=delta_pct,
        suspect=suspect,
        threshold_note=note,
    )
