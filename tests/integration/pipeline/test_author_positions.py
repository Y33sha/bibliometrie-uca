"""Premier et dernier auteur des contributions, votés par les listes d'auteurs de la publication (`propagate_contribution_attributes_sql`)."""

from sqlalchemy import Connection, text

from tests.integration.helpers.alignment import (
    align_source_contributions,
    recompose_contribution_attributes,
)
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record


def _publication(conn: Connection, lists: dict[tuple[str, str], list[str]]) -> dict[str, int]:
    """Insère une publication aux listes d'auteurs `lists`, indexées par `(source, source_id)`, aligne les contributions sources de même nom, et renvoie les contributions par nom."""
    publication = insert_publication(conn)
    members: dict[str, list[tuple[int, int]]] = {}
    for (source, source_id), names in lists.items():
        source_record = insert_source_record(conn, publication, source=source, source_id=source_id)
        for position, name in enumerate(names, start=1):
            source_contribution = insert_source_contribution(
                conn,
                source_record,
                source=source,
                author_position=position,
                raw_author_name=name,
                author_name_normalized=name.lower(),
            )
            members.setdefault(name, []).append((source_contribution, source_record))
    contributions = {
        name: align_source_contributions(conn, publication, m) for name, m in members.items()
    }
    recompose_contribution_attributes(conn)
    return contributions


def _with_position(conn: Connection, contributions: dict[str, int], position: str) -> list[str]:
    ids = conn.execute(
        text(
            "SELECT id FROM contributions"
            " WHERE id = ANY(:ids) AND CAST(:position AS author_position) = ANY(author_positions)"
        ),
        {"ids": list(contributions.values()), "position": position},
    ).scalars()
    names = {v: k for k, v in contributions.items()}
    return sorted(names[i] for i in ids)


def test_deux_listes_plus_courtes_concordantes_l_emportent_sur_la_plus_longue(sa_sync_conn):
    contributions = _publication(
        sa_sync_conn,
        {
            ("hal", "hal-1"): ["A", "B", "C"],
            ("openalex", "W1"): ["A", "B"],
            ("crossref", "10.1/x"): ["A", "B"],
        },
    )

    assert _with_position(sa_sync_conn, contributions, "first") == ["A"]
    assert _with_position(sa_sync_conn, contributions, "last") == ["B"]


def test_une_liste_d_un_seul_auteur_plus_courte_ne_vote_pas_pour_le_dernier(sa_sync_conn):
    contributions = _publication(
        sa_sync_conn,
        {
            ("hal", "hal-1"): ["A", "B", "C"],
            ("openalex", "W1"): ["A"],
            ("crossref", "10.1/x"): ["A"],
        },
    )

    assert _with_position(sa_sync_conn, contributions, "first") == ["A"]
    assert _with_position(sa_sync_conn, contributions, "last") == ["C"]


def test_une_liste_scanr_coupee_ne_vote_pas_pour_le_dernier(sa_sync_conn):
    names = [f"N{i}" for i in range(1, 43)]
    contributions = _publication(
        sa_sync_conn,
        {("hal", "hal-1"): names, ("scanr", "doi10.1/x"): names[:41]},
    )

    assert _with_position(sa_sync_conn, contributions, "last") == ["N42"]


def test_la_copie_scanr_d_un_depot_hal_present_ne_vote_pas(sa_sync_conn):
    contributions = _publication(
        sa_sync_conn,
        {
            ("hal", "hal-1"): ["A", "B"],
            ("scanr", "halhal-1"): ["A", "B"],
            ("openalex", "W1"): ["A", "C"],
            ("crossref", "10.1/x"): ["A", "C"],
        },
    )

    assert _with_position(sa_sync_conn, contributions, "last") == ["C"]


def test_une_egalite_laisse_la_publication_sans_dernier_auteur(sa_sync_conn):
    contributions = _publication(
        sa_sync_conn,
        {("hal", "hal-1"): ["A", "B"], ("openalex", "W1"): ["A", "C"]},
    )

    assert _with_position(sa_sync_conn, contributions, "first") == ["A"]
    assert _with_position(sa_sync_conn, contributions, "last") == []
