"""
Service Référentiel Personnes — accès exclusif en écriture aux tables
`persons`, `person_identifiers`, `person_name_forms`.

Gère aussi le rattachement/détachement des authorships sources
(source_authorships) puisque le person_id y est la source de vérité
du lien personne.

Les auteurs sources sont dans la table unifiée `source_persons`
(UNIQUE(source, source_id)), les authorships utilisent `source_person_id`.
"""

from domain.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.repositories.person_repository import PgPersonRepository
from services.audit import emit_event
from services.authorships import delete_orphan_authorships
from utils.normalize import normalize_name
from utils.perimeter import get_persons_structure_ids_list
from utils.sources import ALL_SOURCES_SET, AUTHOR_SOURCES_SQL

# ── Création ──


def create_person(cur, last_name: str, first_name: str = "") -> int:
    """Crée une personne et retourne son id."""
    cur.execute(
        """
        INSERT INTO persons (last_name, first_name,
                             last_name_normalized, first_name_normalized)
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """,
        (last_name, first_name, normalize_name(last_name), normalize_name(first_name)),
    )
    person_id = cur.fetchone()["id"]
    refresh_person_name_forms(cur, person_id, last_name, first_name)
    return person_id


def set_rejected(cur, person_id: int, rejected: bool) -> None:
    """Marque ou démarque une personne comme rejetée (fausse entité).

    Lève NotFoundError si la personne n'existe pas.
    """
    PgPersonRepository(cur).set_rejected(person_id, rejected)
    emit_event(cur, "person.rejected", "person", person_id, {"rejected": rejected})


def update_name(cur, person_id: int, last_name: str, first_name: str) -> None:
    """Met à jour le nom/prénom d'une personne et rafraîchit ses formes de nom.

    Lève NotFoundError si la personne n'existe pas.
    """
    cur.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
    if not cur.fetchone():
        raise NotFoundError(f"Personne {person_id} introuvable")

    cur.execute(
        """
        UPDATE persons SET last_name = %s, first_name = %s,
               last_name_normalized = %s,
               first_name_normalized = %s,
               updated_at = now()
        WHERE id = %s
        """,
        (
            last_name, first_name,
            normalize_name(last_name), normalize_name(first_name),
            person_id,
        ),
    )
    refresh_person_name_forms(cur, person_id, last_name, first_name)


# ── Rattachement / détachement authorships ──


def link_authorship(
    cur,
    person_id: int,
    source: str,
    authorship_id: int,
    *,
    source_person_id: int | None = None,
    has_hal_person_id: bool = False,
) -> None:
    """Rattache une authorship source à une personne (pipeline).

    Pour HAL, fait aussi le dual-write sur source_persons si c'est un
    compte HAL (hal_person_id renseigné). Ceci permet à l'étape 0 du
    pipeline de propager aux autres authorships du même compte.
    """
    if source not in ALL_SOURCES_SET:
        return

    cur.execute(
        "UPDATE source_authorships SET person_id = %s WHERE id = %s AND source = %s",
        (person_id, authorship_id, source),
    )

    if source == "hal" and source_person_id and has_hal_person_id:
        cur.execute(
            """
            UPDATE source_persons SET person_id = %s
            WHERE id = %s AND (source_ids->>'hal_person_id') IS NOT NULL
        """,
            (person_id, source_person_id),
        )


def link_authorships(cur, person_id: int, authorships: list[dict]) -> None:
    """Rattache un groupe d'authorships à une personne (pipeline).

    Chaque dict doit avoir 'source' et 'authorship_id',
    et optionnellement 'source_person_id' et 'has_hal_person_id'.
    """
    for a in authorships:
        link_authorship(
            cur,
            person_id,
            a["source"],
            a["authorship_id"],
            source_person_id=a.get("source_person_id"),
            has_hal_person_id=a.get("has_hal_person_id", False),
        )


