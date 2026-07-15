"""SQL du lien personne ↔ `source_authorships` : pose, retrait et lecture du `person_id` des signatures.

La recomposition des lignes consolidées (`authorships`) qui en découlent vit dans `infrastructure/repositories/authorship_repository.py`.
"""

from sqlalchemy import Connection, text


def link_authorship(
    conn: Connection,
    person_id: int,
    source: str,
    authorship_id: int,
    resolution_mode: str,
) -> None:
    """Rattache une authorship source à une personne, en marquant le canal de résolution.

    `resolution_mode` (`identifier` / `name` / `cross_source`) enregistre par quel canal
    le `person_id` a été posé ; il porte les réinitialisations ordre-indépendantes de la
    phase personnes.
    """
    conn.execute(
        text(
            "UPDATE source_authorships SET person_id = :pid, "
            "resolution_mode = CAST(:mode AS resolution_mode) "
            "WHERE id = :aid AND source = :src"
        ),
        {"pid": person_id, "aid": authorship_id, "src": source, "mode": resolution_mode},
    )


def unlink_authorship(conn: Connection, person_id: int, source: str, authorship_id: int) -> None:
    conn.execute(
        text("""
            UPDATE source_authorships SET person_id = NULL
            WHERE id = :aid AND person_id = :pid AND source = :src
        """),
        {"aid": authorship_id, "pid": person_id, "src": source},
    )


def find_source_authorship_owner(conn: Connection, source: str, authorship_id: int) -> int | None:
    """`person_id` d'une signature source. `None` si elle est orpheline ou n'existe pas."""
    return conn.execute(
        text("SELECT person_id FROM source_authorships WHERE id = :aid AND source = :src"),
        {"aid": authorship_id, "src": source},
    ).scalar_one_or_none()


def assign_orphan_sa(
    conn: Connection, person_id: int, source: str, authorship_id: int
) -> dict | None:
    """Tente de poser person_id sur une source_authorship orpheline.

    Retourne un dict {author_name_normalized} si l'UPDATE a touché une ligne, `None` sinon — la signature n'existe pas, ou elle porte déjà un `person_id` (fût-ce celui demandé). `find_source_authorship_owner` départage.
    """
    row = conn.execute(
        text("""
            UPDATE source_authorships sa SET person_id = :pid
            FROM author_identifying_keys aik
            WHERE sa.id = :aid AND sa.source = :src AND sa.person_id IS NULL
              AND aik.id = sa.identity_id
            RETURNING aik.author_name_normalized
        """),
        {"pid": person_id, "aid": authorship_id, "src": source},
    ).first()
    return dict(row._mapping) if row else None


# ── Opérations atomiques pour le use case `assign_orphans` ──────────
# Ces fonctions sont orchestrées par `application/authorships/assign_orphans.py`.
# Chaque fonction = une requête SQL ; aucune décision métier (les
# priorités de sources sont passées en paramètre par le use case).


def assign_orphan_source_authorships_to_person(
    conn: Connection, person_id: int, sa_ids: list[int]
) -> int:
    """Pose `person_id` sur les source_authorships du lot qui sont orphelines.

    Retourne le nombre de lignes effectivement modifiées (celles qui
    étaient `person_id IS NULL`). Les autres sont laissées intactes.
    """
    if not sa_ids:
        return 0
    return conn.execute(
        text("""
            UPDATE source_authorships SET person_id = :pid
            WHERE id = ANY(:ids) AND person_id IS NULL
            RETURNING id
        """),
        {"pid": person_id, "ids": sa_ids},
    ).rowcount


def get_distinct_name_forms_from_source_authorships(
    conn: Connection, sa_ids: list[int]
) -> list[str]:
    """Retourne les `author_name_normalized` distincts observés dans le lot."""
    if not sa_ids:
        return []
    rows = conn.execute(
        text("""
            SELECT DISTINCT aik.author_name_normalized
            FROM source_authorships sa
            JOIN author_identifying_keys aik ON aik.id = sa.identity_id
            WHERE sa.id = ANY(:ids)
              AND aik.author_name_normalized IS NOT NULL
        """),
        {"ids": sa_ids},
    ).all()
    return [row.author_name_normalized for row in rows]


def find_publication_id_for_source_authorship(
    conn: Connection, source: str, authorship_id: int
) -> int | None:
    """Résout la `publication_id` côté `source_publications` pour une
    source_authorship donnée. None si la sa n'existe pas ou n'est pas
    rattachée à une publication."""
    return conn.execute(
        text("""
            SELECT d.publication_id FROM source_authorships sa
            JOIN source_publications d ON d.id = sa.source_publication_id
            WHERE sa.id = :aid AND sa.source = :src
        """),
        {"aid": authorship_id, "src": source},
    ).scalar_one_or_none()


def null_person_id_for_name_form(conn: Connection, person_id: int, name_form: str) -> int:
    """Détache (person_id → NULL) les source_authorships d'une personne portant une
    forme de nom donnée. Sert au rejet d'une forme : ses signatures sont retirées de
    la personne. Retourne le nombre de signatures détachées."""
    return conn.execute(
        text(
            "UPDATE source_authorships sa SET person_id = NULL "
            "FROM author_identifying_keys aik "
            "WHERE sa.person_id = :pid AND aik.id = sa.identity_id "
            "AND aik.author_name_normalized = :nf"
        ),
        {"pid": person_id, "nf": name_form},
    ).rowcount


def find_publication_ids_for_source_authorships(conn: Connection, sa_ids: list[int]) -> list[int]:
    """Les `publication_id` distincts couverts par un lot de source_authorships."""
    if not sa_ids:
        return []
    rows = conn.execute(
        text("""
            SELECT DISTINCT d.publication_id FROM source_authorships sa
            JOIN source_publications d ON d.id = sa.source_publication_id
            WHERE sa.id = ANY(:ids) AND d.publication_id IS NOT NULL
        """),
        {"ids": sa_ids},
    ).all()
    return [row.publication_id for row in rows]
