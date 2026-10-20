"""Estimation des poids du modèle du résidu : export du résidu de la règle, et réécriture du fichier de poids."""

import pyarrow.parquet as pq

from interfaces.cli.dev import estimate_residual_weights as script
from pipeline.transformation.publications.author_grouping.residual_weights import (
    RESIDUAL_WEIGHTS,
)
from tests.integration.helpers.contributions import upsert_split_identity
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_signature, insert_source_record


def _source_record(conn, publication_id, source, source_id, names):
    source_record = insert_source_record(conn, publication_id, source=source, source_id=source_id)
    for pos, (last, first) in enumerate(names):
        insert_signature(
            conn,
            source_record,
            source=source,
            author_position=pos,
            contributor_information_id=upsert_split_identity(conn, last, first),
        )
    return source_record


def test_l_export_ecrit_le_residu_de_la_regle_et_les_contributions_sources(sa_sync_conn, tmp_path):
    conn = sa_sync_conn
    publication = insert_publication(conn)
    hal = _source_record(
        conn,
        publication,
        "hal",
        "hal-1",
        [("martin", "a"), ("garcia navarro", "j e"), ("durand", "c")],
    )
    openalex = _source_record(
        conn,
        publication,
        "openalex",
        "W1",
        [("martin", "a"), ("navarro", "j e garcia"), ("durand", "c")],
    )
    residual_path, source_contributions_path = (
        tmp_path / "residual.parquet",
        tmp_path / "source_contributions.parquet",
    )

    script.export(conn, residual_path, source_contributions_path)

    residual = sorted(
        (r["side"], r["slot"], r["gap"], r["ln"], r["fn"])
        for r in pq.read_table(residual_path).to_pylist()
    )
    # Listes de même longueur : l'enregistrement source HAL, de plus petit identifiant, fonde les groupes.
    assert hal < openalex
    slot = f"{publication}:{openalex}"
    assert residual == [
        ("contribution", slot, 1, "navarro", "j e garcia"),
        ("groupe", slot, 1, "garcia navarro", "j e"),
    ]
    assert pq.read_table(source_contributions_path).num_rows == 6


def test_le_fichier_de_poids_reecrit_se_relit_a_l_identique():
    namespace: dict[str, object] = {}
    exec(script._render(RESIDUAL_WEIGHTS), namespace)  # noqa: S102
    assert namespace["RESIDUAL_WEIGHTS"] == RESIDUAL_WEIGHTS