def unlink_authorship(cur, person_id: int, source: str, authorship_id: int) -> None:
    """Détache une authorship source d'une personne (met person_id à NULL)."""
    if source in ALL_SOURCES_SET:
        cur.execute(
            "UPDATE source_authorships SET person_id = NULL WHERE id = %s AND person_id = %s AND source = %s",
            (authorship_id, person_id, source),
        )


# ── Identifiants ──


def add_identifier(
    cur, person_id: int, id_type: str, id_value: str, source: str = "auto", status: str = "pending"
) -> None:
    """Ajoute un identifiant (ORCID, idHAL, IdRef...) à une personne.

    Si l'identifiant existe avec statut 'rejected', le réattribue
    (nouveau person_id, statut pending).
    Si 'pending' ou 'confirmed', ne fait rien.
    """
    cur.execute(
        """
        INSERT INTO person_identifiers (person_id, id_type, id_value, source, status)
        VALUES (%s, %s, %s, %s, %s::identifier_status)
        ON CONFLICT (id_type, id_value) DO UPDATE SET
            person_id = EXCLUDED.person_id,
            source = EXCLUDED.source,
            status = 'pending'
        WHERE person_identifiers.status = 'rejected'
    """,
        (person_id, id_type, id_value, source, status),
    )

    # Attribution d'un idhal → rattacher le compte HAL correspondant
    if id_type == "idhal":
        cur.execute(
            """
            UPDATE source_persons SET person_id = %s
            WHERE source = 'hal'
              AND source_ids->>'idhal' = %s
              AND (person_id IS NULL OR person_id != %s)
        """,
            (person_id, id_value, person_id),
        )


def remove_identifier(cur, person_id: int, id_type: str, id_value: str) -> None:
    """Supprime un identifiant d'une personne.

    Lève NotFoundError si l'identifiant n'existe pas.
    """
    cur.execute(
        """
        DELETE FROM person_identifiers
        WHERE person_id = %s AND id_type = %s AND id_value = %s
        """,
        (person_id, id_type, id_value),
    )
    if cur.rowcount == 0:
        raise NotFoundError("Identifiant introuvable")
    emit_event(
        cur, "person_identifier.removed", "person", person_id,
        {"id_type": id_type, "id_value": id_value},
    )


def update_identifier_status(cur, ident_id: int, status: str) -> dict:
    """Met à jour le statut d'un identifiant (pending/confirmed/rejected).

    Retourne la ligne {id, status} mise à jour.
    Lève NotFoundError si l'identifiant n'existe pas.
    """
    cur.execute(
        """
        UPDATE person_identifiers SET status = %s::identifier_status
        WHERE id = %s RETURNING id, status::text AS status, person_id
        """,
        (status, ident_id),
    )
    row = cur.fetchone()
    if not row:
        raise NotFoundError(f"Identifiant {ident_id} introuvable")
    emit_event(
        cur, "person_identifier.status_changed", "person", row["person_id"],
        {"ident_id": ident_id, "status": status},
    )
    # Retire person_id du retour pour préserver le contrat existant
    return {"id": row["id"], "status": row["status"]}


def reassign_identifier(cur, ident_id: int, target_person_id: int) -> None:
    """Réattribue un identifiant à une autre personne (status → pending).

    Lève NotFoundError si l'identifiant n'existe pas.
    """
    cur.execute(
        """
        UPDATE person_identifiers
        SET person_id = %s, status = 'pending'::identifier_status
        WHERE id = %s
        """,
        (target_person_id, ident_id),
    )
    if cur.rowcount == 0:
        raise NotFoundError(f"Identifiant {ident_id} introuvable")
    emit_event(
        cur, "person_identifier.reassigned", "person", target_person_id,
        {"ident_id": ident_id},
    )


