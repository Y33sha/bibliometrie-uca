"""Tests unitaires de `find_duplicates` (déduplication par identifiant HAL).

Mock du port `MergeQueries` — pas de DB.

Couvre notamment le cas qui avait causé l'accumulation silencieuse de doublons
ScanR↔HAL : un même hal_id partagé entre OpenAlex (déjà fusionnée à HAL) et
ScanR (orpheline). L'ancienne implémentation gardait uniquement la 1ère
occurrence par hal_id et ignorait silencieusement la suivante.
"""

from typing import Any

from application.pipeline.publications.merge_pubs_by_hal_id import find_duplicates


class _FakeQueries:
    def __init__(
        self,
        src_rows: list[dict[str, Any]],
        hal_rows: list[dict[str, Any]],
    ) -> None:
        self._src_rows = src_rows
        self._hal_rows = hal_rows

    # `conn: object` car l'argument n'est pas utilisé dans le fake (les tests
    # passent `conn=None` ; le fake retourne directement les rows pré-fournies).
    def fetch_source_publications_with_hal_external_id(self, conn: object) -> list[dict[str, Any]]:
        return self._src_rows

    def fetch_hal_source_publications(self, conn: object) -> list[dict[str, Any]]:
        return self._hal_rows


def _src(source: str, src_pub_id: int | None, hal_id: str, src_doc_id: int = 1) -> dict:
    return {
        "src_doc_id": src_doc_id,
        "source": source,
        "src_id": f"{source}-{src_doc_id}",
        "src_pub_id": src_pub_id,
        "hal_id": hal_id,
    }


def _hal(hal_id: str, hal_pub_id: int | None, hal_doc_id: int = 100) -> dict:
    return {"hal_doc_id": hal_doc_id, "halid": hal_id, "hal_pub_id": hal_pub_id}


# ── Régression : OA + ScanR sur même hal_id ──────────────────────────


def test_second_source_with_same_hal_id_is_not_dropped():
    """Cas réel observé en prod (publi 160452 vs 86628 sur hal-05508565).

    OpenAlex est inséré en 1er et déjà fusionné à HAL (publi A=86628).
    ScanR arrive ensuite avec une publi distincte (publi B=160452).
    Le fix doit faire apparaître ScanR dans merge_needed.
    """
    src_rows = [
        _src("openalex", src_pub_id=86628, hal_id="hal-05508565", src_doc_id=1),
        _src("scanr", src_pub_id=160452, hal_id="hal-05508565", src_doc_id=2),
    ]
    hal_rows = [_hal("hal-05508565", hal_pub_id=86628, hal_doc_id=999)]

    link_only, merge_needed = find_duplicates(conn=None, queries=_FakeQueries(src_rows, hal_rows))

    assert link_only == []
    assert len(merge_needed) == 1
    item = merge_needed[0]
    assert item["source"] == "scanr"
    assert item["src_pub_id"] == 160452
    assert item["hal_pub_id"] == 86628
    assert item["halid"] == "hal-05508565"


def test_no_op_when_both_sources_already_merged():
    """Si OA et ScanR sont toutes deux déjà fusionnées à la publi HAL → rien à faire."""
    src_rows = [
        _src("openalex", src_pub_id=42, hal_id="hal-X"),
        _src("scanr", src_pub_id=42, hal_id="hal-X", src_doc_id=2),
    ]
    hal_rows = [_hal("hal-X", hal_pub_id=42)]

    link_only, merge_needed = find_duplicates(conn=None, queries=_FakeQueries(src_rows, hal_rows))

    assert link_only == []
    assert merge_needed == []


# ── link_only ─────────────────────────────────────────────────────────


def test_link_only_when_hal_has_no_publication_id():
    """HAL sans publication_id, source non-HAL avec publi → cas link_only."""
    src_rows = [_src("openalex", src_pub_id=10, hal_id="hal-Y")]
    hal_rows = [_hal("hal-Y", hal_pub_id=None, hal_doc_id=500)]

    link_only, merge_needed = find_duplicates(conn=None, queries=_FakeQueries(src_rows, hal_rows))

    assert merge_needed == []
    assert len(link_only) == 1
    assert link_only[0]["src_pub_id"] == 10
    assert link_only[0]["hal_doc_id"] == 500


def test_link_only_dedup_per_hal_doc_when_multiple_sources():
    """Plusieurs sources non-HAL pointant vers le même hal_doc orphelin → un seul link.

    On ne peut lier qu'une publi par hal_doc. Les autres sources seront rattrapées
    au run suivant (devenues des cas merge_needed après le 1er lien).
    """
    src_rows = [
        _src("openalex", src_pub_id=10, hal_id="hal-Z", src_doc_id=1),
        _src("scanr", src_pub_id=11, hal_id="hal-Z", src_doc_id=2),
    ]
    hal_rows = [_hal("hal-Z", hal_pub_id=None, hal_doc_id=700)]

    link_only, _ = find_duplicates(conn=None, queries=_FakeQueries(src_rows, hal_rows))

    assert len(link_only) == 1
    assert link_only[0]["hal_doc_id"] == 700


# ── merge_needed ──────────────────────────────────────────────────────


def test_merge_needed_dedup_same_pair_seen_twice():
    """Si deux sources non-HAL portent le même (src_pub, hal_pub) → un seul merge_needed."""
    src_rows = [
        _src("openalex", src_pub_id=20, hal_id="hal-W", src_doc_id=1),
        _src("scanr", src_pub_id=20, hal_id="hal-W", src_doc_id=2),
    ]
    hal_rows = [_hal("hal-W", hal_pub_id=21)]

    _, merge_needed = find_duplicates(conn=None, queries=_FakeQueries(src_rows, hal_rows))

    assert len(merge_needed) == 1


def test_no_match_when_hal_id_absent_from_hal_table():
    """Si le hal_id côté source non-HAL ne correspond à aucun source_publications HAL → ignoré."""
    src_rows = [_src("scanr", src_pub_id=30, hal_id="hal-orphan")]
    hal_rows = [_hal("hal-otherid", hal_pub_id=99)]

    link_only, merge_needed = find_duplicates(conn=None, queries=_FakeQueries(src_rows, hal_rows))

    assert link_only == []
    assert merge_needed == []
