"""
Service Référentiel Personnes — accès exclusif en écriture aux tables
`persons`, `person_identifiers`, `person_name_forms`.

Gère aussi le rattachement/détachement des authorships sources
(hal_authorships, openalex_authorships, wos_authorships) puisque
le person_id y est la source de vérité du lien personne.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.normalize import normalize_name


# ── Création ──

def create_person(cur, last_name: str, first_name: str = "") -> int:
    """Crée une personne et retourne son id."""
    cur.execute("""
        INSERT INTO persons (last_name, first_name,
                             last_name_normalized, first_name_normalized)
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """, (last_name, first_name,
          normalize_name(last_name), normalize_name(first_name)))
    return cur.fetchone()["id"]


# ── Rattachement / détachement authorships ──

def link_authorship(cur, person_id: int, source: str, authorship_id: int,
                    *, hal_author_id: int | None = None,
                    has_hal_person_id: bool = False):
    """Rattache une authorship source à une personne.

    Pour HAL, fait aussi le dual-write sur hal_authors si c'est un compte HAL.
    """
    if source == "hal":
        cur.execute("UPDATE hal_authorships SET person_id = %s WHERE id = %s",
                    (person_id, authorship_id))
        if hal_author_id and has_hal_person_id:
            cur.execute("""
                UPDATE hal_authors SET person_id = %s, updated_at = now()
                WHERE id = %s AND hal_person_id IS NOT NULL
            """, (person_id, hal_author_id))
    elif source == "openalex":
        cur.execute("UPDATE openalex_authorships SET person_id = %s WHERE id = %s",
                    (person_id, authorship_id))
    elif source == "wos":
        cur.execute("UPDATE wos_authorships SET person_id = %s WHERE id = %s",
                    (person_id, authorship_id))


def link_authorships(cur, person_id: int, authorships: list[dict]):
    """Rattache un groupe d'authorships à une personne.

    Chaque dict doit avoir 'source' et 'authorship_id',
    et optionnellement 'hal_author_id' et 'has_hal_person_id'.
    """
    for a in authorships:
        link_authorship(cur, person_id, a["source"], a["authorship_id"],
                        hal_author_id=a.get("hal_author_id"),
                        has_hal_person_id=a.get("has_hal_person_id", False))


def unlink_authorship(cur, person_id: int, source: str, authorship_id: int):
    """Détache une authorship source d'une personne (met person_id à NULL)."""
    if source == "hal":
        cur.execute(
            "UPDATE hal_authorships SET person_id = NULL WHERE id = %s AND person_id = %s",
            (authorship_id, person_id))
    elif source == "openalex":
        cur.execute(
            "UPDATE openalex_authorships SET person_id = NULL WHERE id = %s AND person_id = %s",
            (authorship_id, person_id))
    elif source == "wos":
        cur.execute(
            "UPDATE wos_authorships SET person_id = NULL WHERE id = %s AND person_id = %s",
            (authorship_id, person_id))


# ── Identifiants ──

def add_identifier(cur, person_id: int, id_type: str, id_value: str,
                   source: str = "auto", status: str = "pending"):
    """Ajoute un identifiant (ORCID, idHAL, IdRef...) à une personne.
    Ne fait rien si l'identifiant existe déjà (ON CONFLICT DO NOTHING).
    """
    cur.execute("""
        INSERT INTO person_identifiers (person_id, id_type, id_value, source, status)
        VALUES (%s, %s, %s, %s, %s::identifier_status)
        ON CONFLICT (id_type, id_value) DO NOTHING
    """, (person_id, id_type, id_value, source, status))


def add_identifiers_from_authorships(cur, person_id: int, authorships: list[dict]):
    """Ajoute les ORCID et idHAL trouvés dans un groupe d'authorships."""
    seen = set()
    for a in authorships:
        if a.get("orcid") and ("orcid", a["orcid"]) not in seen:
            add_identifier(cur, person_id, "orcid", a["orcid"])
            seen.add(("orcid", a["orcid"]))
        if a.get("idhal") and ("idhal", a["idhal"]) not in seen:
            add_identifier(cur, person_id, "idhal", a["idhal"])
            seen.add(("idhal", a["idhal"]))