def add_identifiers_from_authorships(cur, person_id: int, authorships: list[dict]) -> None:
    """Ajoute les ORCID, idHAL et IdRef trouvés dans un groupe d'authorships."""
    seen = set()
    for a in authorships:
        if a.get("orcid") and ("orcid", a["orcid"]) not in seen:
            add_identifier(cur, person_id, "orcid", a["orcid"])
            seen.add(("orcid", a["orcid"]))
        if a.get("idhal") and ("idhal", a["idhal"]) not in seen:
            add_identifier(cur, person_id, "idhal", a["idhal"])
            seen.add(("idhal", a["idhal"]))
        if a.get("idref") and ("idref", a["idref"]) not in seen:
            idref_source = a.get("source", "hal")
            add_identifier(cur, person_id, "idref", a["idref"], source=idref_source)
            seen.add(("idref", a["idref"]))


# ── Formes de noms ──


def compute_person_name_forms(last_name: str, first_name: str) -> set[str]:
    """Calcule les variantes normalisées de formes de nom pour une personne.

    Retourne un ensemble de formes normalisées :
      - "prenom nom", "nom prenom"
      - "initiale(s) nom", "nom initiale(s)"
        Si le prénom a plusieurs mots (ex: "jean michel"), produit :
        - initiales séparées : "j m nom", "nom j m"
        - initiales collées  : "jm nom", "nom jm"
    """
    ln = normalize_name(last_name)
    fn = normalize_name(first_name)
    if not ln:
        return set()

    forms = set()
    if fn:
        forms.add(f"{fn} {ln}")
        forms.add(f"{ln} {fn}")

        parts = fn.split()
        if parts:
            initials_spaced = " ".join(p[0] for p in parts)
            initials_joined = "".join(p[0] for p in parts)
            forms.add(f"{initials_spaced} {ln}")
            forms.add(f"{ln} {initials_spaced}")
            if initials_joined != initials_spaced:
                forms.add(f"{initials_joined} {ln}")
                forms.add(f"{ln} {initials_joined}")
    else:
        forms.add(ln)

    return forms


def refresh_person_name_forms(cur, person_id: int, last_name: str, first_name: str) -> None:
    """Recalcule les formes de nom source 'persons' d'une personne.

    Supprime les anciennes formes 'persons' de cette personne, puis insère
    les nouvelles. Les formes partagées avec d'autres personnes ou d'autres
    sources sont préservées (seul le person_id et la source sont retirés/ajoutés).
    """
    # 1a. Formes dont 'persons' est la seule source : retirer le person_id
    cur.execute(
        """
        UPDATE person_name_forms
        SET person_ids = array_remove(person_ids, %s)
        WHERE %s = ANY(person_ids)
          AND sources = ARRAY['persons']
    """,
        (person_id, person_id),
    )
    # 1b. Formes multi-sources : retirer 'persons' de sources, garder person_id
    cur.execute(
        """
        UPDATE person_name_forms
        SET sources = array_remove(sources, 'persons'),
            updated_at = now()
        WHERE %s = ANY(person_ids)
          AND 'persons' = ANY(sources)
          AND array_length(sources, 1) > 1
    """,
        (person_id,),
    )
    # 1c. Nettoyer les formes devenues vides
    cur.execute("""
        DELETE FROM person_name_forms
        WHERE person_ids = '{}' OR person_ids IS NULL
    """)

    # 2. Ajouter les nouvelles formes
    for form in compute_person_name_forms(last_name, first_name):
        add_name_form(cur, person_id, form, source="persons")


