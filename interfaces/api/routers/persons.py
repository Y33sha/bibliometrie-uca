"""Persons router: directory, search, list, profile, merge, identifiers, authors."""

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from application.authorships import (
    exclude_authorship as _exclude_authorship,
)
from application.persons import (
    add_identifier as _add_identifier,
)
from application.persons import (
    assign_orphan_authorship as _assign_orphan,
)
from application.persons import (
    batch_assign_orphan_authorships as _batch_assign_orphan,
)
from application.persons import (
    create_person as _create_person,
)
from application.persons import (
    detach_authorships as _detach_authorships_service,
)
from application.persons import (
    detach_name_form as _detach_name_form,
)
from application.persons import (
    merge_person as _merge_person,
)
from application.persons import (
    reassign_identifier as _reassign_identifier,
)
from application.persons import (
    remove_identifier as _remove_identifier,
)
from application.persons import (
    set_rejected as _set_rejected,
)
from application.persons import (
    update_identifier_status as _update_identifier_status,
)
from application.persons import (
    update_name as _update_name,
)
from domain.sources import ALL_SOURCES_SET, AUTHOR_SOURCES_SQL
from infrastructure.db.queries import persons as persons_queries
from interfaces.api.deps import get_cursor
from interfaces.api.filters import parse_str_csv
from interfaces.api.models import (
    AddIdentifier,
    AssignOrphanAuthorship,
    BatchAssignOrphanAuthorships,
    DetachAuthorships,
    DetachNameForm,
    MergePersons,
    ReassignIdentifier,
    RejectPerson,
    UpdateIdentifierStatus,
    UpdatePersonName,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/persons/directory")
async def persons_directory(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    department: str = Query(""),
    role: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    has_rh: str = Query(""),
    sort: str = Query("name"),
) -> Any:
    """Annuaire public des personnes UCA avec ORCID et idHAL."""
    filters = persons_queries.DirectoryFilters(
        search=search,
        departments=parse_str_csv(department),
        roles=parse_str_csv(role),
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_rh=has_rh,
    )
    with get_cursor() as (cur, _conn):
        return persons_queries.persons_directory(
            cur, filters=filters, page=page, per_page=per_page, sort=sort
        )


@router.get("/api/persons/search")
async def search_persons(
    q: str = Query("", min_length=2), limit: int = Query(10, ge=1, le=30)
) -> Any:
    """Recherche rapide de personnes (autocomplete)."""
    with get_cursor() as (cur, _conn):
        return persons_queries.search_persons(cur, q=q, limit=limit)


@router.get("/api/persons")
async def list_persons(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
    department: str = Query(""),
    role: str = Query(""),
    linked: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    has_rh: str = Query(""),
    sort: str = Query("name"),
) -> Any:
    """Liste des personnes avec filtres (admin)."""
    filters = persons_queries.ListFilters(
        search=search,
        department=department,
        role=role,
        linked=linked,
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_rh=has_rh,
    )
    with get_cursor() as (cur, _conn):
        return persons_queries.list_persons(
            cur, filters=filters, page=page, per_page=per_page, sort=sort
        )


@router.get("/api/persons/facets")
async def persons_facets(
    department: str = Query(""),
    role: str = Query(""),
    has_orcid: str = Query(""),
    has_idhal: str = Query(""),
    has_rh: str = Query(""),
    linked: str = Query(""),
) -> Any:
    """Facettes dynamiques pour la page personnes."""
    filters = persons_queries.FacetFilters(
        departments=parse_str_csv(department),
        roles=parse_str_csv(role),
        has_orcid=has_orcid,
        has_idhal=has_idhal,
        has_rh=has_rh,
        linked=linked,
    )
    with get_cursor() as (cur, _conn):
        return persons_queries.persons_facets(cur, filters=filters)


@router.get("/api/persons/departments")
async def list_departments() -> Any:
    """Liste des départements distincts."""
    with get_cursor() as (cur, _conn):
        return persons_queries.list_departments(cur)


@router.get("/api/persons/roles")
async def list_roles() -> Any:
    """Liste des rôles distincts."""
    with get_cursor() as (cur, _conn):
        return persons_queries.list_roles(cur)


@router.get("/api/persons/stats")
async def persons_stats() -> Any:
    """Statistiques sur les personnes et l'alignement."""
    with get_cursor() as (cur, _conn):
        return persons_queries.persons_stats(cur)


@router.get("/api/persons/{person_id}")
async def get_person(person_id: int) -> Any:
    """Détail d'une personne avec auteurs liés."""
    with get_cursor() as (cur, _conn):
        person = persons_queries.get_person(cur, person_id)
        if not person:
            raise HTTPException(status_code=404, detail="Person not found")
        return person


@router.get("/api/persons/{person_id}/profile")
async def person_profile(person_id: int) -> Any:
    """Profil public complet d'une personne."""
    with get_cursor() as (cur, _conn):
        profile = persons_queries.person_profile(cur, person_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Person not found")
        return profile


@router.get("/api/persons/{person_id}/theses")
async def person_theses(person_id: int) -> Any:
    """Thèses liées à cette personne avec un rôle non-auteur."""
    with get_cursor() as (cur, _conn):
        return persons_queries.person_theses(cur, person_id)


@router.get("/api/persons/{person_id}/addresses")
async def person_addresses(
    person_id: int,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
) -> Any:
    """Adresses distinctes utilisées dans les authorships sources de cette personne."""
    with get_cursor() as (cur, _conn):
        return persons_queries.person_addresses(cur, person_id, page=page, per_page=per_page)


# ----- Identifier management -----

ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


@router.post("/api/persons/{person_id}/identifier")
async def add_person_identifier(person_id: int, data: AddIdentifier) -> Any:
    """Ajoute manuellement un identifiant (ORCID ou idHAL) à une personne."""
    if data.id_type not in ("orcid", "idhal", "idref"):
        raise HTTPException(status_code=400, detail="id_type doit être 'orcid', 'idhal' ou 'idref'")

    id_value = data.id_value.strip()

    # Nettoyage ORCID
    if data.id_type == "orcid":
        id_value = (
            id_value.replace("https://orcid.org/", "").replace("http://orcid.org/", "").strip()
        )
        if not ORCID_RE.match(id_value):
            raise HTTPException(
                status_code=400,
                detail=f"Format ORCID invalide : '{id_value}'. Attendu : 0000-0000-0000-000X",
            )

    if not id_value:
        raise HTTPException(status_code=400, detail="Valeur vide")

    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Personne introuvable")

        # Vérifier si déjà attribué
        cur.execute(
            "SELECT id, person_id, status::text FROM person_identifiers WHERE id_type = %s AND id_value = %s",
            (data.id_type, id_value),
        )
        existing = cur.fetchone()
        was_reassigned = False
        if existing:
            if existing["person_id"] == person_id:
                return {"added": False, "reason": "already_exists"}
            if existing["status"] != "rejected":
                raise HTTPException(
                    status_code=409,
                    detail=f"Cet identifiant est déjà attribué à la personne #{existing['person_id']}",
                )
            was_reassigned = True

        _add_identifier(cur, person_id, data.id_type, id_value, source="manual")
        result = {"added": True, "id_type": data.id_type, "id_value": id_value}
        if was_reassigned:
            result["reassigned"] = True
        return result


@router.delete("/api/persons/{person_id}/identifier/{id_type}/{id_value:path}")
async def remove_person_identifier(person_id: int, id_type: str, id_value: str) -> Any:
    """Supprime un identifiant d'une personne."""
    with get_cursor() as (cur, conn):
        _remove_identifier(cur, person_id, id_type, id_value)
        return {"removed": True}


@router.patch("/api/person-identifiers/{ident_id}/status")
async def update_identifier_status(ident_id: int, body: UpdateIdentifierStatus) -> Any:
    """Met à jour le statut d'un identifiant (pending/confirmed/rejected)."""
    with get_cursor() as (cur, conn):
        row = _update_identifier_status(cur, ident_id, body.status)
        return {"id": row["id"], "status": row["status"]}


@router.patch("/api/person-identifiers/{ident_id}/reassign")
async def reassign_identifier(ident_id: int, body: ReassignIdentifier) -> Any:
    """Réattribue un identifiant rejeté à une autre personne (status → pending)."""
    target_person_id = body.person_id
    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM persons WHERE id = %s", (target_person_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Personne cible introuvable")
        _reassign_identifier(cur, ident_id, target_person_id)
        return {"id": ident_id, "person_id": target_person_id, "status": "pending"}


@router.patch("/api/authorships/{authorship_id}/exclude")
async def toggle_authorship_excluded(authorship_id: int) -> Any:
    """Marque un authorship comme exclu (lien personne-publication rejeté)."""
    with get_cursor() as (cur, conn):
        row = _exclude_authorship(cur, authorship_id)
        return {"id": row["id"], "excluded": row["excluded"]}


@router.patch("/api/persons/{person_id}/reject")
async def reject_person(person_id: int, body: RejectPerson) -> Any:
    """Marque/démarque une personne comme rejetée (fausse entité)."""
    with get_cursor() as (cur, conn):
        _set_rejected(cur, person_id, body.rejected)
        return {"ok": True}


@router.patch("/api/persons/{person_id}/name")
async def update_person_name(person_id: int, body: UpdatePersonName) -> Any:
    """Modifie le nom/prénom d'une personne."""
    last_name = body.last_name.strip()
    first_name = body.first_name.strip()
    if not last_name:
        raise HTTPException(status_code=400, detail="Le nom est requis")
    with get_cursor() as (cur, conn):
        _update_name(cur, person_id, last_name, first_name)
        return {"ok": True}


@router.post("/api/persons/{person_id}/merge")
async def merge_persons(person_id: int, body: MergePersons) -> Any:
    """Fusionne une autre personne (source) dans celle-ci (target)."""
    source_id = body.source_id
    if source_id == person_id:
        raise HTTPException(status_code=400, detail="source_id invalide")

    with get_cursor() as (cur, conn):
        # Vérifier que les deux personnes existent
        cur.execute("SELECT id FROM persons WHERE id IN (%s, %s)", (person_id, source_id))
        found = {row["id"] for row in cur.fetchall()}
        if person_id not in found:
            raise HTTPException(status_code=404, detail="Personne cible introuvable")
        if source_id not in found:
            raise HTTPException(status_code=404, detail="Personne source introuvable")

        _merge_person(cur, person_id, source_id)
        return {"merged": True, "source_id": source_id, "target_id": person_id}


# ----- API: Authorships orphelines -----


# Filtre commun pour les orphan authorships :
# - in_perimeter, sans person_id, sources principales
# - exclut les authorships sur des memoires (etudiants de master)
# - exclut les authorships dont le source_author est rattache a une personne rejetee
_ORPHAN_BASE = f"""
    sa.person_id IS NULL AND sa.in_perimeter = TRUE
    AND sa.source IN {AUTHOR_SOURCES_SQL}
    AND p.doc_type NOT IN ('memoir', 'peer_review')
    AND NOT EXISTS (
        SELECT 1 FROM source_authorships sa2
        JOIN persons pe ON pe.id = sa2.person_id AND pe.rejected = TRUE
        WHERE sa2.source_person_id = sa.source_person_id
    )
"""


@router.get("/api/admin/orphan-authorships/count")
async def orphan_authorships_count() -> Any:
    """Nombre d'authorships UCA sans person_id."""
    with get_cursor() as (cur, conn):
        cur.execute(f"""
            SELECT COUNT(*) AS total
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN publications p ON p.id = sd.publication_id
            WHERE {_ORPHAN_BASE}
        """)
        return cur.fetchone()


@router.get("/api/admin/orphan-authorships")
async def list_orphan_authorships(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    search: str = Query(""),
) -> Any:
    """Liste les authorships UCA sans person_id, avec publication et nom d'auteur."""
    offset = (page - 1) * per_page
    search_cond = ""
    params: list = []
    if search.strip():
        params.append(f"%{search.strip()}%")
        search_cond = "AND unaccent(lower(sa.raw_author_name)) LIKE unaccent(lower(%s))"

    with get_cursor() as (cur, conn):
        # Count
        cur.execute(
            f"""
            SELECT COUNT(*) FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN publications p ON p.id = sd.publication_id
            WHERE {_ORPHAN_BASE}
              {search_cond}
        """,
            params,
        )
        total = cur.fetchone()["count"]

        # List
        cur.execute(
            f"""
            SELECT sa.source, sa.id AS authorship_id,
                   sa.raw_author_name AS full_name,
                   sd.publication_id,
                   p.title AS pub_title, p.pub_year
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN publications p ON p.id = sd.publication_id
            WHERE {_ORPHAN_BASE}
              {search_cond}
            ORDER BY sa.raw_author_name, p.pub_year DESC
            LIMIT %s OFFSET %s
        """,
            params + [per_page, offset],
        )
        rows = cur.fetchall()

        return {
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page or 1,
            "authorships": rows,
        }


# _add_name_form et _ensure_truth_authorship sont dans services.persons


@router.post("/api/admin/orphan-authorships/assign")
async def assign_orphan_authorship_endpoint(body: AssignOrphanAuthorship) -> Any:
    """Attribue une authorship orpheline à une personne existante ou nouvelle."""
    if body.source not in ALL_SOURCES_SET:
        raise HTTPException(status_code=400, detail=f"Source inconnue: {body.source}")

    person_id = body.person_id
    with get_cursor() as (cur, conn):
        if body.create_person:
            ln = body.create_person.last_name.strip()
            fn = body.create_person.first_name.strip()
            if not ln:
                raise HTTPException(status_code=400, detail="Nom requis")
            person_id = _create_person(cur, ln, fn)
        elif not person_id:
            raise HTTPException(status_code=400, detail="person_id ou create_person requis")

        # Vérifier que la personne existe
        cur.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Personne introuvable")

        _assign_orphan(cur, person_id, body.source, body.authorship_id)

        return {"ok": True, "person_id": person_id}


@router.post("/api/admin/orphan-authorships/batch-assign")
async def batch_assign_orphan_authorships(body: BatchAssignOrphanAuthorships) -> Any:
    """Attribue plusieurs authorships orphelines a une meme personne.

    Fait tout en SQL batch au lieu d'iterer authorship par authorship :
    1. SET person_id sur les source_authorships
    2. Cree les authorships canoniques manquantes
    3. Met les FK source_authorships.authorship_id
    4. Ajoute les formes de noms
    """
    person_id = body.person_id

    sa_ids = [a.authorship_id for a in body.authorships if a.source in ALL_SOURCES_SET]
    if not sa_ids:
        return {"ok": True, "assigned": 0}

    with get_cursor() as (cur, conn):
        cur.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Personne introuvable")

        assigned = _batch_assign_orphan(cur, person_id, sa_ids)
        return {"ok": True, "assigned": assigned}


# ----- API: Formes de noms / détachement authorships -----


@router.get("/api/persons/{person_id}/name-form-authorships")
async def name_form_authorships(person_id: int, name_form: str = Query(...)) -> Any:
    """Liste les authorships sources liées à une personne pour une forme de nom donnée.
    name_form est la forme normalisée (lowercase, unaccent) depuis person_name_forms.
    Retourne aussi les autres personnes partageant cette forme de nom."""
    with get_cursor() as (cur, conn):
        cur.execute(
            f"""
            SELECT sa.source, sa.id AS authorship_id,
                   sd.publication_id AS pub_id, sd.title, sd.pub_year, sd.doi
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            WHERE sa.person_id = %s AND sa.author_name_normalized = %s
              AND sa.source IN {AUTHOR_SOURCES_SQL}
            ORDER BY sd.pub_year DESC, sd.title
        """,
            (person_id, name_form),
        )
        authorships = cur.fetchall()

        # Autres personnes partageant cette forme de nom
        cur.execute(
            """
            SELECT p.id, p.first_name, p.last_name,
                   pr.department_name,
                   EXISTS(SELECT 1 FROM persons_rh rh WHERE rh.person_id = p.id) AS has_rh
            FROM person_name_forms pnf,
                 LATERAL unnest(pnf.person_ids) AS pid
            JOIN persons p ON p.id = pid
            LEFT JOIN persons_rh pr ON pr.person_id = p.id
            WHERE pnf.name_form = %s
              AND pid <> %s
              AND p.rejected = FALSE
            ORDER BY p.last_name, p.first_name
        """,
            (name_form, person_id),
        )
        other_persons = cur.fetchall()

        return {"authorships": authorships, "other_persons": other_persons}


@router.post("/api/persons/{person_id}/detach-authorships")
async def detach_authorships(person_id: int, body: DetachAuthorships) -> Any:
    """Détache des authorships sources d'une personne et nettoie les formes de noms."""
    with get_cursor() as (cur, conn):
        return _detach_authorships_service(
            cur,
            person_id,
            authorships=[
                {"source": a.source, "authorship_id": a.authorship_id} for a in body.authorships
            ],
            name_form=body.name_form,
        )


@router.post("/api/persons/{person_id}/detach-name-form")
async def detach_name_form(person_id: int, body: DetachNameForm) -> Any:
    """Détache une forme de nom d'une personne (quand aucune authorship n'y est liée)."""
    name_form = body.name_form

    with get_cursor() as (cur, conn):
        # Vérifier qu'il n'y a aucune authorship liée
        cur.execute(
            f"""
            SELECT COUNT(*) FROM source_authorships sa
            WHERE sa.person_id = %s AND sa.author_name_normalized = %s
              AND sa.source IN {AUTHOR_SOURCES_SQL}
        """,
            (person_id, name_form),
        )
        remaining = cur.fetchone()["count"]
        if remaining > 0:
            raise HTTPException(
                status_code=400, detail="Cette forme a encore des authorships liées"
            )

        _detach_name_form(cur, person_id, name_form)
        return {"detached": True}


# ----- API: Doublons personnes -----


def _person_name_tokens(ln_norm: str, fn_norm: str) -> set[str]:
    """Tokens du nom complet normalisé (last + first), tirets éclatés en espaces."""
    return set((ln_norm + " " + fn_norm).replace("-", " ").split()) - {""}


def _tokens_match(t1: set[str], t2: set[str]) -> bool:
    """Vérifie si les tokens matchent.

    Chaque token de l'ensemble le plus petit doit trouver un correspondant
    dans l'ensemble le plus grand : soit identique, soit initiale (1 lettre)
    correspondant au début d'un token de l'autre ensemble.
    """
    if not t1 or not t2:
        return False
    small, big = (t1, t2) if len(t1) <= len(t2) else (t2, t1)
    for s in small:
        if s in big:
            continue
        if len(s) == 1:
            # s est une initiale — cherche un token dans big commençant par s
            if any(b.startswith(s) for b in big):
                continue
        # Cherche si s correspond à l'expansion d'une initiale dans big
        if any(len(b) == 1 and s.startswith(b) for b in big):
            continue
        return False
    return True


_DUP_NOT_EXISTS = """
    WHERE NOT EXISTS (
        SELECT 1 FROM distinct_persons dp
        WHERE dp.person_id_a = LEAST(p1.id, p2.id) AND dp.person_id_b = GREATEST(p1.id, p2.id)
    )
    AND NOT (
        EXISTS (SELECT 1 FROM persons_rh WHERE person_id = p1.id)
        AND EXISTS (SELECT 1 FROM persons_rh WHERE person_id = p2.id)
    )
"""

# Requêtes de doublons personnes par priorité (exécutées séquentiellement)
PERSON_DUP_QUERIES = [
    # Priorité 1a : même nom, initiale vs prénom complet
    f"""SELECT p1.id AS id_a, p2.id AS id_b,
               p1.last_name_normalized AS ln1, p1.first_name_normalized AS fn1,
               p2.last_name_normalized AS ln2, p2.first_name_normalized AS fn2
        FROM persons p1
        JOIN persons p2 ON p1.id < p2.id
          AND p1.last_name_normalized = p2.last_name_normalized
          AND p1.last_name_normalized <> ''
          AND LEFT(p1.first_name_normalized, 1) = LEFT(p2.first_name_normalized, 1)
          AND (LENGTH(p1.first_name_normalized) = 1 OR LENGTH(p2.first_name_normalized) = 1)
          AND LENGTH(p1.first_name_normalized) >= 1
          AND LENGTH(p2.first_name_normalized) >= 1
        {_DUP_NOT_EXISTS}
        ORDER BY p1.id, p2.id""",
    # Priorité 1b : nom composé vs nom simple
    f"""SELECT p1.id AS id_a, p2.id AS id_b,
               p1.last_name_normalized AS ln1, p1.first_name_normalized AS fn1,
               p2.last_name_normalized AS ln2, p2.first_name_normalized AS fn2
        FROM persons p1
        JOIN persons p2 ON p1.id < p2.id
          AND REPLACE(p1.last_name_normalized, '-', ' ') <> REPLACE(p2.last_name_normalized, '-', ' ')
          AND p1.last_name_normalized <> ''
          AND p2.last_name_normalized <> ''
          AND (
              REPLACE(p2.last_name_normalized, '-', ' ') LIKE REPLACE(p1.last_name_normalized, '-', ' ') || ' %%'
              OR REPLACE(p1.last_name_normalized, '-', ' ') LIKE REPLACE(p2.last_name_normalized, '-', ' ') || ' %%'
          )
          AND LENGTH(p1.first_name_normalized) >= 1
          AND LENGTH(p2.first_name_normalized) >= 1
          AND LEFT(p1.first_name_normalized, 1) = LEFT(p2.first_name_normalized, 1)
          AND (
              p1.first_name_normalized = p2.first_name_normalized
              OR LENGTH(p1.first_name_normalized) = 1
              OR LENGTH(p2.first_name_normalized) = 1
              OR p1.first_name_normalized LIKE p2.first_name_normalized || ' %%'
              OR p2.first_name_normalized LIKE p1.first_name_normalized || ' %%'
          )
        {_DUP_NOT_EXISTS}
        ORDER BY p1.id, p2.id""",
    # Priorité 1c : inversion nom/prénom
    f"""SELECT p1.id AS id_a, p2.id AS id_b,
               p1.last_name_normalized AS ln1, p1.first_name_normalized AS fn1,
               p2.last_name_normalized AS ln2, p2.first_name_normalized AS fn2
        FROM persons p1
        JOIN persons p2 ON p1.id < p2.id
          AND p1.last_name_normalized = p2.first_name_normalized
          AND p1.first_name_normalized = p2.last_name_normalized
          AND p1.last_name_normalized <> ''
          AND p1.first_name_normalized <> ''
          AND p1.last_name_normalized <> p1.first_name_normalized
        {_DUP_NOT_EXISTS}
        ORDER BY p1.id, p2.id""",
    # Priorité 2 : même nom, prénoms compatibles (pas initiale)
    f"""SELECT p1.id AS id_a, p2.id AS id_b,
               p1.last_name_normalized AS ln1, p1.first_name_normalized AS fn1,
               p2.last_name_normalized AS ln2, p2.first_name_normalized AS fn2
        FROM persons p1
        JOIN persons p2 ON p1.id < p2.id
          AND p1.last_name_normalized = p2.last_name_normalized
          AND p1.last_name_normalized <> ''
          AND LENGTH(p1.first_name_normalized) > 1
          AND LENGTH(p2.first_name_normalized) > 1
          AND LEFT(p1.first_name_normalized, 1) = LEFT(p2.first_name_normalized, 1)
          AND (
              p1.first_name_normalized = p2.first_name_normalized
              OR p1.first_name_normalized LIKE p2.first_name_normalized || ' %%'
              OR p2.first_name_normalized LIKE p1.first_name_normalized || ' %%'
          )
        {_DUP_NOT_EXISTS}
        ORDER BY p1.id, p2.id""",
]


def _get_person_dedup_detail(cur: Any, person_id: Any) -> Any:
    """Détail d'une personne pour la page de déduplication."""
    cur.execute(
        """
        SELECT p.id, p.last_name, p.first_name,
               p.last_name_normalized, p.first_name_normalized,
               prh.role_title, prh.department_name,
               (prh.id IS NOT NULL) AS has_rh
        FROM persons p
        LEFT JOIN persons_rh prh ON prh.person_id = p.id
        WHERE p.id = %s
    """,
        (person_id,),
    )
    person = cur.fetchone()
    if not person:
        return None

    cur.execute(
        """
        SELECT id, id_type, id_value, source, status::text
        FROM person_identifiers WHERE person_id = %s
        ORDER BY id_type, id_value
    """,
        (person_id,),
    )
    identifiers = [dict(r) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT pub.id, pub.title, pub.pub_year, pub.doi, pub.doc_type::text,
               (SELECT array_agg(DISTINCT
                   CASE sd.source
                       WHEN 'hal' THEN 'HAL'
                       WHEN 'openalex' THEN 'OpenAlex'
                       WHEN 'wos' THEN 'WoS'
                       WHEN 'scanr' THEN 'ScanR'
                   END
                ) FROM source_publications sd WHERE sd.publication_id = pub.id
               ) AS sources
        FROM authorships a
        JOIN publications pub ON pub.id = a.publication_id
        WHERE a.person_id = %s AND NOT a.excluded
        ORDER BY pub.pub_year DESC NULLS LAST, pub.id DESC
    """,
        (person_id,),
    )
    publications = [dict(r) for r in cur.fetchall()]

    # Laboratoires associés (via authorships sources)
    cur.execute(
        """
        SELECT DISTINCT s.id, s.acronym, s.name
        FROM structures s
        WHERE s.structure_type = 'labo' AND s.id IN (
            SELECT UNNEST(sa.structure_ids)
            FROM source_authorships sa
            WHERE sa.person_id = %s AND sa.structure_ids IS NOT NULL
        )
        ORDER BY s.acronym NULLS LAST, s.name
    """,
        (person_id,),
    )
    labs = [{"id": r["id"], "acronym": r["acronym"], "name": r["name"]} for r in cur.fetchall()]

    return {
        "id": person["id"],
        "last_name": person["last_name"],
        "first_name": person["first_name"],
        "last_name_normalized": person["last_name_normalized"],
        "first_name_normalized": person["first_name_normalized"],
        "has_rh": person["has_rh"],
        "role_title": person["role_title"],
        "department_name": person["department_name"],
        "identifiers": identifiers,
        "publications": publications,
        "pub_count": len(publications),
        "labs": labs,
    }


def _parse_skip_pairs(skip: str) -> set[tuple[int, int]]:
    """Parse 'idA-idB,idA-idB,...' en set de tuples."""
    result: set[tuple[int, int]] = set()
    if skip:
        for s in skip.split(","):
            parts = s.strip().split("-")
            if len(parts) == 2:
                try:
                    result.add((int(parts[0]), int(parts[1])))
                except ValueError:
                    pass
    return result


def _scan_dup_query(
    cur: Any, sql: Any, skip_pairs: Any = None, stop_at_first: Any = False, skip_n: Any = 0
) -> Any:
    """Parcourt une requête de doublons avec curseur serveur.
    Retourne (found_row_or_None, count_of_valid_pairs).
    skip_n: nombre de paires valides à sauter avant de retourner la première.
    """
    cur.execute("DECLARE _dup_cur NO SCROLL CURSOR FOR " + sql)
    found = None
    count = 0
    skipped = 0
    while True:
        cur.execute("FETCH 500 FROM _dup_cur")
        rows = cur.fetchall()
        if not rows:
            break
        for row in rows:
            t1 = _person_name_tokens(row["ln1"], row["fn1"])
            t2 = _person_name_tokens(row["ln2"], row["fn2"])
            if not _tokens_match(t1, t2):
                continue
            count += 1
            if found is None:
                # Legacy skip pairs
                if skip_pairs is not None:
                    pair_key = (row["id_a"], row["id_b"])
                    if pair_key in skip_pairs:
                        continue
                # Offset-based skip
                if skipped < skip_n:
                    skipped += 1
                    continue
                found = row
                if stop_at_first:
                    break
        if stop_at_first and found:
            break
    cur.execute("CLOSE _dup_cur")
    return found, count, skipped


# ----- HAL problems: duplicate accounts -----


@router.get("/api/hal-problems/duplicate-accounts")
async def hal_duplicate_accounts(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> Any:
    """Personnes liées à 2+ comptes HAL distincts."""
    offset = (page - 1) * per_page
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT person_id
                FROM source_persons
                WHERE source = 'hal' AND person_id IS NOT NULL
                  AND (source_ids->>'hal_person_id') IS NOT NULL
                GROUP BY person_id
                HAVING COUNT(DISTINCT source_ids->>'hal_person_id') >= 2
            ) sub
        """)
        total = cur.fetchone()["count"]

        cur.execute(
            """
            SELECT p.id AS person_id, p.last_name, p.first_name,
                   (prh.id IS NOT NULL) AS has_rh,
                   (SELECT json_agg(json_build_object(
                       'hal_person_id', (sa.source_ids->>'hal_person_id')::int,
                       'full_name', sa.full_name,
                       'idhal', sa.source_ids->>'idhal',
                       'orcid', sa.orcid,
                       'pub_count', (SELECT COUNT(*) FROM source_authorships sa2
                                     WHERE sa2.source = 'hal' AND sa2.source_person_id = sa.id)
                   ) ORDER BY (sa.source_ids->>'hal_person_id')::int)
                    FROM source_persons sa
                    WHERE sa.source = 'hal' AND sa.person_id = p.id
                      AND (sa.source_ids->>'hal_person_id') IS NOT NULL
                   ) AS hal_accounts
            FROM persons p
            LEFT JOIN persons_rh prh ON prh.person_id = p.id
            WHERE p.id IN (
                SELECT person_id
                FROM source_persons
                WHERE source = 'hal' AND person_id IS NOT NULL
                  AND (source_ids->>'hal_person_id') IS NOT NULL
                GROUP BY person_id
                HAVING COUNT(DISTINCT source_ids->>'hal_person_id') >= 2
            )
            ORDER BY LOWER(p.last_name), LOWER(p.first_name)
            LIMIT %s OFFSET %s
        """,
            (per_page, offset),
        )
        persons = [dict(r) for r in cur.fetchall()]

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "persons": persons,
        }


