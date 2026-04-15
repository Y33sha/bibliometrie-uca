"""
Service Référentiel Personnes — accès exclusif en écriture aux tables
`persons`, `person_identifiers`, `person_name_forms`.

Gère aussi le rattachement/détachement des authorships sources
(source_authorships) puisque le person_id y est la source de vérité
du lien personne.

Les auteurs sources sont dans la table unifiée `source_authors`
(UNIQUE(source, source_id)), les authorships utilisent `source_author_id`.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.normalize import normalize_name
from utils.sources import ALL_SOURCES_SET, AUTHOR_SOURCES_SQL
from utils.perimeter import get_persons_structure_ids_list


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
    person_id = cur.fetchone()["id"]
    refresh_person_name_forms(cur, person_id, last_name, first_name)
    return person_id


# ── Rattachement / détachement authorships ──

def link_authorship(cur, person_id: int, source: str, authorship_id: int,
                    *, source_author_id: int | None = None,
                    has_hal_person_id: bool = False):
    """Rattache une authorship source à une personne.

    Pour HAL, fait aussi le dual-write sur source_authors si c'est un compte HAL.
    """
    if source not in ALL_SOURCES_SET:
        return

    cur.execute("UPDATE source_authorships SET person_id = %s WHERE id = %s AND source = %s",
                (person_id, authorship_id, source))

    # Dual-write sur source_authors pour les comptes HAL
    if source == "hal" and source_author_id and has_hal_person_id:
        cur.execute("""
            UPDATE source_authors SET person_id = %s            WHERE id = %s AND (source_ids->>'hal_person_id') IS NOT NULL
        """, (person_id, source_author_id))


def link_authorships(cur, person_id: int, authorships: list[dict]):
    """Rattache un groupe d'authorships à une personne.

    Chaque dict doit avoir 'source' et 'authorship_id',
    et optionnellement 'source_author_id' et 'has_hal_person_id'.
    """
    for a in authorships:
        link_authorship(cur, person_id, a["source"], a["authorship_id"],
                        source_author_id=a.get("source_author_id"),
                        has_hal_person_id=a.get("has_hal_person_id", False))


def unlink_authorship(cur, person_id: int, source: str, authorship_id: int):
    """Détache une authorship source d'une personne (met person_id à NULL)."""
    if source in ALL_SOURCES_SET:
        cur.execute(
            "UPDATE source_authorships SET person_id = NULL WHERE id = %s AND person_id = %s AND source = %s",
            (authorship_id, person_id, source))


# ── Identifiants ──

def add_identifier(cur, person_id: int, id_type: str, id_value: str,
                   source: str = "auto", status: str = "pending"):
    """Ajoute un identifiant (ORCID, idHAL, IdRef...) à une personne.

    Si l'identifiant existe avec statut 'rejected', le réattribue
    (nouveau person_id, statut pending).
    Si 'pending' ou 'confirmed', ne fait rien.
    """
    cur.execute("""
        INSERT INTO person_identifiers (person_id, id_type, id_value, source, status)
        VALUES (%s, %s, %s, %s, %s::identifier_status)
        ON CONFLICT (id_type, id_value) DO UPDATE SET
            person_id = EXCLUDED.person_id,
            source = EXCLUDED.source,
            status = 'pending'
        WHERE person_identifiers.status = 'rejected'
    """, (person_id, id_type, id_value, source, status))


def add_identifiers_from_authorships(cur, person_id: int, authorships: list[dict]):
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