def add_name_form(cur, person_id: int, full_name: str, source: str | None = None) -> None:
    """Ajoute une forme de nom à person_name_forms si elle n'existe pas déjà.

    Si source est fourni (ex: 'hal', 'openalex', 'persons'), il est ajouté
    au tableau sources de la forme de nom.
    """
    if not full_name or not full_name.strip():
        return
    norm = normalize_name(full_name)
    if not norm:
        return
    if source:
        cur.execute(
            """
            INSERT INTO person_name_forms (name_form, person_ids, sources)
            VALUES (%s, ARRAY[%s], ARRAY[%s])
            ON CONFLICT (name_form) DO UPDATE
            SET person_ids = (
                    SELECT array_agg(DISTINCT x)
                    FROM unnest(person_name_forms.person_ids || ARRAY[%s]) AS x
                ),
                sources = (
                    SELECT array_agg(DISTINCT x ORDER BY x)
                    FROM unnest(COALESCE(person_name_forms.sources, '{}') || ARRAY[%s]) AS x
                ),
                updated_at = now()
        """,
            (norm, person_id, source, person_id, source),
        )
    else:
        cur.execute(
            """
            INSERT INTO person_name_forms (name_form, person_ids)
            VALUES (%s, ARRAY[%s])
            ON CONFLICT (name_form) DO UPDATE
            SET person_ids = (
                SELECT array_agg(DISTINCT x)
                FROM unnest(person_name_forms.person_ids || ARRAY[%s]) AS x
            )
        """,
            (norm, person_id, person_id),
        )


def detach_name_form(cur, person_id: int, name_form: str) -> bool:
    """Détache une personne d'une forme de nom.

    Retire person_id de person_ids. Supprime la forme si person_ids devient vide.
    Retourne True si le détachement a eu lieu.
    """
    cur.execute(
        """
        UPDATE person_name_forms
        SET person_ids = array_remove(person_ids, %s)
        WHERE name_form = %s
    """,
        (person_id, name_form),
    )
    cur.execute(
        """
        DELETE FROM person_name_forms
        WHERE name_form = %s AND person_ids = '{}'
    """,
        (name_form,),
    )
    return True


# ── Rattachement / détachement par auteur source ──
# Ces fonctions opèrent par author_id (pas authorship_id) : elles rattachent
# ou détachent TOUTES les authorships d'un auteur source, propagent vers
# les authorships vérité, et gèrent les identifiants.

# Config par source
_SOURCE_CONFIG = {
    "hal": {
        "author_fk": "source_person_id",
        "id_fields": ["orcid"],
        "source_ids_fields": {"idhal": "idhal"},
    },
    "openalex": {
        "author_fk": "source_person_id",
        "id_fields": ["orcid"],
        "source_ids_fields": {},
    },
    "wos": {
        "author_fk": "source_person_id",
        "id_fields": ["orcid"],
        "source_ids_fields": {},
    },
    "scanr": {
        "author_fk": "source_person_id",
        "id_fields": ["orcid", "idref"],
        "source_ids_fields": {},
    },
    "theses": {
        "author_fk": "source_person_id",
        "id_fields": ["orcid", "idref"],
        "source_ids_fields": {},
    },
}


# ── Attribution d'authorships orphelines ──


def assign_orphan_authorship(cur, person_id: int, source: str, authorship_id: int) -> bool:
    """Attribue une authorship orpheline (person_id IS NULL) à une personne.

    1. Met person_id sur l'authorship source (seulement si NULL)
    2. Récupère le nom de l'auteur
    3. Ajoute la forme de nom (si authorship non exclue)
    4. Crée/met à jour l'authorship vérité + FK source

    Retourne True si l'authorship a été attribuée, False sinon.
    """
    cfg = _SOURCE_CONFIG.get(source)
    if not cfg:
        raise ValidationError(f"Source inconnue : {source}")

    # 1. Rattacher et récupérer le nom normalisé + statut excluded
    cur.execute(
        """
        UPDATE source_authorships SET person_id = %s WHERE id = %s AND source = %s AND person_id IS NULL
        RETURNING excluded, author_name_normalized
    """,
        (person_id, authorship_id, source),
    )

    row = cur.fetchone()
    if not row:
        return False

    # 2. Ajouter la forme de nom (sauf si authorship exclue)
    if row["author_name_normalized"] and not row.get("excluded"):
        add_name_form(cur, person_id, row["author_name_normalized"], source=source)

    # 3. Créer/mettre à jour l'authorship vérité
    _ensure_truth_authorship(cur, person_id, source, authorship_id)

    return True


