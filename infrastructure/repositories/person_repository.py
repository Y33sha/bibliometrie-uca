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
