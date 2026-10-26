# STATUS: recurring (dev)
"""Réestime avec Splink les poids du modèle du résidu de l'alignement des auteurs, et réécrit `residual_weights.py`.

Deux étapes, chacune rejouable seule :

1. Export. Chaque publication à plusieurs enregistrements sources s'aligne par la seule règle de noms (`align_publication`). Les contributions sources et les groupes restés sans lien, enregistrement source par enregistrement source, vont dans `residual.parquet`. Les contributions sources d'auteur des publications de `FULL_MODEL_MAX_AUTHORS` auteurs au plus vont dans `source_contributions.parquet`. Les deux fichiers sont dans `data/residual_weights/`.
2. Estimation. Splink estime par EM les poids du résidu. Sur le résidu, l'EM n'identifie pas les poids d'ORCID et d'IdRef : ils viennent d'un modèle estimé sur toutes les paires de contributions sources d'un échantillon de `source_contributions.parquet`. Le script affiche l'écart aux poids en place, puis réécrit le fichier.

Les niveaux de comparaison des modèles Splink reproduisent en SQL ceux de `comparison_levels`, sous les mêmes libellés.

Usage, sous plafond de mémoire :
    systemd-run --user --scope -p MemoryMax=4G -p MemorySwapMax=0 \\
        .venv/bin/python -m interfaces.cli.dev.estimate_residual_weights [--skip-export] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import splink.comparison_level_library as cll
import splink.comparison_library as cl
from splink import Linker, SettingsCreator
from splink.backends.duckdb import DuckDBAPI
from splink.blocking_rule_library import CustomRule
from splink.internals.blocking_rule_creator import BlockingRuleCreator
from sqlalchemy import Connection, text

from domain.dates import today
from domain.publications.author_grouping import (
    JARO_WINKLER_THRESHOLDS,
    Author,
    Comparison,
    ComparisonLevel,
    ResidualSink,
    align_publication,
)
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.transformation.publications.author_grouping import residual_weights
from pipeline.transformation.publications.author_grouping.author_grouping import (
    contributions_by_source_record,
    deferred_source_records,
    publication_batches,
)
from pipeline.transformation.publications.author_grouping.store import (
    AuthorGroupingStore,
    SourceContributionRow,
)

log = setup_logger("estimate_residual_weights", os.path.dirname(__file__))

DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "residual_weights"
RESIDUAL = DATA_DIR / "residual.parquet"
SOURCE_CONTRIBUTIONS = DATA_DIR / "source_contributions.parquet"
WEIGHTS_FILE = Path(residual_weights.__file__)

FULL_MODEL_MAX_AUTHORS = 100
# Contributions sources de l'échantillon du modèle complet, tirées par publication.
FULL_MODEL_SAMPLE = 1_500_000
RESIDUAL_ITERATIONS = 100
FULL_MODEL_ITERATIONS = 25
EM_MAX_PAIRS = 5_000_000
U_MAX_PAIRS = 10_000_000

_PUBLICATIONS_SQL = text("""
    SELECT publication_id, sum(author_count)::integer FROM source_records
    WHERE publication_id IS NOT NULL
    GROUP BY 1 HAVING count(*) > 1
    ORDER BY 1