def batch_assign_orphan_authorships(cur, person_id: int, sa_ids: list[int]) -> int:
    """Attribue en batch plusieurs authorships sources orphelines à une personne.

    Plus efficace que boucler sur `assign_orphan_authorship` quand on a
    plusieurs dizaines d'authorships à rattacher à la même personne :
    1. SET person_id sur les source_authorships (seulement si NULL)
    2. Crée les authorships vérité manquantes (une par publication)
    3. Pose les FK source_authorships.authorship_id
    4. Ajoute les formes de nom observées (auteur normalisé)

    Retourne le nombre de source_authorships effectivement rattachées
    (celles qui étaient orphelines).
    """
    if not sa_ids:
        return 0

    # 1. Rattacher les source_authorships orphelines
    cur.execute(
        """
        UPDATE source_authorships SET person_id = %s
        WHERE id = ANY(%s) AND person_id IS NULL
        RETURNING id
        """,
        (person_id, sa_ids),
    )
    assigned = cur.rowcount

    # 2. Créer les authorships vérité manquantes
    cur.execute(
        """
        INSERT INTO authorships (publication_id, person_id,
            author_position, in_perimeter, is_corresponding, structure_ids)
        SELECT DISTINCT ON (sd.publication_id)
            sd.publication_id, %s,
            sa.author_position, sa.in_perimeter, sa.is_corresponding, sa.structure_ids
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        WHERE sa.id = ANY(%s) AND sd.publication_id IS NOT NULL
        ORDER BY sd.publication_id,
            CASE sa.source WHEN 'hal' THEN 1 WHEN 'openalex' THEN 2 WHEN 'wos' THEN 3 END
        ON CONFLICT (publication_id, person_id) DO NOTHING
        """,
        (person_id, sa_ids),
    )

    # 3. Poser les FK authorship_id sur les source_authorships
    cur.execute(
        """
        UPDATE source_authorships sa SET authorship_id = a.id
        FROM source_publications sd, authorships a
        WHERE sa.id = ANY(%s)
          AND sd.id = sa.source_publication_id
          AND a.publication_id = sd.publication_id
          AND a.person_id = %s
          AND sa.authorship_id IS NULL
        """,
        (sa_ids, person_id),
    )

    # 4. Ajouter les formes de noms observées
    cur.execute(
        """
        SELECT DISTINCT author_name_normalized
        FROM source_authorships
        WHERE id = ANY(%s)
          AND author_name_normalized IS NOT NULL
          AND NOT excluded
        """,
        (sa_ids,),
    )
    for row in cur.fetchall():
        add_name_form(cur, person_id, row["author_name_normalized"])

    return assigned


def detach_authorships(cur, person_id: int, authorships: list[dict],
                        name_form: str | None = None) -> dict:
    """Détache un lot d'authorships sources d'une personne et nettoie les
    authorships vérité devenues orphelines.

    Si `name_form` est fourni, supprime aussi la forme de nom de la personne
    lorsque plus aucune authorship ne la porte.

    `authorships` : liste de dicts {source, authorship_id}.

    Retourne {"detached": N, "deleted_authorships": M, "cleaned_form": bool}.
    """
    for a in authorships:
        unlink_authorship(cur, person_id, a["source"], a["authorship_id"])

    deleted = delete_orphan_authorships(cur, person_id)

    cleaned_form = False
    if name_form:
        # Ne nettoyer la forme que si plus aucune source_authorship ne la porte
        cur.execute(
            f"""
            SELECT COUNT(*) FROM source_authorships sa
            WHERE sa.person_id = %s AND sa.author_name_normalized = %s
              AND sa.source IN {AUTHOR_SOURCES_SQL}
            """,
            (person_id, name_form),
        )
        if cur.fetchone()["count"] == 0:
            detach_name_form(cur, person_id, name_form)
            cleaned_form = True

    return {
        "detached": len(authorships),
        "deleted_authorships": deleted,
        "cleaned_form": cleaned_form,
    }