# ----- HAL problems: duplicate publications -----


def _hal_pub_detail(cur: Any, pub_id: Any) -> Any:
    """Détail d'une publication pour la page doublons HAL."""
    cur.execute(
        """
        SELECT p.id, p.title, p.pub_year, p.doc_type::text, p.doi, p.container_title
        FROM publications p WHERE p.id = %s
    """,
        (pub_id,),
    )
    pub = cur.fetchone()
    if not pub:
        return None
    cur.execute(
        """
        SELECT sd.source_id AS halid, sd.hal_collections, sd.doc_type AS hal_doc_type, sd.pub_year AS hal_pub_year, sd.title AS hal_title,
               (SELECT COUNT(*) FROM source_authorships sa2 WHERE sa2.source = 'hal' AND sa2.source_publication_id = sd.id AND NOT sa2.excluded) AS author_count
        FROM source_publications sd WHERE sd.publication_id = %s AND sd.source = 'hal'
    """,
        (pub_id,),
    )
    hal_docs = [dict(r) for r in cur.fetchall()]
    return {**dict(pub), "hal_docs": hal_docs}


@router.get("/api/hal-problems/duplicate-pubs-doi")
async def hal_duplicate_pubs_by_doi(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> Any:
    """Dépôts HAL avec DOI identique rattachés à la même publication."""
    offset = (page - 1) * per_page
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT COUNT(*) FROM (
                SELECT sd.publication_id, LOWER(sd.doi)
                FROM source_publications sd
                WHERE sd.source = 'hal' AND sd.doi IS NOT NULL AND sd.doi != ''
                GROUP BY sd.publication_id, LOWER(sd.doi)
                HAVING COUNT(*) >= 2
            ) sub
        """)
        total = cur.fetchone()["count"]

        cur.execute(
            """
            SELECT LOWER(sd.doi) AS doi,
                   sd.publication_id AS pub_id,
                   array_agg(sd.source_id ORDER BY sd.source_id) AS halids
            FROM source_publications sd
            WHERE sd.source = 'hal' AND sd.doi IS NOT NULL AND sd.doi != ''
            GROUP BY sd.publication_id, LOWER(sd.doi)
            HAVING COUNT(*) >= 2
            ORDER BY LOWER(sd.doi)
            LIMIT %s OFFSET %s
        """,
            (per_page, offset),
        )
        rows = cur.fetchall()

        pairs = []
        for r in rows:
            pub = _hal_pub_detail(cur, r["pub_id"])
            if pub:
                pairs.append({"doi": r["doi"], "halids": r["halids"], "publication": pub})

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "pairs": pairs,
        }


@router.get("/api/hal-problems/duplicate-pubs-meta")
async def hal_duplicate_pubs_by_metadata(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> Any:
    """Doublons possibles: dépôts HAL avec métadonnées identiques."""
    offset = (page - 1) * per_page
    with get_cursor() as (cur, conn):
        dup_query = """
            FROM publications p1
            JOIN publications p2 ON p1.title_normalized = p2.title_normalized AND p1.id < p2.id
            JOIN source_publications hd1 ON hd1.publication_id = p1.id AND hd1.source = 'hal'
            JOIN source_publications hd2 ON hd2.publication_id = p2.id AND hd2.source = 'hal'
            WHERE LENGTH(p1.title_normalized) > 30
              AND p1.pub_year = p2.pub_year
              AND p1.doc_type = p2.doc_type
              AND NOT (p1.doi IS NOT NULL AND p2.doi IS NOT NULL AND LOWER(p1.doi) <> LOWER(p2.doi))
              AND ABS(
                  (SELECT COUNT(*) FROM source_authorships sa1 WHERE sa1.source = 'hal' AND sa1.source_publication_id = hd1.id AND NOT sa1.excluded)
                  - (SELECT COUNT(*) FROM source_authorships sa2 WHERE sa2.source = 'hal' AND sa2.source_publication_id = hd2.id AND NOT sa2.excluded)
              ) <= 2
              AND NOT EXISTS (SELECT 1 FROM distinct_publications dp
                              WHERE dp.pub_id_a = LEAST(p1.id, p2.id) AND dp.pub_id_b = GREATEST(p1.id, p2.id))
        """

        cur.execute(f"SELECT COUNT(*) {dup_query}")
        total = cur.fetchone()["count"]

        cur.execute(
            f"""
            SELECT p1.id AS id_a, p2.id AS id_b
            {dup_query}
            ORDER BY p1.id
            LIMIT %s OFFSET %s
        """,
            (per_page, offset),
        )
        rows = cur.fetchall()

        pairs = []
        for r in rows:
            pub_a = _hal_pub_detail(cur, r["id_a"])
            pub_b = _hal_pub_detail(cur, r["id_b"])
            if pub_a and pub_b:
                pairs.append({"pub_a": pub_a, "pub_b": pub_b})

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "pairs": pairs,
        }


# ----- HAL problems: missing collections -----


@router.get("/api/hal-problems/missing-collections")
async def hal_missing_collections(
    lab_id: int = Query(...),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> Any:
    """Publications affiliées à un labo sur OA/WoS, présentes dans HAL,
    mais absentes de la collection HAL du labo."""
    offset = (page - 1) * per_page
    with get_cursor() as (cur, conn):
        cur.execute("SELECT acronym, hal_collection FROM structures WHERE id = %s", (lab_id,))
        lab = cur.fetchone()
        if not lab or not lab["hal_collection"]:
            raise HTTPException(status_code=400, detail="Labo sans collection HAL")

        col = lab["hal_collection"]
        lab_arr = [lab_id]

        base_where = """
            FROM publications p
            JOIN authorships a ON a.publication_id = p.id AND a.structure_ids && %s::int[]
            WHERE EXISTS (SELECT 1 FROM source_publications sd WHERE sd.publication_id = p.id AND sd.source = 'hal')
              AND NOT EXISTS (SELECT 1 FROM source_publications sd
                              WHERE sd.publication_id = p.id AND sd.source = 'hal' AND %s = ANY(sd.hal_collections))
        """
        params = [lab_arr, col]

        cur.execute(f"SELECT COUNT(DISTINCT p.id) {base_where}", params)
        total = cur.fetchone()["count"]

        cur.execute(
            f"""
            SELECT DISTINCT p.id, p.title, p.pub_year, p.doc_type::text, p.doi,
                   (SELECT array_agg(sd2.source_id) FROM source_publications sd2 WHERE sd2.publication_id = p.id AND sd2.source = 'hal') AS halids,
                   NOT EXISTS (SELECT 1 FROM source_publications sd2
                               WHERE sd2.publication_id = p.id AND sd2.source = 'hal' AND 'PRES_CLERMONT' = ANY(sd2.hal_collections)) AS hors_uca
            {base_where}
            ORDER BY p.pub_year DESC NULLS LAST, p.id DESC
            LIMIT %s OFFSET %s
        """,
            params + [per_page, offset],
        )
        pubs = [dict(r) for r in cur.fetchall()]

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "lab_acronym": lab["acronym"],
            "hal_collection": col,
            "publications": pubs,
        }


@router.get("/api/hal-problems/missing-collections/labs")
async def hal_missing_collections_labs() -> Any:
    """Liste des labos avec collection HAL."""
    with get_cursor() as (cur, conn):
        cur.execute("""
            SELECT s.id, s.acronym, s.name, s.hal_collection
            FROM structures s
            WHERE s.hal_collection IS NOT NULL AND s.structure_type = 'labo'
            ORDER BY s.acronym
        """)
        return [dict(r) for r in cur.fetchall()]


# ----- HAL problems: affiliation conflicts -----

SHS_LAB_CODES = (
    "cmh",
    "clerma",
    "cerdi",
    "chec",
    "celis",
    "phier",
    "ihrim",
    "lapsco",
    "comsoc",
    "umr_territoires",
    "umr_ressources",
    "acte",
    "lrl",
    "lescores",
    "msh",
)


def _affiliation_pub_row(r: Any) -> Any:
    return {
        "id": r["id"],
        "title": r["title"],
        "pub_year": r["pub_year"],
        "doc_type": r["doc_type"],
        "doi": r["doi"],
        "halids": r["halids"],
        "labs": r["labs"],
    }


@router.get("/api/hal-problems/affiliation-conflicts")
async def hal_affiliation_conflicts(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> Any:
    """Publications affiliées UCA dans HAL mais pas dans OA/WoS."""
    offset = (page - 1) * per_page
    with get_cursor() as (cur, conn):
        cur.execute("SET LOCAL jit = off")
        base_where = """
            FROM authorships a
            JOIN publications p ON p.id = a.publication_id
            WHERE a.in_perimeter = TRUE
              AND EXISTS (SELECT 1 FROM source_authorships sa WHERE sa.authorship_id = a.id AND sa.source = 'hal')
              AND EXISTS (SELECT 1 FROM structures s WHERE s.id = ANY(a.structure_ids) AND s.structure_type = 'labo')
              AND (
                  -- Même position dans OA: adresse présente mais pas dans le périmètre
                  EXISTS (
                      SELECT 1 FROM source_authorships sa
                      JOIN source_publications sd ON sd.id = sa.source_publication_id
                      WHERE sd.publication_id = p.id
                        AND sa.source = 'openalex'
                        AND sa.author_position = a.author_position
                        AND sa.in_perimeter = FALSE
                        AND EXISTS (SELECT 1 FROM source_authorship_addresses saa WHERE saa.source_authorship_id = sa.id)
                  )
                  OR EXISTS (
                      SELECT 1 FROM source_authorships sa
                      JOIN source_publications sd ON sd.id = sa.source_publication_id
                      WHERE sd.publication_id = p.id
                        AND sa.source = 'wos'
                        AND sa.author_position = a.author_position
                        AND sa.in_perimeter = FALSE
                        AND EXISTS (SELECT 1 FROM source_authorship_addresses saa WHERE saa.source_authorship_id = sa.id)
                  )
              )
        """

        cur.execute(f"SELECT COUNT(DISTINCT p.id) {base_where}")
        total = cur.fetchone()["count"]

        cur.execute(
            f"""
            SELECT DISTINCT p.id, p.title, p.pub_year, p.doc_type::text, p.doi,
                   (SELECT array_agg(sd2.source_id) FROM source_publications sd2 WHERE sd2.publication_id = p.id AND sd2.source = 'hal') AS halids,
                   (SELECT string_agg(DISTINCT s.acronym, ', ' ORDER BY s.acronym)
                    FROM structures s WHERE s.id = ANY(a.structure_ids) AND s.structure_type = 'labo') AS labs
            {base_where}
            ORDER BY p.pub_year DESC NULLS LAST, p.id DESC
            LIMIT %s OFFSET %s
        """,
            (per_page, offset),
        )
        pubs = [_affiliation_pub_row(r) for r in cur.fetchall()]

        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page or 1,
            "publications": pubs,
        }