""")

_RESIDUAL_SCHEMA = pa.schema(
    [
        ("unique_id", pa.string()),
        ("side", pa.string()),
        ("slot", pa.string()),
        (Comparison.GAP, pa.int32()),
        (Comparison.LAST_NAME, pa.string()),
        (Comparison.FIRST_NAME, pa.string()),
        (Comparison.ORCID, pa.string()),
        (Comparison.IDREF, pa.string()),
    ]
)
_SOURCE_CONTRIBUTIONS_SCHEMA = pa.schema(
    [
        ("unique_id", pa.int64()),
        ("publication_id", pa.int64()),
        ("source_record_id", pa.int64()),
        ("pos", pa.int32()),
        ("n", pa.int32()),
        (Comparison.LAST_NAME, pa.string()),
        (Comparison.FIRST_NAME, pa.string()),
        (Comparison.ORCID, pa.string()),
        (Comparison.IDREF, pa.string()),
    ]
)


def _blank(value: str) -> str | None:
    return value or None


def _residual_records(
    publication_id: int,
    source_record_id: int,
    contributions: Sequence[Author],
    groups: Sequence[Author],
) -> list[dict[str, object]]:
    """Lignes de `residual.parquet` pour un enregistrement source : `slot` réunit l'enregistrement source et les groupes qu'il affronte."""
    slot = f"{publication_id}:{source_record_id}"
    return [
        {
            "unique_id": f"{side[0]}{slot}:{rank}",
            "side": side,
            "slot": slot,
            Comparison.GAP: author.gap,
            Comparison.LAST_NAME: _blank(author.last_name),
            Comparison.FIRST_NAME: _blank(author.first_name),
            Comparison.ORCID: _blank(author.orcid),
            Comparison.IDREF: _blank(author.idref),
        }
        for side, authors in (("contribution", contributions), ("groupe", groups))
        for rank, author in enumerate(authors)
    ]


def _collector(records: list[dict[str, object]], publication_id: int) -> ResidualSink:
    """Ajoute à `records` le résidu de chaque enregistrement source de la publication."""

    def collect(
        source_record_id: int, contributions: Sequence[Author], groups: Sequence[Author]
    ) -> None:
        records.extend(_residual_records(publication_id, source_record_id, contributions, groups))

    return collect


def export(conn: Connection, residual_path: Path, source_contributions_path: Path) -> None:
    """Écrit le résidu de la règle et les contributions sources du modèle complet à partir des contributions sources en base."""
    store = AuthorGroupingStore(conn)
    t0 = time.perf_counter()
    publications = [(r[0], r[1]) for r in conn.execute(_PUBLICATIONS_SQL)]
    log.info("%d publications à plusieurs enregistrements sources", len(publications))
    with (
        pq.ParquetWriter(residual_path, _RESIDUAL_SCHEMA) as residual_out,
        pq.ParquetWriter(
            source_contributions_path, _SOURCE_CONTRIBUTIONS_SCHEMA
        ) as source_contributions_out,
    ):
        done = 0
        for batch in publication_batches(publications):
            rows_by_publication: dict[int, list[SourceContributionRow]] = {}
            for row in store.fetch_source_contributions(batch):
                rows_by_publication.setdefault(row.publication_id, []).append(row)
            residual: list[dict[str, object]] = []
            source_contributions: list[dict[str, object]] = []
            for publication_id, rows in rows_by_publication.items():
                source_records = contributions_by_source_record(rows)
                if len(source_records) < 2:
                    continue
                align_publication(
                    source_records,
                    on_residual=_collector(residual, publication_id),
                    deferred=deferred_source_records(rows),
                )
                if (
                    max(len(contributions) for contributions in source_records.values())
                    <= FULL_MODEL_MAX_AUTHORS
                ):
                    source_contributions.extend(
                        {
                            "unique_id": s.id,
                            "publication_id": publication_id,
                            "source_record_id": source_record_id,
                            "pos": s.position,
                            "n": len(contributions),
                            Comparison.LAST_NAME: _blank(s.last_name),
                            Comparison.FIRST_NAME: _blank(s.first_name),
                            Comparison.ORCID: _blank(s.orcid),
                            Comparison.IDREF: _blank(s.idref),
                        }
                        for source_record_id, contributions in source_records.items()
                        for s in contributions
                        if s.position is not None
                    )
            residual_out.write_table(pa.Table.from_pylist(residual, _RESIDUAL_SCHEMA))
            source_contributions_out.write_table(
                pa.Table.from_pylist(source_contributions, _SOURCE_CONTRIBUTIONS_SCHEMA)
            )
            done += len(batch)
            log.info(
                "%d/%d publications (%.0f s)", done, len(publications), time.perf_counter() - t0
            )


def _initials(col: str) -> str:
    return f"array_to_string(list_transform(string_split({col}, ' '), x -> left(x, 1)), '')"


def _only_initials(col: str) -> str:
    return f"len(list_filter(string_split({col}, ' '), x -> length(x) > 1)) = 0"


def _name_comparisons() -> list[cl.CustomComparison]:
    """Patronyme et prénom, niveaux de `comparison_levels`."""
    last_name = cl.CustomComparison(
        output_column_name=Comparison.LAST_NAME,
        comparison_levels=[
            cll.NullLevel(Comparison.LAST_NAME),
            cll.ExactMatchLevel(Comparison.LAST_NAME).configure(
                label_for_charts=ComparisonLevel.LAST_NAME_EXACT
            ),
            cll.CustomLevel(
                "ln_l = fn_r AND ln_r = fn_l", label_for_charts=ComparisonLevel.REVERSED
            ),
            cll.CustomLevel(
                "list_has_all(string_split(ln_l, ' '), string_split(ln_r, ' '))"
                " OR list_has_all(string_split(ln_r, ' '), string_split(ln_l, ' '))",
                label_for_charts=ComparisonLevel.WORDS_INCLUDED,
            ),
            cll.CustomLevel(
                f"jaro_winkler_similarity(ln_l, ln_r) >= {JARO_WINKLER_THRESHOLDS[ComparisonLevel.JW_092]}",
                label_for_charts=ComparisonLevel.JW_092,
            ),
            cll.CustomLevel(
                f"jaro_winkler_similarity(ln_l, ln_r) >= {JARO_WINKLER_THRESHOLDS[ComparisonLevel.JW_08]}",
                label_for_charts=ComparisonLevel.JW_08,
            ),
            cll.ElseLevel().configure(label_for_charts=ComparisonLevel.ELSE),
        ],
    )
    first_name = cl.CustomComparison(
        output_column_name=Comparison.FIRST_NAME,
        comparison_levels=[
            cll.NullLevel(Comparison.FIRST_NAME),
            cll.ExactMatchLevel(Comparison.FIRST_NAME).configure(
                label_for_charts=ComparisonLevel.FIRST_NAME_EXACT
            ),
            cll.CustomLevel(
                f"(({_only_initials('fn_l')}) OR ({_only_initials('fn_r')}))"
                f" AND (starts_with({_initials('fn_l')}, {_initials('fn_r')})"
                f" OR starts_with({_initials('fn_r')}, {_initials('fn_l')}))",
                label_for_charts=ComparisonLevel.INITIALS_MATCH,
            ),
            cll.CustomLevel(
                f"jaro_winkler_similarity(fn_l, fn_r) >= {JARO_WINKLER_THRESHOLDS[ComparisonLevel.JW_09]}",
                label_for_charts=ComparisonLevel.JW_09,
            ),
            cll.ElseLevel().configure(label_for_charts=ComparisonLevel.ELSE),
        ],
    )
    return [last_name, first_name]


def _identifier(column: str) -> cl.CustomComparison:
    return cl.CustomComparison(
        output_column_name=column,
        comparison_levels=[
            cll.NullLevel(column),
            cll.ExactMatchLevel(column).configure(
                label_for_charts=ComparisonLevel.IDENTIFIER_EXACT
            ),
            cll.ElseLevel().configure(label_for_charts=ComparisonLevel.ELSE),
        ],
    )


# Paires candidates du résidu : une contribution source face aux groupes de son `slot`, de trou égal ou voisin, de patronymes aux deux premières lettres égales, ou d'identifiant partagé.
_SAME_SLOT = "l.slot = r.slot"
_RESIDUAL_BLOCKS: list[BlockingRuleCreator] = [
    CustomRule(f"{_SAME_SLOT} AND abs(l.gap - r.gap) <= 1"),
    CustomRule(f"{_SAME_SLOT} AND left(l.ln, 2) = left(r.ln, 2)"),
    CustomRule(f"{_SAME_SLOT} AND l.orcid = r.orcid"),
    CustomRule(f"{_SAME_SLOT} AND l.idref = r.idref"),
]
_RESIDUAL_EM_BLOCKS = [
    f"{_SAME_SLOT} AND l.gap = r.gap",
    f"{_SAME_SLOT} AND left(l.ln, 2) = left(r.ln, 2)",
]


def _residual_settings() -> SettingsCreator:
    gap = cl.CustomComparison(
        output_column_name=Comparison.GAP,
        comparison_levels=[
            cll.CustomLevel("gap_l = gap_r", label_for_charts=ComparisonLevel.SAME_GAP),
            cll.CustomLevel("abs(gap_l - gap_r) = 1", label_for_charts=ComparisonLevel.NEXT_GAP),
            cll.ElseLevel().configure(label_for_charts=ComparisonLevel.ELSEWHERE),
        ],
    )
    return SettingsCreator(
        link_type="link_only",
        blocking_rules_to_generate_predictions=[*_RESIDUAL_BLOCKS],
        comparisons=[
            *_name_comparisons(),
            _identifier(Comparison.ORCID),
            _identifier(Comparison.IDREF),
            gap,
        ],
        additional_columns_to_retain=["slot"],
        max_iterations=RESIDUAL_ITERATIONS,
    )


# Paires du modèle complet : deux contributions sources d'enregistrements sources différents d'une même publication.
_SAME_PUBLICATION = (
    "l.publication_id = r.publication_id AND l.source_record_id <> r.source_record_id"
)
_SAME_PUBLICATION_RULE: BlockingRuleCreator = CustomRule(_SAME_PUBLICATION)


def _full_settings() -> SettingsCreator:
    """Noms, identifiants, et écart de position décliné par longueur de liste : la fiabilité de la position dépend de la longueur des listes."""
    gaps = (
        ("pos_l = pos_r", "même position"),
        ("abs(pos_l - pos_r) = 1", "écart de 1"),
        ("abs(pos_l / n_l - pos_r / n_r) <= 0.1", "écart relatif <= 10 %"),
        ("true", "plus loin"),
    )
    lengths = (
        ("greatest(n_l, n_r) <= 20", "jusqu'à 20"),
        ("greatest(n_l, n_r) BETWEEN 21 AND 50", "21-50"),
        ("greatest(n_l, n_r) > 50", "plus de 50"),
    )
    position = cl.CustomComparison(
        output_column_name="pos",
        comparison_levels=[
            cll.CustomLevel(f"({g}) AND ({n})", label_for_charts=f"{g_label}, {n_label}")
            for g, g_label in gaps
            for n, n_label in lengths
        ],
    )
    return SettingsCreator(
        link_type="dedupe_only",
        blocking_rules_to_generate_predictions=[_SAME_PUBLICATION_RULE],
        comparisons=[
            *_name_comparisons(),
            _identifier(Comparison.ORCID),
            _identifier(Comparison.IDREF),
            position,
        ],
        additional_columns_to_retain=["publication_id", "source_record_id", "n"],
        max_iterations=FULL_MODEL_ITERATIONS,
    )


def _level_weights(linker: Linker) -> dict[str, dict[str, float]]:
    """Poids en bits, log2(m/u), de chaque niveau non nul du modèle."""
    weights: dict[str, dict[str, float]] = {}
    for comparison in linker.misc.save_model_to_json()["comparisons"]:
        levels = weights.setdefault(comparison["output_column_name"], {})
        for level in comparison["comparison_levels"]:
            m, u = level.get("m_probability"), level.get("u_probability")
            if not level.get("is_null_level") and m and u:
                levels[level["label_for_charts"]] = math.log2(m / u)
    return weights


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET memory_limit = '2GB'")
    con.execute(f"SET temp_directory = '{DATA_DIR / 'duckdb_tmp'}'")
    con.execute("SET threads = 4")
    return con


def _estimate_residual() -> dict[str, dict[str, float]]:
    con = _connect()
    con.execute(
        f"CREATE TABLE contributions AS SELECT * FROM read_parquet('{RESIDUAL}') WHERE side = 'contribution'"
    )
    con.execute(
        f"CREATE TABLE groups AS SELECT * FROM read_parquet('{RESIDUAL}') WHERE side = 'groupe'"
    )
    api = DuckDBAPI(con)
    linker = Linker([api.register("contributions"), api.register("groups")], _residual_settings())
    linker.training.estimate_probability_two_random_records_match([*_RESIDUAL_BLOCKS], recall=0.8)
    linker.training.estimate_u_using_random_sampling(max_pairs=U_MAX_PAIRS)
    for rule in _RESIDUAL_EM_BLOCKS:
        linker.training.estimate_parameters_using_expectation_maximisation(
            rule, max_pairs=EM_MAX_PAIRS
        )
    return _level_weights(linker)


def _estimate_identifiers() -> dict[str, dict[str, float]]:
    """Poids d'ORCID et d'IdRef du modèle complet, estimé sur un échantillon de publications tirées au hasard."""
    con = _connect()
    sizes = con.execute(
        f"SELECT publication_id, count(*) FROM read_parquet('{SOURCE_CONTRIBUTIONS}') GROUP BY 1 ORDER BY 1"
    ).fetchall()
    random.Random(7).shuffle(sizes)  # noqa: S311 (tirage reproductible, sans usage cryptographique)
    sample: list[int] = []
    total = 0
    for publication_id, count in sizes:
        if total + count > FULL_MODEL_SAMPLE:
            break
        sample.append(publication_id)
        total += count
    con.execute("CREATE TABLE sample_ids (publication_id BIGINT)")
    con.executemany("INSERT INTO sample_ids VALUES (?)", [(p,) for p in sample])
    con.execute(
        f"CREATE TABLE source_contributions AS SELECT s.* FROM read_parquet('{SOURCE_CONTRIBUTIONS}') s"
        " JOIN sample_ids USING (publication_id)"
    )
    log.info("modèle complet : %d publications, %d contributions sources", len(sample), total)
    linker = Linker(DuckDBAPI(con).register("source_contributions"), _full_settings())
    linker.training.estimate_probability_two_random_records_match(
        [_SAME_PUBLICATION_RULE], recall=0.9
    )
    linker.training.estimate_u_using_random_sampling(max_pairs=U_MAX_PAIRS)
    linker.training.estimate_parameters_using_expectation_maximisation(
        _SAME_PUBLICATION, max_pairs=EM_MAX_PAIRS
    )
    weights = _level_weights(linker)
    return {column: weights[column] for column in (Comparison.ORCID, Comparison.IDREF)}


def _render(weights: Mapping[str, Mapping[str, float]]) -> str:
    """Contenu de `residual_weights.py`."""
    lines = [
        '"""Poids en bits du modèle du résidu, par comparaison et par niveau (`domain.publications.author_grouping.comparison_levels`).',
        "",
        f"Estimés le {today().isoformat()} par `interfaces.cli.dev.estimate_residual_weights`, avec Splink, par EM sur les contributions sources que la règle de noms laisse sans lien dans tout le stock, {RESIDUAL_ITERATIONS} itérations. Les poids d'ORCID et d'IdRef viennent d'un modèle estimé sur toutes les paires de contributions sources d'un échantillon des publications de {FULL_MODEL_MAX_AUTHORS} auteurs au plus : sur le résidu, l'EM ne les identifie pas.",
        '"""',
        "",
        "RESIDUAL_WEIGHTS: dict[str, dict[str, float]] = {",
    ]
    for comparison, levels in weights.items():
        lines.append(f"    {json.dumps(comparison)}: {{")
        lines += [
            f"        {json.dumps(label, ensure_ascii=False)}: {round(value, 3)!r},"
            for label, value in levels.items()
        ]
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _report(old: Mapping[str, Mapping[str, float]], new: Mapping[str, Mapping[str, float]]) -> None:
    for comparison, levels in new.items():
        for label, value in levels.items():
            before = old.get(comparison, {}).get(label)
            change = f"{value - before:+.3f}" if before is not None else "nouveau niveau"
            log.info("%s / %s : %.3f (%s)", comparison, label, value, change)
        for label in set(old.get(comparison, {})) - set(levels):
            log.info("%s / %s : niveau sans poids estimé", comparison, label)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-export", action="store_true", help="réutilise les fichiers Parquet de l'export"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="affiche les poids estimés sans réécrire le fichier"
    )
    args = parser.parse_args()

    if not args.skip_export:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with get_sync_engine().connect() as conn:
            export(conn, RESIDUAL, SOURCE_CONTRIBUTIONS)
            conn.rollback()
    weights = _estimate_residual()
    weights.update(_estimate_identifiers())
    _report(residual_weights.RESIDUAL_WEIGHTS, weights)
    if not args.dry_run:
        WEIGHTS_FILE.write_text(_render(weights), encoding="utf-8")
        log.info("%s réécrit", WEIGHTS_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
