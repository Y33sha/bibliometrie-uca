"""Ordres de `grants.sql` : un ordre de droits par élément, sans commentaire."""

from infrastructure.db.grants import grant_statements


def test_statements_are_privilege_orders():
    statements = grant_statements()

    assert statements
    assert all(s.startswith(("GRANT", "REVOKE", "DO $$")) for s in statements)
    assert not any("--" in s for s in statements)


def test_do_blocks_are_whole_statements():
    blocks = [s for s in grant_statements() if s.startswith("DO $$")]

    assert len(blocks) == 2
    assert all(s.endswith("END LOOP;\nEND\n$$") for s in blocks)


def test_api_writes_on_merge_redirects():
    assert any(
        "public.merge_redirects" in s and "bibliometrie_app" in s and s.startswith("GRANT INSERT")
        for s in grant_statements()
    )
