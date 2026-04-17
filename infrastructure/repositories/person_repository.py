"""Adapter PostgreSQL pour la persistance des personnes.

Couche infrastructure de l'architecture hexagonale : isole le code métier
(services/persons.py) de la base de données. Le service compose des
appels au repository, n'écrit plus de SQL directement.

Cette classe encapsule les opérations d'accès à la table `persons` et
ses tables satellites (person_identifiers, person_name_forms,
distinct_persons, source_persons). Elle peut lever des exceptions du
domaine (domain.errors.NotFoundError notamment) — c'est autorisé car
infrastructure dépend de domain, jamais l'inverse.

Un futur `domain/ports/person_repository.py` (Protocol abstrait) pourra
être introduit quand on voudra mocker ce repo dans des tests unitaires
sans base. Pour l'instant on reste pragmatique : classe concrète seule.

Usage :
    with get_cursor() as (cur, conn):
        repo = PgPersonRepository(cur)
        repo.set_rejected(person_id, True)
"""

from domain.errors import NotFoundError
from domain.person import compute_person_name_forms
from utils.normalize import normalize_name


class PgPersonRepository:
    """Accès PostgreSQL à l'agrégat Person."""

    def __init__(self, cur):
        """cur : curseur psycopg2 dans la transaction courante (fournie
        par le service appelant, qui gère le cycle de vie de la connexion)."""
        self._cur = cur

    # ── persons ────────────────────────────────────────────────────

    def create(self, last_name: str, first_name: str = "") -> int:
        """Insère une personne et retourne son id.

        Ne crée PAS les formes de nom dérivées — c'est le service qui
        les compose (logique métier) et appelle `refresh_name_forms()`.
        """
        self._cur.execute(
            """
            INSERT INTO persons (last_name, first_name,
                                 last_name_normalized, first_name_normalized)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (last_name, first_name, normalize_name(last_name), normalize_name(first_name)),
        )
        return self._cur.fetchone()["id"]

    def update_name(self, person_id: int, last_name: str, first_name: str) -> None:
        """Met à jour nom/prénom. Lève NotFoundError si la personne n'existe pas."""
        self._cur.execute("SELECT id FROM persons WHERE id = %s", (person_id,))
        if not self._cur.fetchone():
            raise NotFoundError(f"Personne {person_id} introuvable")

        self._cur.execute(
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

    def set_rejected(self, person_id: int, rejected: bool) -> None:
        """Marque ou démarque une personne comme rejetée (fausse entité).

        Lève NotFoundError si la personne n'existe pas.
        """
        self._cur.execute(
            "UPDATE persons SET rejected = %s, updated_at = now() WHERE id = %s",
            (rejected, person_id),
        )
        if self._cur.rowcount == 0:
            raise NotFoundError(f"Personne {person_id} introuvable")

    # ── Fusion ─────────────────────────────────────────────────────

    def has_distinct_rh(self, id_a: int, id_b: int) -> bool:
        """Vrai si chacune des deux personnes possède une fiche RH distincte
        (donc fusion interdite : invariant métier)."""
        self._cur.execute(
            "SELECT COUNT(*) AS n FROM persons_rh WHERE person_id IN (%s, %s)",
            (id_a, id_b),
        )
        return self._cur.fetchone()["n"] >= 2

    def merge_into(self, target_id: int, source_id: int) -> None:
        """Fusionne la personne `source_id` dans `target_id`.

        Toute la séquence de transferts est ici (une seule transaction) :
        1. Transfert des auteurs sources et source_authorships
        2. Dédoublonnage puis transfert des authorships vérité
        3. Dédoublonnage puis transfert des identifiants
        4. Transfert conditionnel de la fiche RH
        5. Mise à jour des person_name_forms (remplacement source_id → target_id)
        6. Recalcul des formes source 'persons' pour la cible
        7. Suppression de la personne source

        L'invariant métier (pas de fusion si les deux ont une fiche RH)
        doit être vérifié AVANT par le service via `has_distinct_rh`.
        """
        # 1. Transférer les auteurs sources (comptes HAL/ScanR avec person_id)
        self._cur.execute(
            "UPDATE source_persons SET person_id = %s WHERE person_id = %s",
            (target_id, source_id),
        )
        # 1b. Transférer les source_authorships
        self._cur.execute(
            "UPDATE source_authorships SET person_id = %s WHERE person_id = %s",
            (target_id, source_id),
        )

        # 2. Transférer les authorships consolidées (supprimer doublons publication)
        self._cur.execute(
            """
            DELETE FROM authorships
            WHERE person_id = %s
              AND publication_id IN (
                  SELECT publication_id FROM authorships WHERE person_id = %s
              )
            """,
            (source_id, target_id),
        )
        self._cur.execute(
            "UPDATE authorships SET person_id = %s WHERE person_id = %s",
            (target_id, source_id),
        )

        # 3. Transférer les identifiants (supprimer doublons)
        self._cur.execute(
            """
            DELETE FROM person_identifiers
            WHERE person_id = %s
              AND (id_type, id_value) IN (
                  SELECT id_type, id_value FROM person_identifiers WHERE person_id = %s
              )
            """,
            (source_id, target_id),
        )
        self._cur.execute(
            "UPDATE person_identifiers SET person_id = %s WHERE person_id = %s",
            (target_id, source_id),
        )

        # 4. Transférer la fiche RH source vers la cible (si la cible n'en a pas)
        self._cur.execute(
            """
            UPDATE persons_rh SET person_id = %s
            WHERE person_id = %s
              AND NOT EXISTS (SELECT 1 FROM persons_rh WHERE person_id = %s)
            """,
            (target_id, source_id, target_id),
        )

        # 5. person_name_forms : remplacer source_id par target_id partout
        self._cur.execute(
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

        # 6. Recalculer les formes source 'persons' du target à partir de son nom
        self._cur.execute(
            "SELECT last_name, first_name FROM persons WHERE id = %s",
            (target_id,),
        )
        target = self._cur.fetchone()
        forms = compute_person_name_forms(target["last_name"], target["first_name"] or "")
        self.refresh_name_forms(target_id, forms)

        # 7. Supprimer la personne source
        self._cur.execute("DELETE FROM persons WHERE id = %s", (source_id,))

    # ── distinct_persons ───────────────────────────────────────────

    def mark_distinct(self, person_id_a: int, person_id_b: int) -> tuple[int, int] | None:
        """Marque deux personnes comme distinctes dans `distinct_persons`.
        Idempotent (ON CONFLICT DO NOTHING).

        Les IDs sont triés (LEAST/GREATEST) pour garantir l'unicité de la paire.
        Retourne (a, b) si la paire vient d'être insérée, None si elle
        existait déjà — le caller peut décider d'émettre un audit ou non.
        """
        self._cur.execute(
            """
            INSERT INTO distinct_persons (person_id_a, person_id_b)
            VALUES (LEAST(%s, %s), GREATEST(%s, %s))
            ON CONFLICT DO NOTHING
            RETURNING person_id_a, person_id_b
            """,
            (person_id_a, person_id_b, person_id_a, person_id_b),
        )
        row = self._cur.fetchone()
        if not row:
            return None
        return row["person_id_a"], row["person_id_b"]

    # ── person_identifiers ─────────────────────────────────────────

    def add_identifier(
        self,
        person_id: int,
        id_type: str,
        id_value: str,
        source: str = "auto",
        status: str = "pending",
    ) -> None:
        """Ajoute un identifiant (ORCID, idHAL, IdRef...) à une personne.

        Si l'identifiant existe avec statut 'rejected', le réattribue
        (nouveau person_id, statut pending). Si 'pending' ou 'confirmed',
        ne fait rien.

        Pour les idHAL, rattache aussi le compte HAL correspondant dans
        `source_persons` (side-effect cross-table attendu par le pipeline).
        """
        self._cur.execute(
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

        if id_type == "idhal":
            self._cur.execute(
                """
                UPDATE source_persons SET person_id = %s
                WHERE source = 'hal'
                  AND source_ids->>'idhal' = %s
                  AND (person_id IS NULL OR person_id != %s)
                """,
                (person_id, id_value, person_id),
            )

    def remove_identifier(self, person_id: int, id_type: str, id_value: str) -> None:
        """Supprime un identifiant. Lève NotFoundError s'il n'existe pas."""
        self._cur.execute(
            """
            DELETE FROM person_identifiers
            WHERE person_id = %s AND id_type = %s AND id_value = %s
            """,
            (person_id, id_type, id_value),
        )
        if self._cur.rowcount == 0:
            raise NotFoundError("Identifiant introuvable")

    def update_identifier_status(self, ident_id: int, status: str) -> dict:
        """Change le statut d'un identifiant.

        Retourne {id, status, person_id}. Lève NotFoundError si l'identifiant
        n'existe pas. Le service utilisera person_id pour l'audit.
        """
        self._cur.execute(
            """
            UPDATE person_identifiers SET status = %s::identifier_status
            WHERE id = %s RETURNING id, status::text AS status, person_id
            """,
            (status, ident_id),
        )
        row = self._cur.fetchone()
        if not row:
            raise NotFoundError(f"Identifiant {ident_id} introuvable")
        return row

    def reassign_identifier(self, ident_id: int, target_person_id: int) -> None:
        """Réattribue un identifiant à une autre personne (statut → pending).

        Lève NotFoundError si l'identifiant n'existe pas.
        """
        self._cur.execute(
            """
            UPDATE person_identifiers
            SET person_id = %s, status = 'pending'::identifier_status
            WHERE id = %s
            """,
            (target_person_id, ident_id),
        )
        if self._cur.rowcount == 0:
            raise NotFoundError(f"Identifiant {ident_id} introuvable")

    # ── source_authorships (liens personnes ↔ authorships sources) ─

    def link_authorship(
        self,
        person_id: int,
        source: str,
        authorship_id: int,
        *,
        source_person_id: int | None = None,
        has_hal_person_id: bool = False,
    ) -> None:
        """Rattache une authorship source à une personne.

        Pour HAL avec un compte HAL, propage aussi le person_id vers
        source_persons (dual-write attendu par l'étape 0 du pipeline).
        """
        self._cur.execute(
            "UPDATE source_authorships SET person_id = %s WHERE id = %s AND source = %s",
            (person_id, authorship_id, source),
        )
        if source == "hal" and source_person_id and has_hal_person_id:
            self._cur.execute(
                """
                UPDATE source_persons SET person_id = %s
                WHERE id = %s AND (source_ids->>'hal_person_id') IS NOT NULL
                """,
                (person_id, source_person_id),
            )

    def unlink_authorship(self, person_id: int, source: str, authorship_id: int) -> None:
        """Détache une authorship source d'une personne (person_id → NULL)."""
        self._cur.execute(
            """
            UPDATE source_authorships SET person_id = NULL
            WHERE id = %s AND person_id = %s AND source = %s
            """,
            (authorship_id, person_id, source),
        )

    def assign_orphan_sa(
        self, person_id: int, source: str, authorship_id: int,
    ) -> dict | None:
        """Tente de poser person_id sur une source_authorship orpheline.

        Retourne un dict {excluded, author_name_normalized} si l'UPDATE a
        touché une ligne (orphan effectivement attribuée), None si déjà
        attribuée à une autre personne. Le service enchaîne avec add_name_form
        et ensure_truth_authorship après cette étape.
        """
        self._cur.execute(
            """
            UPDATE source_authorships SET person_id = %s
            WHERE id = %s AND source = %s AND person_id IS NULL
            RETURNING excluded, author_name_normalized
            """,
            (person_id, authorship_id, source),
        )
        return self._cur.fetchone()

    def batch_assign_orphans(self, person_id: int, sa_ids: list[int]) -> int:
        """Rattache en batch un lot de source_authorships orphelines, crée les
        authorships vérité manquantes, pose les FK et ajoute les formes de noms.

        Retourne le nombre de source_authorships réellement rattachées.
        """
        if not sa_ids:
            return 0

        # 1. Rattacher les source_authorships orphelines
        self._cur.execute(
            """
            UPDATE source_authorships SET person_id = %s
            WHERE id = ANY(%s) AND person_id IS NULL
            RETURNING id
            """,
            (person_id, sa_ids),
        )
        assigned = self._cur.rowcount

        # 2. Créer les authorships vérité manquantes
        self._cur.execute(
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
        self._cur.execute(
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

        # 4. Récupérer les formes de nom observées (à ajouter par le service)
        self._cur.execute(
            """
            SELECT DISTINCT author_name_normalized
            FROM source_authorships
            WHERE id = ANY(%s)
              AND author_name_normalized IS NOT NULL
              AND NOT excluded
            """,
            (sa_ids,),
        )
        forms = [r["author_name_normalized"] for r in self._cur.fetchall()]
        for form in forms:
            self.add_name_form(person_id, form)

        return assigned

    def ensure_truth_authorship(self, person_id: int, source: str, authorship_id: int) -> None:
        """Crée/synchronise l'authorship vérité pour une paire (pub, person).

        Même logique que build_authorships.py mais pour une seule paire :
        FK sources, author_position, is_corresponding, in_perimeter,
        structure_ids — agrégés depuis les source_authorships.
        """
        # Trouver la publication_id via source_publications
        self._cur.execute(
            """
            SELECT d.publication_id FROM source_authorships sa
            JOIN source_publications d ON d.id = sa.source_publication_id
            WHERE sa.id = %s AND sa.source = %s
            """,
            (authorship_id, source),
        )
        row = self._cur.fetchone()
        if not row or not row["publication_id"]:
            return
        pub_id = row["publication_id"]

        # 1. INSERT si pas déjà existant
        self._cur.execute(
            """
            INSERT INTO authorships (publication_id, person_id)
            VALUES (%s, %s)
            ON CONFLICT (publication_id, person_id) DO NOTHING
            """,
            (pub_id, person_id),
        )

        # 2. FK sources (source_authorships.authorship_id → authorships.id)
        self._cur.execute(
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
        self._cur.execute(
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
        from utils.sources import AUTHOR_SOURCES_SQL
        self._cur.execute(
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

    def count_authorships_with_name_form(self, person_id: int, name_form: str) -> int:
        """Compte les source_authorships actives d'une personne portant une
        forme de nom donnée. Utilisé par detach_authorships pour décider
        de nettoyer la name_form ou pas."""
        from utils.sources import AUTHOR_SOURCES_SQL
        self._cur.execute(
            f"""
            SELECT COUNT(*) AS n FROM source_authorships sa
            WHERE sa.person_id = %s AND sa.author_name_normalized = %s
              AND sa.source IN {AUTHOR_SOURCES_SQL}
            """,
            (person_id, name_form),
        )
        return self._cur.fetchone()["n"]

    # ── person_name_forms ──────────────────────────────────────────

    def refresh_name_forms(self, person_id: int, forms: set[str]) -> None:
        """Recalcule les formes de nom source 'persons' d'une personne.

        Supprime les anciennes formes 'persons' de cette personne puis insère
        les nouvelles. Les formes partagées avec d'autres personnes ou
        d'autres sources sont préservées.

        `forms` : l'ensemble des formes normalisées calculées par le domaine
        (voir `compute_person_name_forms`).
        """
        # 1a. Formes dont 'persons' est la seule source : retirer le person_id
        self._cur.execute(
            """
            UPDATE person_name_forms
            SET person_ids = array_remove(person_ids, %s)
            WHERE %s = ANY(person_ids)
              AND sources = ARRAY['persons']
            """,
            (person_id, person_id),
        )
        # 1b. Formes multi-sources : retirer 'persons' de sources, garder person_id
        self._cur.execute(
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
        self._cur.execute("""
            DELETE FROM person_name_forms
            WHERE person_ids = '{}' OR person_ids IS NULL
        """)
        # 2. Ajouter les nouvelles formes
        for form in forms:
            self.add_name_form(person_id, form, source="persons")

    def add_name_form(self, person_id: int, full_name: str, source: str | None = None) -> None:
        """Ajoute une forme de nom à person_name_forms si elle n'existe pas déjà.

        Si `source` est fourni (ex: 'hal', 'openalex', 'persons'), il est
        ajouté au tableau sources de la forme de nom.
        """
        if not full_name or not full_name.strip():
            return
        norm = normalize_name(full_name)
        if not norm:
            return
        if source:
            self._cur.execute(
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
            self._cur.execute(
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

    def detach_name_form(self, person_id: int, name_form: str) -> None:
        """Détache une personne d'une forme de nom.

        Retire person_id de person_ids. Supprime la forme si person_ids
        devient vide.
        """
        self._cur.execute(
            """
            UPDATE person_name_forms
            SET person_ids = array_remove(person_ids, %s)
            WHERE name_form = %s
            """,
            (person_id, name_form),
        )
        self._cur.execute(
            """
            DELETE FROM person_name_forms
            WHERE name_form = %s AND person_ids = '{}'
            """,
            (name_form,),
        )