def _ensure_truth_authorship(cur, person_id: int, source: str, authorship_id: int) -> None:
    """Crée/synchronise l'authorship vérité à partir des authorships sources.

    Même logique que build_authorships.py mais pour une seule paire
    (publication_id, person_id) : FK, author_position, is_corresponding,
    in_perimeter, structure_ids.
    """
    _SOURCE_CONFIG[source]

    # Trouver la publication_id via source_publications
    cur.execute(
        """
        SELECT d.publication_id FROM source_authorships sa
        JOIN source_publications d ON d.id = sa.source_publication_id
        WHERE sa.id = %s AND sa.source = %s
    """,
        (authorship_id, source),
    )
    row = cur.fetchone()
    if not row or not row["publication_id"]:
        return
    pub_id = row["publication_id"]

    # 1. INSERT si pas déjà existant
    cur.execute(
        """
        INSERT INTO authorships (publication_id, person_id)
        VALUES (%s, %s)
        ON CONFLICT (publication_id, person_id) DO NOTHING
    """,
        (pub_id, person_id),
    )

    # 2. FK sources (source_authorships.authorship_id → authorships.id)
    cur.execute(
        """
        UPDATE source_authorships sa
        SET authorship_id = a.id
        FROM source_publications sd, authorships a
        WHERE sd.id = sa.source_publication_id
          AND a.publication_id = sd.publication_id
          AND a.person_id = sa.person_id
          AND sd.publication_id = %s
          AND sa.person_id = %s
          AND NOT sa.excluded
          AND sa.authorship_id IS NULL
    """,
        (pub_id, person_id),
    )

    # 3. author_position et is_corresponding
    cur.execute(
        """
        UPDATE authorships a
        SET author_position = sub.pos,
            is_corresponding = COALESCE(a.is_corresponding, sub.corr)
        FROM (
            SELECT sa.authorship_id,
                   (array_agg(sa.author_position ORDER BY
                       CASE sa.source WHEN 'hal' THEN 1 WHEN 'openalex' THEN 2 WHEN 'wos' THEN 3 END
                   ))[1] AS pos,
                   (array_agg(sa.is_corresponding ORDER BY
                       CASE sa.source WHEN 'wos' THEN 1 WHEN 'openalex' THEN 2 WHEN 'hal' THEN 3 END
                   ))[1] AS corr
            FROM source_authorships sa
            WHERE sa.authorship_id IS NOT NULL AND NOT sa.excluded
            GROUP BY sa.authorship_id
        ) sub
        WHERE a.id = sub.authorship_id
          AND a.publication_id = %s AND a.person_id = %s
    """,
        (pub_id, person_id),
    )

    # 4. in_perimeter et structure_ids (union des sources)
    get_persons_structure_ids_list(cur)
    cur.execute(
        f"""
        WITH src AS (
            SELECT sa.in_perimeter AS uca, sa.structure_ids AS sids
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            WHERE sa.source IN {AUTHOR_SOURCES_SQL}
              AND sd.publication_id = %s AND sa.person_id = %s AND NOT sa.excluded
        ),
        agg AS (
            SELECT bool_or(uca) AS in_perimeter,
                   array_agg(DISTINCT sid) FILTER (WHERE sid IS NOT NULL) AS all_sids
            FROM src, LATERAL unnest(COALESCE(sids, '{{}}'::int[])) AS sid
        )
        UPDATE authorships a
        SET in_perimeter = COALESCE(agg.in_perimeter, FALSE),
            structure_ids = NULLIF(agg.all_sids, ARRAY[]::int[]),
            updated_at = now()
        FROM agg
        WHERE a.publication_id = %s AND a.person_id = %s
    """,
        (pub_id, person_id, pub_id, person_id),
    )


# ── Fusion ──


