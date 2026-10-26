"""Revues homonymes de deux éditeurs à fusionner : paires fusionnables et paires bloquantes."""

from domain.publishers.merge import SharedTitlePair, split_shared_title_pairs
from domain.serials.issns import IssnSupport, SerialIssn


def _pair(target_id: int, source_id: int, target_issn: str = "", source_issn: str = ""):
    def issns(value: str) -> tuple[SerialIssn, ...]:
        return (SerialIssn(issn=value, support=IssnSupport.PRINT),) if value else ()

    return SharedTitlePair(
        target_serial_id=target_id,
        target_title=f"Revue {target_id}",
        target_issns=issns(target_issn),
        source_serial_id=source_id,
        source_title=f"Revue {source_id}",
        source_issns=issns(source_issn),
    )


class TestSplitSharedTitlePairs:
    def test_pair_with_same_issn_is_mergeable(self):
        pair = _pair(1, 2, "0028-0836", "0028-0836")
        assert split_shared_title_pairs([pair]) == ([pair], [])

    def test_conflicting_issns_block(self):
        mergeable, blockers = split_shared_title_pairs([_pair(1, 2, "0028-0836", "1476-4687")])
        assert mergeable == []
        assert [b["target_serial_id"] for b in blockers] == [1]
        assert "cible / source" in blockers[0]["reason"]

    def test_serial_in_two_pairs_blocks_both(self):
        """Deux revues source homonymes d'une même revue cible : l'éditeur source contient un doublon."""
        mergeable, blockers = split_shared_title_pairs([_pair(1, 2), _pair(1, 3), _pair(4, 5)])
        assert mergeable == [_pair(4, 5)]
        assert [(b["source_serial_id"], b["reason"]) for b in blockers] == [
            (2, "doublon interne dans l'éditeur cible (titre dédupliqué)"),
            (3, "doublon interne dans l'éditeur cible (titre dédupliqué)"),
        ]
