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
from utils.sources import ALL_SOURCES_SET

# ── Création ──


def create_person(cur, last_name: str, first_name: str = "") -> int:
    """Crée une personne et retourne son id."""
    repo = PgPersonRepository(cur)
    person_id = repo.create(last_name, first_name)
    repo.refresh_name_forms(person_id, compute_person_name_forms(last_name, first_name))
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
    repo = PgPersonRepository(cur)
    repo.update_name(person_id, last_name, first_name)
    repo.refresh_name_forms(person_id, compute_person_name_forms(last_name, first_name))


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

    Pour HAL avec un compte HAL, fait aussi le dual-write sur source_persons
    (propagation attendue par l'étape 0 du pipeline).
    """
    if source not in ALL_SOURCES_SET:
        return
    PgPersonRepository(cur).link_authorship(
        person_id, source, authorship_id,
        source_person_id=source_person_id,
        has_hal_person_id=has_hal_person_id,
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
        PgPersonRepository(cur).unlink_authorship(person_id, source, authorship_id)


# ── Identifiants ──


def add_identifier(
    cur, person_id: int, id_type: str, id_value: str, source: str = "auto", status: str = "pending"
) -> None:
    """Ajoute un identifiant (ORCID, idHAL, IdRef...) à une personne.

    Si l'identifiant existe avec statut 'rejected', le réattribue
    (nouveau person_id, statut pending). Si 'pending' ou 'confirmed',
    ne fait rien.
    """
    PgPersonRepository(cur).add_identifier(person_id, id_type, id_value, source, status)


def remove_identifier(cur, person_id: int, id_type: str, id_value: str) -> None:
    """Supprime un identifiant d'une personne.

    Lève NotFoundError si l'identifiant n'existe pas.
    """
    PgPersonRepository(cur).remove_identifier(person_id, id_type, id_value)
    emit_event(
        cur, "person_identifier.removed", "person", person_id,
        {"id_type": id_type, "id_value": id_value},
    )


def update_identifier_status(cur, ident_id: int, status: str) -> dict:
    """Met à jour le statut d'un identifiant (pending/confirmed/rejected).

    Retourne la ligne {id, status} mise à jour.
    Lève NotFoundError si l'identifiant n'existe pas.
    """
    row = PgPersonRepository(cur).update_identifier_status(ident_id, status)
    emit_event(
        cur, "person_identifier.status_changed", "person", row["person_id"],
        {"ident_id": ident_id, "status": status},
    )
    return {"id": row["id"], "status": row["status"]}


def reassign_identifier(cur, ident_id: int, target_person_id: int) -> None:
    """Réattribue un identifiant à une autre personne (status → pending).

    Lève NotFoundError si l'identifiant n'existe pas.
    """
    PgPersonRepository(cur).reassign_identifier(ident_id, target_person_id)
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

    Shim : calcule les formes via le domaine et délègue au repository.
    """
    forms = compute_person_name_forms(last_name, first_name)
    PgPersonRepository(cur).refresh_name_forms(person_id, forms)


def add_name_form(cur, person_id: int, full_name: str, source: str | None = None) -> None:
    """Ajoute une forme de nom à person_name_forms si elle n'existe pas déjà."""
    PgPersonRepository(cur).add_name_form(person_id, full_name, source=source)


def detach_name_form(cur, person_id: int, name_form: str) -> None:
    """Détache une personne d'une forme de nom. Supprime la forme si
    person_ids devient vide."""
    PgPersonRepository(cur).detach_name_form(person_id, name_form)


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

    1. Valide la source
    2. Met person_id sur l'authorship source (seulement si elle est orpheline)
    3. Ajoute la forme de nom (si authorship non exclue)
    4. Crée/met à jour l'authorship vérité + FK source

    Retourne True si l'authorship a été attribuée, False sinon.
    """
    if source not in _SOURCE_CONFIG:
        raise ValidationError(f"Source inconnue : {source}")

    repo = PgPersonRepository(cur)
    row = repo.assign_orphan_sa(person_id, source, authorship_id)
    if not row:
        return False

    # Ajouter la forme de nom (sauf si authorship exclue)
    if row["author_name_normalized"] and not row.get("excluded"):
        repo.add_name_form(person_id, row["author_name_normalized"], source=source)

    # Créer/mettre à jour l'authorship vérité
    repo.ensure_truth_authorship(person_id, source, authorship_id)
    return True


def batch_assign_orphan_authorships(cur, person_id: int, sa_ids: list[int]) -> int:
    """Attribue en batch plusieurs authorships sources orphelines à une personne.

    Retourne le nombre de source_authorships effectivement rattachées
    (celles qui étaient orphelines).
    """
    return PgPersonRepository(cur).batch_assign_orphans(person_id, sa_ids)


def detach_authorships(cur, person_id: int, authorships: list[dict],
                        name_form: str | None = None) -> dict:
    """Détache un lot d'authorships sources d'une personne et nettoie les
    authorships vérité devenues orphelines.

    Si `name_form` est fourni, supprime aussi la forme de nom de la personne
    lorsque plus aucune authorship ne la porte.

    Retourne {"detached": N, "deleted_authorships": M, "cleaned_form": bool}.
    """
    repo = PgPersonRepository(cur)
    for a in authorships:
        if a["source"] in ALL_SOURCES_SET:
            repo.unlink_authorship(person_id, a["source"], a["authorship_id"])

    deleted = delete_orphan_authorships(cur, person_id)

    cleaned_form = False
    if name_form and repo.count_authorships_with_name_form(person_id, name_form) == 0:
        repo.detach_name_form(person_id, name_form)
        cleaned_form = True

    return {
        "detached": len(authorships),
        "deleted_authorships": deleted,
        "cleaned_form": cleaned_form,
    }


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