def mark_distinct(cur, person_id_a: int, person_id_b: int) -> None:
    """Marque deux personnes comme distinctes (non-doublon) dans
    `distinct_persons`. Idempotent.

    Les IDs sont triés pour garantir l'unicité de la paire.
    """
    inserted = PgPersonRepository(cur).mark_distinct(person_id_a, person_id_b)
    # Audit seulement si une ligne a été insérée (la paire n'existait pas déjà)
    if inserted:
        emit_event(
            cur, "person.marked_distinct", "person", inserted[0],
            {"other_id": inserted[1]},
        )


def merge_person(cur, target_id: int, source_id: int) -> None:
    """Fusionne la personne source_id dans target_id.

    Transfère tous les auteurs liés, identifiants, authorships et person_name_forms
    de source vers target, puis supprime la personne source.

    Lève RuntimeError si les deux personnes ont chacune une fiche RH distincte.
    """
    # Garde-fou : ne JAMAIS fusionner si les deux ont une fiche RH
    cur.execute(
        """
        SELECT COUNT(*) AS n FROM persons_rh
        WHERE person_id IN (%s, %s)
    """,
        (target_id, source_id),
    )
    if cur.fetchone()["n"] >= 2:
        raise ConflictError(
            f"REFUS de fusion : les personnes #{target_id} et #{source_id} "
            f"ont chacune une fiche RH distincte."
        )

    # 1. Transférer les auteurs sources (comptes HAL/ScanR avec person_id)
    cur.execute(
        "UPDATE source_persons SET person_id = %s WHERE person_id = %s", (target_id, source_id)
    )

    # 1b. Transférer les source_authorships
    cur.execute(
        "UPDATE source_authorships SET person_id = %s WHERE person_id = %s", (target_id, source_id)
    )

    # 4. Transférer les authorships consolidées (supprimer les doublons publication)
    cur.execute(
        """
        DELETE FROM authorships
        WHERE person_id = %s
          AND publication_id IN (
              SELECT publication_id FROM authorships WHERE person_id = %s
          )
    """,
        (source_id, target_id),
    )
    cur.execute(
        "UPDATE authorships SET person_id = %s WHERE person_id = %s", (target_id, source_id)
    )

    # 5. Transférer les identifiants (supprimer doublons)
    cur.execute(
        """
        DELETE FROM person_identifiers
        WHERE person_id = %s
          AND (id_type, id_value) IN (
              SELECT id_type, id_value FROM person_identifiers WHERE person_id = %s
          )
    """,
        (source_id, target_id),
    )
    cur.execute(
        "UPDATE person_identifiers SET person_id = %s WHERE person_id = %s", (target_id, source_id)
    )

    # 6. Transférer persons_rh de la source vers la cible (si la cible n'en a pas)
    cur.execute(
        """
        UPDATE persons_rh SET person_id = %s
        WHERE person_id = %s
          AND NOT EXISTS (SELECT 1 FROM persons_rh WHERE person_id = %s)
    """,
        (target_id, source_id, target_id),
    )

    # 7. Mettre à jour person_name_forms : remplacer source_id par target_id
    #    (pour les formes non-persons : hal, openalex, wos, manual)
    cur.execute(
        """
        UPDATE person_name_forms
        SET person_ids = (
                SELECT array_agg(DISTINCT v ORDER BY v)
                FROM unnest(array_replace(person_ids, %s, %s)) AS v
            ),
            updated_at = now()
        WHERE %s = ANY(person_ids)
    """,
        (source_id, target_id, source_id),
    )

    # 7b. Recalculer les formes source 'persons' du target
    cur.execute("SELECT last_name, first_name FROM persons WHERE id = %s", (target_id,))
    target = cur.fetchone()
    refresh_person_name_forms(cur, target_id, target["last_name"], target["first_name"] or "")

    # 8. Supprimer la personne source
    cur.execute("DELETE FROM persons WHERE id = %s", (source_id,))

    emit_event(cur, "person.merged", "person", target_id, {"source_id": source_id})