def refresh_person_name_forms(cur, person_id: int, last_name: str, first_name: str):
    """Recalcule les formes de nom source 'persons' d'une personne.

    Supprime les anciennes formes 'persons' de cette personne, puis insère
    les nouvelles. Les formes partagées avec d'autres personnes ou d'autres
    sources sont préservées (seul le person_id et la source sont retirés/ajoutés).
    """
    # 1a. Formes dont 'persons' est la seule source : retirer le person_id
    cur.execute("""
        UPDATE person_name_forms
        SET person_ids = array_remove(person_ids, %s)
        WHERE %s = ANY(person_ids)
          AND sources = ARRAY['persons']
    """, (person_id, person_id))
    # 1b. Formes multi-sources : retirer 'persons' de sources, garder person_id
    cur.execute("""
        UPDATE person_name_forms
        SET sources = array_remove(sources, 'persons'),
            updated_at = now()
        WHERE %s = ANY(person_ids)
          AND 'persons' = ANY(sources)
          AND array_length(sources, 1) > 1
    """, (person_id,))
    # 1c. Nettoyer les formes devenues vides
    cur.execute("""
        DELETE FROM person_name_forms
        WHERE person_ids = '{}' OR person_ids IS NULL
    """)

    # 2. Ajouter les nouvelles formes
    for form in compute_person_name_forms(last_name, first_name):
        add_name_form(cur, person_id, form, source="persons")


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
        """, (norm, person_id, source, person_id, source))
    else:
        cur.execute("""
            INSERT INTO person_name_forms (name_form, person_ids)
            VALUES (%s, ARRAY[%s])
            ON CONFLICT (name_form) DO UPDATE
            SET person_ids = (
                SELECT array_agg(DISTINCT x)
                FROM unnest(person_name_forms.person_ids || ARRAY[%s]) AS x
            )
        """, (norm, person_id, person_id))


def detach_name_form(cur, person_id: int, name_form: str):
    """Détache une personne d'une forme de nom.

    Retire person_id de person_ids. Supprime la forme si person_ids devient vide.
    Retourne True si le détachement a eu lieu.
    """
    cur.execute("""
        UPDATE person_name_forms
        SET person_ids = array_remove(person_ids, %s)
        WHERE name_form = %s
    """, (person_id, name_form))
    cur.execute("""
        DELETE FROM person_name_forms
        WHERE name_form = %s AND person_ids = '{}'
    """, (name_form,))
    return True


# ── Rattachement / détachement par auteur source ──
# Ces fonctions opèrent par author_id (pas authorship_id) : elles rattachent
# ou détachent TOUTES les authorships d'un auteur source, propagent vers
# les authorships vérité, et gèrent les identifiants.

# Config par source
_SOURCE_CONFIG = {
    "hal": {
        "author_fk": "source_author_id",
        "id_fields": ["orcid"],
        "source_ids_fields": {"idhal": "idhal"},
    },
    "openalex": {
        "author_fk": "source_author_id",
        "id_fields": ["orcid"],
        "source_ids_fields": {},
    },
    "wos": {
        "author_fk": "source_author_id",
        "id_fields": ["orcid"],
        "source_ids_fields": {},
    },
    "scanr": {
        "author_fk": "source_author_id",
        "id_fields": ["orcid", "idref"],
        "source_ids_fields": {},
    },
    "theses": {
        "author_fk": "source_author_id",
        "id_fields": ["orcid", "idref"],
        "source_ids_fields": {},
    },
}


def link_author_to_person(cur, person_id: int, source: str, author_id: int):
    """Rattache un auteur source (et toutes ses authorships) à une personne.

    1. Met person_id sur toutes les authorships de cet auteur
    2. Dual-write sur source_authors si c'est un compte HAL
    3. Propage vers les authorships vérité (person_id NULL uniquement)
    4. Propage les identifiants (ORCID, idHAL) vers person_identifiers

    Retourne les infos de l'auteur ou None si non trouvé.
    """
    cfg = _SOURCE_CONFIG.get(source)
    if not cfg:
        raise ValueError(f"Source inconnue : {source}")

    # Charger l'auteur source
    cur.execute("SELECT * FROM source_authors WHERE id = %s AND source = %s",
                (author_id, source))
    author = cur.fetchone()
    if not author:
        return None

    # 1. Rattacher les authorships sources
    cur.execute("""
        UPDATE source_authorships SET person_id = %s
        WHERE source = %s AND source_author_id = %s
    """, (person_id, source, author_id))

    # 2. Dual-write source_authors pour les comptes HAL
    if source == "hal" and author.get("source_ids", {}).get("hal_person_id"):
        cur.execute("""
            UPDATE source_authors SET person_id = %s            WHERE id = %s
        """, (person_id, author_id))

    # 3. Propager vers authorships vérité (seulement celles sans person_id)
    cur.execute("""
        UPDATE authorships a SET person_id = %s
        FROM source_authorships sa
        WHERE sa.authorship_id = a.id
          AND sa.source = %s AND sa.source_author_id = %s
          AND a.person_id IS NULL
    """, (person_id, source, author_id))

    # 4. Propager les identifiants
    for field in cfg["id_fields"]:
        value = author.get(field)
        if value:
            add_identifier(cur, person_id, "orcid", value, source=source)

    # 4b. Propager les identifiants depuis source_ids (ex: idhal)
    source_ids = author.get("source_ids") or {}
    for json_key, id_type in cfg.get("source_ids_fields", {}).items():
        value = source_ids.get(json_key)
        if value:
            add_identifier(cur, person_id, id_type, str(value), source=source)

    return author


def unlink_author_from_person(cur, person_id: int, source: str, author_id: int):
    """Détache un auteur source (et toutes ses authorships) d'une personne.

    1. Met person_id à NULL sur les authorships sources de cet auteur
    2. Détache source_authors si c'est HAL
    3. Propage vers les authorships vérité
    """
    cfg = _SOURCE_CONFIG.get(source)
    if not cfg:
        raise ValueError(f"Source inconnue : {source}")

    # 1. Détacher les authorships sources
    cur.execute("""
        UPDATE source_authorships SET person_id = NULL
        WHERE source = %s AND source_author_id = %s AND person_id = %s
    """, (source, author_id, person_id))

    # 2. Détacher source_authors (comptes HAL)
    if source == "hal":
        cur.execute("""
            UPDATE source_authors SET person_id = NULL            WHERE id = %s AND person_id = %s
        """, (author_id, person_id))

    # 3. Propager vers authorships vérité
    cur.execute("""
        UPDATE authorships a SET person_id = NULL
        FROM source_authorships sa
        WHERE sa.authorship_id = a.id
          AND sa.source = %s AND sa.source_author_id = %s
          AND a.person_id = %s
    """, (source, author_id, person_id))


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

    # 1. Rattacher et récupérer le nom normalisé + statut excluded
    cur.execute("""
        UPDATE source_authorships SET person_id = %s WHERE id = %s AND source = %s AND person_id IS NULL
        RETURNING excluded, author_name_normalized
    """, (person_id, authorship_id, source))

    row = cur.fetchone()
    if not row:
        return False

    # 2. Ajouter la forme de nom (sauf si authorship exclue)
    if row["author_name_normalized"] and not row.get("excluded"):
        add_name_form(cur, person_id, row["author_name_normalized"], source=source)

    # 3. Créer/mettre à jour l'authorship vérité
    _ensure_truth_authorship(cur, person_id, source, authorship_id)

    return True


def _ensure_truth_authorship(cur, person_id: int, source: str, authorship_id: int):
    """Crée/synchronise l'authorship vérité à partir des authorships sources.

    Même logique que build_authorships.py mais pour une seule paire
    (publication_id, person_id) : FK, author_position, is_corresponding,
    in_perimeter, structure_ids.
    """
    cfg = _SOURCE_CONFIG[source]

    # Trouver la publication_id via source_documents
    cur.execute("""
        SELECT d.publication_id FROM source_authorships sa
        JOIN source_documents d ON d.id = sa.source_document_id
        WHERE sa.id = %s AND sa.source = %s
    """, (authorship_id, source))
    row = cur.fetchone()
    if not row or not row["publication_id"]:
        return
    pub_id = row["publication_id"]

    # 1. INSERT si pas déjà existant
    cur.execute("""
        INSERT INTO authorships (publication_id, person_id)
        VALUES (%s, %s)
        ON CONFLICT (publication_id, person_id) DO NOTHING
    """, (pub_id, person_id))

    # 2. FK sources (source_authorships.authorship_id → authorships.id)
    cur.execute("""
        UPDATE source_authorships sa
        SET authorship_id = a.id
        FROM source_documents sd, authorships a
        WHERE sd.id = sa.source_document_id
          AND a.publication_id = sd.publication_id
          AND a.person_id = sa.person_id
          AND sd.publication_id = %s
          AND sa.person_id = %s
          AND NOT sa.excluded
          AND sa.authorship_id IS NULL
    """, (pub_id, person_id))

    # 3. author_position et is_corresponding
    cur.execute("""
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
    """, (pub_id, person_id))

    # 4. in_perimeter et structure_ids (union des sources)
    perimeter_ids = get_persons_structure_ids_list(cur)
    cur.execute(f"""
        WITH src AS (
            SELECT sa.in_perimeter AS uca, sa.structure_ids AS sids
            FROM source_authorships sa
            JOIN source_documents sd ON sd.id = sa.source_document_id
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
    """, (pub_id, person_id, pub_id, person_id))


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

    # 1. Transférer les auteurs sources (comptes HAL/ScanR avec person_id)
    cur.execute("UPDATE source_authors SET person_id = %s WHERE person_id = %s",
                (target_id, source_id))

    # 1b. Transférer les source_authorships
    cur.execute("UPDATE source_authorships SET person_id = %s WHERE person_id = %s",
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
    #    (pour les formes non-persons : hal, openalex, wos, manual)
    cur.execute("""
        UPDATE person_name_forms
        SET person_ids = (
                SELECT array_agg(DISTINCT v ORDER BY v)
                FROM unnest(array_replace(person_ids, %s, %s)) AS v
            ),
            updated_at = now()
        WHERE %s = ANY(person_ids)
    """, (source_id, target_id, source_id))

    # 7b. Recalculer les formes source 'persons' du target
    cur.execute("SELECT last_name, first_name FROM persons WHERE id = %s", (target_id,))
    target = cur.fetchone()
    refresh_person_name_forms(cur, target_id, target["last_name"],
                              target["first_name"] or "")

    # 8. Supprimer la personne source
    cur.execute("DELETE FROM persons WHERE id = %s", (source_id,))