# ── Formes de noms ──

def add_name_form(cur, person_id: int, full_name: str, source: str | None = None):
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
        cur.execute("""
            INSERT INTO person_name_forms (name_form, name_form_normalized, person_ids, sources)
            VALUES (%s, %s, ARRAY[%s], ARRAY[%s])
            ON CONFLICT (name_form_normalized) WHERE name_form_normalized IS NOT NULL DO UPDATE
            SET person_ids = (
                    SELECT array_agg(DISTINCT x)
                    FROM unnest(person_name_forms.person_ids || ARRAY[%s]) AS x
                ),
                sources = (
                    SELECT array_agg(DISTINCT x ORDER BY x)
                    FROM unnest(COALESCE(person_name_forms.sources, '{}') || ARRAY[%s]) AS x
                ),
                updated_at = now()
        """, (full_name.strip(), norm, person_id, source, person_id, source))
    else:
        cur.execute("""
            INSERT INTO person_name_forms (name_form, name_form_normalized, person_ids)
            VALUES (%s, %s, ARRAY[%s])
            ON CONFLICT (name_form_normalized) WHERE name_form_normalized IS NOT NULL DO UPDATE
            SET person_ids = (
                SELECT array_agg(DISTINCT x)
                FROM unnest(person_name_forms.person_ids || ARRAY[%s]) AS x
            )
        """, (full_name.strip(), norm, person_id, person_id))


# ── Rattachement / détachement par auteur source ──
# Ces fonctions opèrent par author_id (pas authorship_id) : elles rattachent
# ou détachent TOUTES les authorships d'un auteur source, propagent vers
# les authorships vérité, et gèrent les identifiants.

# Tables et FK par source
_SOURCE_CONFIG = {
    "hal": {
        "author_table": "hal_authors",
        "author_fk": "hal_author_id",
        "authorship_table": "hal_authorships",
        "truth_fk": "hal_authorship_id",
        "id_fields": ["idhal", "orcid"],
    },
    "openalex": {
        "author_table": "openalex_authors",
        "author_fk": "openalex_author_id",
        "authorship_table": "openalex_authorships",
        "truth_fk": "openalex_authorship_id",
        "id_fields": ["orcid"],
    },
    "wos": {
        "author_table": "wos_authors",
        "author_fk": "wos_author_id",
        "authorship_table": "wos_authorships",
        "truth_fk": "wos_authorship_id",
        "id_fields": ["orcid"],
    },
}


def link_author_to_person(cur, person_id: int, source: str, author_id: int):
    """Rattache un auteur source (et toutes ses authorships) à une personne.

    1. Met person_id sur toutes les authorships de cet auteur
    2. Dual-write sur hal_authors si c'est un compte HAL
    3. Propage vers les authorships vérité (person_id NULL uniquement)
    4. Propage les identifiants (ORCID, idHAL) vers person_identifiers

    Retourne les infos de l'auteur ou None si non trouvé.
    """
    cfg = _SOURCE_CONFIG.get(source)
    if not cfg:
        raise ValueError(f"Source inconnue : {source}")

    # Charger l'auteur source
    cur.execute(f"SELECT * FROM {cfg['author_table']} WHERE id = %s", (author_id,))
    author = cur.fetchone()
    if not author:
        return None

    # 1. Rattacher les authorships sources
    cur.execute(f"""
        UPDATE {cfg['authorship_table']} SET person_id = %s
        WHERE {cfg['author_fk']} = %s
    """, (person_id, author_id))

    # 2. Dual-write hal_authors pour les comptes HAL
    if source == "hal" and author.get("hal_person_id"):
        cur.execute("""
            UPDATE hal_authors SET person_id = %s, updated_at = now()
            WHERE id = %s
        """, (person_id, author_id))

    # 3. Propager vers authorships vérité (seulement celles sans person_id)
    cur.execute(f"""
        UPDATE authorships a SET person_id = %s, updated_at = now()
        WHERE a.{cfg['truth_fk']} IN (
            SELECT s.id FROM {cfg['authorship_table']} s
            WHERE s.{cfg['author_fk']} = %s
        )
        AND a.person_id IS NULL
    """, (person_id, author_id))

    # 4. Propager les identifiants
    for field in cfg["id_fields"]:
        value = author.get(field)
        if value:
            id_type = "idhal" if field == "idhal" else "orcid"
            add_identifier(cur, person_id, id_type, value, source=source)

    return author


