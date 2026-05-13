"""SQL pour `person_name_forms` — colonne de vérité `persons jsonb`.

Format : ``{ "<person_id>": ["<source1>", ...], ... }`` (cf.
`domain/persons/name_forms.py`). Les anciennes colonnes `person_ids` /
`sources` ne sont plus écrites ni lues depuis ce module — elles
seront DROP en Phase 6 du chantier
`DATA_person-name-forms-normalisation`.

Différence d'approche avec l'orchestrateur batch
(`application/pipeline/persons/populate_person_name_forms.py`) : ici le
caller (admin, assign_orphans, etc.) n'a pas pré-chargé l'état en
mémoire, donc la fusion doit se faire côté SQL — d'où le ON CONFLICT
+ `jsonb_set` dans `add_name_form`.
"""

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from domain.normalize import normalize_name
from domain.persons.name_forms import remove_person_source


def refresh_name_forms(conn: Connection, person_id: int, forms: set[str]) -> None:
    """Recalcule les formes de nom source 'persons' d'une personne.

    Retire ``'persons'`` du couple ``(person_id, "persons")`` dans toutes
    les formes où il apparaît (key droppée si plus aucune source ; row
    supprimée si plus aucun person_id). Puis pose les nouvelles formes
    via `add_name_form` (qui gère le ON CONFLICT JSONB).

    `forms` : l'ensemble des formes normalisées calculées par le domaine
    (voir `compute_person_name_forms`).
    """
    pid_text = str(person_id)
    rows = conn.execute(
        text("""
            SELECT id, persons FROM person_name_forms
            WHERE persons ? :pid AND persons->:pid ? 'persons'
        """),
        {"pid": pid_text},
    ).all()

    for row in rows:
        new_persons = remove_person_source(row.persons, person_id, "persons")
        if not new_persons:
            conn.execute(
                text("DELETE FROM person_name_forms WHERE id = :id"),
                {"id": row.id},
            )
        else:
            conn.execute(
                text(
                    "UPDATE person_name_forms SET persons = :p, updated_at = now() WHERE id = :id"
                ).bindparams(bindparam("p", type_=JSONB)),
                {"id": row.id, "p": new_persons},
            )

    for form in forms:
        add_name_form(conn, person_id, form, source="persons")


def add_name_form(
    conn: Connection, person_id: int, full_name: str, source: str | None = None
) -> None:
    """Ajoute une forme de nom à person_name_forms (idempotent).

    Pose la clé ``str(person_id)`` dans `persons jsonb` et, si `source`
    est fourni, l'ajoute aux sources de cette clé. Si la forme existe
    déjà, fusionne au niveau SQL via ON CONFLICT + `jsonb_set` (la
    valeur finale est l'union triée des sources existantes et de la
    nouvelle).
    """
    if not full_name or not full_name.strip():
        return
    norm = normalize_name(full_name)
    if not norm:
        return

    pid_text = str(person_id)
    new_persons = {pid_text: [source] if source else []}

    # Union des sources existantes (table) et nouvelles (EXCLUDED.persons)
    # pour la clé `pid` via deux jsonb_array_elements_text + UNION ALL.
    # On évite un `:bind::text[]` qui casse le parseur de bind de SA
    # (lookahead `(?!:)` qui refuse `:name::`).
    stmt = text("""
        INSERT INTO person_name_forms (name_form, persons)
        VALUES (:nf, :new_persons)
        ON CONFLICT (name_form) DO UPDATE SET
            persons = jsonb_set(
                person_name_forms.persons,
                ARRAY[:pid],
                (
                    SELECT COALESCE(
                        to_jsonb(array_agg(DISTINCT s ORDER BY s)),
                        '[]'::jsonb
                    )
                    FROM (
                        SELECT jsonb_array_elements_text(
                            person_name_forms.persons->:pid
                        ) AS s
                        UNION ALL
                        SELECT jsonb_array_elements_text(
                            EXCLUDED.persons->:pid
                        )
                    ) merged
                ),
                true
            ),
            updated_at = now()
    """).bindparams(bindparam("new_persons", type_=JSONB))
    conn.execute(
        stmt,
        {"nf": norm, "pid": pid_text, "new_persons": new_persons},
    )


def detach_name_form(conn: Connection, person_id: int, name_form: str) -> None:
    """Détache une personne d'une forme de nom. Supprime la forme si orpheline.

    DELETE puis UPDATE (et pas l'inverse) : la CHECK `persons_not_empty`
    rejette l'état intermédiaire `{}` si on UPDATE d'abord sur une row
    qui n'a que cette clé.
    """
    pid_text = str(person_id)
    conn.execute(
        text("""
            DELETE FROM person_name_forms
            WHERE name_form = :nf
              AND persons ? :pid
              AND (SELECT COUNT(*) FROM jsonb_object_keys(persons)) = 1
        """),
        {"pid": pid_text, "nf": name_form},
    )
    conn.execute(
        text(
            "UPDATE person_name_forms SET persons = persons - :pid, updated_at = now() "
            "WHERE name_form = :nf AND persons ? :pid"
        ),
        {"pid": pid_text, "nf": name_form},
    )