def unlink_author_from_person(cur, person_id: int, source: str, author_id: int):
    """Détache un auteur source (et toutes ses authorships) d'une personne.

    1. Met person_id à NULL sur les authorships sources de cet auteur
    2. Détache hal_authors si c'est HAL
    3. Propage vers les authorships vérité
    """
    cfg = _SOURCE_CONFIG.get(source)
    if not cfg:
        raise ValueError(f"Source inconnue : {source}")

    # 1. Détacher les authorships sources
    cur.execute(f"""
        UPDATE {cfg['authorship_table']} SET person_id = NULL
        WHERE {cfg['author_fk']} = %s AND person_id = %s
    """, (author_id, person_id))

    # 2. Détacher hal_authors (comptes HAL)
    if source == "hal":
        cur.execute("""
            UPDATE hal_authors SET person_id = NULL, updated_at = now()
            WHERE id = %s AND person_id = %s
        """, (author_id, person_id))

    # 3. Propager vers authorships vérité
    cur.execute(f"""
        UPDATE authorships a SET person_id = NULL
        FROM {cfg['authorship_table']} s
        WHERE a.{cfg['truth_fk']} = s.id
          AND s.{cfg['author_fk']} = %s
          AND a.person_id = %s
    """, (author_id, person_id))


# ── Attribution d'authorships orphelines ──

def assign_orphan_authorship(cur, person_id: int, source: str, authorship_id: int):
    """Attribue une authorship orpheline (person_id IS NULL) à une personne.

    1. Met person_id sur l'authorship source (seulement si NULL)
    2. Récupère le nom de l'auteur
    3. Ajoute la forme de nom (si authorship non exclue)
    4. Crée/met à jour l'authorship vérité + FK source

    Retourne True si l'authorship a été attribuée, False sinon.
    """
    cfg = _SOURCE_CONFIG.get(source)
    if not cfg:
        raise ValueError(f"Source inconnue : {source}")

    # 1. Rattacher et récupérer le nom + statut excluded
    if source == "hal":
        cur.execute("""
            UPDATE hal_authorships SET person_id = %s WHERE id = %s AND person_id IS NULL
            RETURNING excluded,
                (SELECT ha.full_name FROM hal_authors ha WHERE ha.id = hal_author_id) AS full_name
        """, (person_id, authorship_id))
    elif source == "openalex":
        cur.execute("""
            UPDATE openalex_authorships SET person_id = %s WHERE id = %s AND person_id IS NULL
            RETURNING excluded, raw_author_name AS full_name
        """, (person_id, authorship_id))
    elif source == "wos":
        cur.execute("""
            UPDATE wos_authorships SET person_id = %s WHERE id = %s AND person_id IS NULL
            RETURNING excluded,
                (SELECT wa.full_name FROM wos_authors wa WHERE wa.id = wos_author_id) AS full_name
        """, (person_id, authorship_id))

    row = cur.fetchone()
    if not row:
        return False

    # 2. Ajouter la forme de nom (sauf si authorship exclue)
    if row["full_name"] and not row.get("excluded"):
        add_name_form(cur, person_id, row["full_name"])

    # 3. Créer/mettre à jour l'authorship vérité
    _ensure_truth_authorship(cur, person_id, source, authorship_id)

    return True


def _ensure_truth_authorship(cur, person_id: int, source: str, authorship_id: int):
    """Crée l'authorship vérité si elle n'existe pas, et met à jour la FK source."""
    cfg = _SOURCE_CONFIG[source]

    # Trouver la publication_id via la table de documents
    doc_table = {
        "hal": ("hal_authorships", "hal_documents", "hal_document_id"),
        "openalex": ("openalex_authorships", "openalex_documents", "openalex_document_id"),
        "wos": ("wos_authorships", "wos_documents", "wos_document_id"),
    }
    auth_tbl, doc_tbl, doc_fk = doc_table[source]
    cur.execute(f"""
        SELECT d.publication_id FROM {auth_tbl} a
        JOIN {doc_tbl} d ON d.id = a.{doc_fk}
        WHERE a.id = %s
    """, (authorship_id,))
    row = cur.fetchone()
    if not row or not row["publication_id"]:
        return
    pub_id = row["publication_id"]

    # INSERT si pas déjà existant
    cur.execute("""
        INSERT INTO authorships (publication_id, person_id)
        VALUES (%s, %s)
        ON CONFLICT (publication_id, person_id) DO NOTHING
    """, (pub_id, person_id))

    # Mettre à jour la FK source
    cur.execute(f"""
        UPDATE authorships SET {cfg['truth_fk']} = %s, updated_at = now()
        WHERE publication_id = %s AND person_id = %s AND {cfg['truth_fk']} IS NULL
    """, (authorship_id, pub_id, person_id))


# ── Fusion ──

def merge_person(cur, target_id: int, source_id: int):
    """Fusionne la personne source_id dans target_id.

    Transfère tous les auteurs liés, identifiants, authorships et person_name_forms
    de source vers target, puis supprime la personne source.

    Lève RuntimeError si les deux personnes ont chacune une fiche RH distincte.
    """
    # Garde-fou : ne JAMAIS fusionner si les deux ont une fiche RH
    cur.execute("""
        SELECT COUNT(*) AS n FROM persons_rh
        WHERE person_id IN (%s, %s)
    """, (target_id, source_id))
    if cur.fetchone()["n"] >= 2:
        raise RuntimeError(
            f"REFUS de fusion : les personnes #{target_id} et #{source_id} "
            f"ont chacune une fiche RH distincte."
        )

    # 1. Transférer les auteurs HAL (comptes avec hal_person_id)
    cur.execute("UPDATE hal_authors SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 1b. Transférer les hal_authorships
    cur.execute("UPDATE hal_authorships SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 2. Transférer les authorships OpenAlex
    cur.execute("UPDATE openalex_authorships SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 3. Transférer les authorships WoS
    cur.execute("UPDATE wos_authorships SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 4. Transférer les authorships consolidées (supprimer les doublons publication)
    cur.execute("""
        DELETE FROM authorships
        WHERE person_id = %s
          AND publication_id IN (
              SELECT publication_id FROM authorships WHERE person_id = %s
          )
    """, (source_id, target_id))
    cur.execute("UPDATE authorships SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 5. Transférer les identifiants (supprimer doublons)
    cur.execute("""
        DELETE FROM person_identifiers
        WHERE person_id = %s
          AND (id_type, id_value) IN (
              SELECT id_type, id_value FROM person_identifiers WHERE person_id = %s
          )
    """, (source_id, target_id))
    cur.execute("UPDATE person_identifiers SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 6. Transférer persons_rh de la source vers la cible (si la cible n'en a pas)
    cur.execute("""
        UPDATE persons_rh SET person_id = %s
        WHERE person_id = %s
          AND NOT EXISTS (SELECT 1 FROM persons_rh WHERE person_id = %s)
    """, (target_id, source_id, target_id))

    # 7. Mettre à jour person_name_forms : remplacer source_id par target_id
    cur.execute("""
        UPDATE person_name_forms
        SET person_ids = (
                SELECT array_agg(DISTINCT v ORDER BY v)
                FROM unnest(array_replace(person_ids, %s, %s)) AS v
            ),
            updated_at = now()
        WHERE %s = ANY(person_ids)
    """, (source_id, target_id, source_id))

    # 8. Supprimer la personne source
    cur.execute("DELETE FROM persons WHERE id = %s", (source_id,))
