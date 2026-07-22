"""Adapter PostgreSQL sync pour les authorships et source_authorships."""

from datetime import datetime

from sqlalchemy import Connection, text

from infrastructure.queries.sources_sql import source_case_sql


class PgAuthorshipRepository:
    """Accès PostgreSQL sync aux authorships canoniques et à leurs signatures sources."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Recomposition d'une authorship depuis ses signatures ───────

    def insert_authorship_if_missing(self, publication_id: int, person_id: int) -> None:
        """INSERT ... ON CONFLICT DO NOTHING dans `authorships` pour la paire.

        Skippe les paires présentes dans `rejected_authorships` (rejet canonique).
        """
        self._conn.execute(
            text("""
                INSERT INTO authorships (publication_id, person_id)
                SELECT :pub, :pid
                WHERE NOT EXISTS (
                    SELECT 1 FROM rejected_authorships rj
                    WHERE rj.publication_id = :pub AND rj.person_id = :pid
                )
                ON CONFLICT (publication_id, person_id) DO NOTHING
            """),
            {"pub": publication_id, "pid": person_id},
        )

    def create_authorships_from_sources(
        self, person_id: int, sa_ids: list[int], source_priority: tuple[str, ...]
    ) -> None:
        """Crée les authorships manquantes pour la personne, depuis les signatures du lot.

        Pour chaque `publication_id` distinct, insère une ligne dans `authorships` en prenant les colonnes (`author_position`, `in_perimeter`, `is_corresponding`) de la source la plus prioritaire. Les structures dérivées vivent dans la matview `authorship_structures`, rafraîchie par le caller.
        """
        if not sa_ids:
            return
        self._conn.execute(
            text(f"""
                CREATE TEMP TABLE _chosen_sa AS
                SELECT DISTINCT ON (sd.publication_id)
                    sd.publication_id, sa.id AS sa_id,
                    sa.author_position, sa.in_perimeter, sa.is_corresponding
                FROM source_authorships sa
                JOIN source_publications sd ON sd.id = sa.source_publication_id
                WHERE sa.id = ANY(:ids) AND sd.publication_id IS NOT NULL
                ORDER BY sd.publication_id, {source_case_sql(source_priority)}
            """),
            {"ids": sa_ids},
        )
        self._conn.execute(
            text("""
                INSERT INTO authorships (publication_id, person_id,
                    author_position, in_perimeter, is_corresponding)
                SELECT cs.publication_id, :pid, cs.author_position, cs.in_perimeter,
                       cs.is_corresponding
                FROM _chosen_sa cs
                WHERE NOT EXISTS (
                    SELECT 1 FROM rejected_authorships rj
                    WHERE rj.publication_id = cs.publication_id AND rj.person_id = :pid
                )
                ON CONFLICT (publication_id, person_id) DO NOTHING
            """),
            {"pid": person_id},
        )
        self._conn.execute(text("DROP TABLE _chosen_sa"))

    def link_source_authorships_to_authorship(self, publication_id: int, person_id: int) -> None:
        """Pose `source_authorships.authorship_id` pour l'authorship de la paire, sur toutes les signatures encore non liées."""
        self._conn.execute(
            text("""
                UPDATE source_authorships sa
                SET authorship_id = a.id
                FROM source_publications sd, authorships a
                WHERE sd.id = sa.source_publication_id
                  AND a.publication_id = sd.publication_id
                  AND a.person_id = sa.person_id
                  AND sd.publication_id = :pub
                  AND sa.person_id = :pid
                  AND sa.authorship_id IS NULL
            """),
            {"pub": publication_id, "pid": person_id},
        )

    def link_source_authorships_to_authorships(self, person_id: int, sa_ids: list[int]) -> None:
        """Pose `source_authorships.authorship_id` vers l'authorship canonique de la même paire, pour les lignes du lot. N'écrase que les FK encore nulles (idempotent)."""
        if not sa_ids:
            return
        self._conn.execute(
            text("""
                UPDATE source_authorships sa SET authorship_id = a.id
                FROM source_publications sd, authorships a
                WHERE sa.id = ANY(:ids)
                  AND sd.id = sa.source_publication_id
                  AND a.publication_id = sd.publication_id
                  AND a.person_id = :pid
                  AND sa.authorship_id IS NULL
            """),
            {"ids": sa_ids, "pid": person_id},
        )

    def recompute_authorship_author_position_and_corresponding(
        self, publication_id: int, person_id: int, source_priority: tuple[str, ...]
    ) -> None:
        """Réagrège `authorships.author_position` et `is_corresponding` depuis les signatures actives.

        Aligné sur le build (`propagate_authorship_attributes`) : position par priorité de source, `is_corresponding` en `bool_or` — le FALSE d'une source est une absence de signal, non une négation.
        """
        self._conn.execute(
            text(f"""
                UPDATE authorships a
                SET author_position = sub.pos,
                    is_corresponding = sub.is_corr
                FROM (
                    SELECT sa.authorship_id,
                           (array_agg(sa.author_position ORDER BY
                               {source_case_sql(source_priority)})
                               FILTER (WHERE sa.author_position IS NOT NULL))[1] AS pos,
                           bool_or(sa.is_corresponding) AS is_corr
                    FROM source_authorships sa
                    WHERE sa.authorship_id IS NOT NULL
                    GROUP BY sa.authorship_id
                ) sub
                WHERE a.id = sub.authorship_id
                  AND a.publication_id = :pub AND a.person_id = :pid
            """),
            {"pub": publication_id, "pid": person_id},
        )

    def recompute_authorship_in_perimeter(
        self, publication_id: int, person_id: int, sources: tuple[str, ...]
    ) -> None:
        """Réagrège `authorships.in_perimeter` (OR des signatures) pour la paire.

        Les structures dérivées vivent dans la matview `authorship_structures`, rafraîchie par le caller.
        """
        sources_sql = "(" + ", ".join(f"'{s}'" for s in sources) + ")"
        self._conn.execute(
            text(f"""
                UPDATE authorships a
                SET in_perimeter = COALESCE((
                        SELECT bool_or(sa.in_perimeter)
                        FROM source_authorships sa
                        JOIN source_publications sd ON sd.id = sa.source_publication_id
                        WHERE sa.source IN {sources_sql}
                          AND sd.publication_id = :pub
                          AND sa.person_id = :pid
                    ), FALSE)
                WHERE a.publication_id = :pub AND a.person_id = :pid
            """),
            {"pub": publication_id, "pid": person_id},
        )

    # ── source_authorships : lien personne ↔ signature ─────────────
    # `source_authorships.person_id` pose qu'une signature est portée par une personne. Sa
    # sémantique de suppression (`ON DELETE SET NULL`) le range côté signature : effacer la
    # personne rend la signature orpheline, ne la détruit pas.

    def link_authorship(
        self,
        person_id: int,
        source: str,
        source_authorship_id: int,
        resolution_mode: str,
    ) -> None:
        """Rattache une signature source à une personne, en marquant le canal de résolution.

        `resolution_mode` (`identifier` / `name` / `cross_source`) enregistre par quel canal le `person_id` a été posé ; il porte les réinitialisations ordre-indépendantes de la phase personnes.
        """
        self._conn.execute(
            text(
                "UPDATE source_authorships SET person_id = :pid, "
                "resolution_mode = CAST(:mode AS resolution_mode) "
                "WHERE id = :aid AND source = :src"
            ),
            {"pid": person_id, "aid": source_authorship_id, "src": source, "mode": resolution_mode},
        )

    def unlink_authorship(self, person_id: int, source: str, source_authorship_id: int) -> None:
        self._conn.execute(
            text(
                "UPDATE source_authorships SET person_id = NULL "
                "WHERE id = :aid AND person_id = :pid AND source = :src"
            ),
            {"aid": source_authorship_id, "pid": person_id, "src": source},
        )

    def find_source_authorship_owner(self, source_authorship_id: int) -> int | None:
        """`person_id` d'une signature source. `None` si elle est orpheline ou n'existe pas."""
        return self._conn.execute(
            text("SELECT person_id FROM source_authorships WHERE id = :aid"),
            {"aid": source_authorship_id},
        ).scalar_one_or_none()

    def assign_orphan_sa(self, person_id: int, source_authorship_id: int) -> dict | None:
        """Pose `person_id` sur une signature source orpheline.

        Retourne un dict {source, author_name_normalized} si l'UPDATE a touché une ligne, `None` sinon — la signature n'existe pas, ou elle porte déjà un `person_id` (fût-ce celui demandé). `find_source_authorship_owner` départage.
        """
        row = self._conn.execute(
            text("""
                UPDATE source_authorships sa SET person_id = :pid
                FROM author_identifying_keys aik
                WHERE sa.id = :aid AND sa.person_id IS NULL
                  AND aik.id = sa.identity_id
                RETURNING sa.source::text AS source, aik.author_name_normalized
            """),
            {"pid": person_id, "aid": source_authorship_id},
        ).first()
        return dict(row._mapping) if row else None

    def assign_orphan_source_authorships_to_person(
        self, person_id: int, source_authorship_ids: list[int]
    ) -> int:
        """Pose `person_id` sur les signatures du lot qui sont orphelines, et retourne le nombre touché.

        Les signatures déjà rattachées sont laissées intactes.
        """
        if not source_authorship_ids:
            return 0
        return self._conn.execute(
            text("""
                UPDATE source_authorships SET person_id = :pid
                WHERE id = ANY(:ids) AND person_id IS NULL
                RETURNING id
            """),
            {"pid": person_id, "ids": source_authorship_ids},
        ).rowcount

    def get_distinct_name_forms_from_source_authorships(
        self, source_authorship_ids: list[int]
    ) -> list[str]:
        """Les `author_name_normalized` distincts observés dans le lot."""
        if not source_authorship_ids:
            return []
        rows = self._conn.execute(
            text("""
                SELECT DISTINCT aik.author_name_normalized
                FROM source_authorships sa
                JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                WHERE sa.id = ANY(:ids)
                  AND aik.author_name_normalized IS NOT NULL
            """),
            {"ids": source_authorship_ids},
        ).all()
        return [row.author_name_normalized for row in rows]

    def find_publication_id_for_source_authorship(self, source_authorship_id: int) -> int | None:
        """`publication_id` de la signature, ou `None` si elle n'existe pas ou n'est pas rattachée."""
        return self._conn.execute(
            text("""
                SELECT d.publication_id FROM source_authorships sa
                JOIN source_publications d ON d.id = sa.source_publication_id
                WHERE sa.id = :aid
            """),
            {"aid": source_authorship_id},
        ).scalar_one_or_none()

    def find_publication_ids_for_source_authorships(
        self, source_authorship_ids: list[int]
    ) -> list[int]:
        """Les `publication_id` distincts couverts par un lot de signatures."""
        if not source_authorship_ids:
            return []
        rows = self._conn.execute(
            text("""
                SELECT DISTINCT d.publication_id FROM source_authorships sa
                JOIN source_publications d ON d.id = sa.source_publication_id
                WHERE sa.id = ANY(:ids) AND d.publication_id IS NOT NULL
            """),
            {"ids": source_authorship_ids},
        ).all()
        return [row.publication_id for row in rows]

    def null_person_id_for_name_form(self, person_id: int, name_form: str) -> int:
        """Détache d'une personne les signatures qui portent une forme de nom, et retourne leur nombre.

        Sert au rejet d'une forme : ses signatures sont retirées de la personne (`person_id → NULL`).
        """
        return self._conn.execute(
            text(
                "UPDATE source_authorships sa SET person_id = NULL "
                "FROM author_identifying_keys aik "
                "WHERE sa.person_id = :pid AND aik.id = sa.identity_id "
                "AND aik.author_name_normalized = :nf"
            ),
            {"pid": person_id, "nf": name_form},
        ).rowcount

    # ── authorships ────────────────────────────────────────────────

    def get_authorship_person(self, authorship_id: int) -> dict | None:
        result = self._conn.execute(
            text("SELECT id, person_id, publication_id FROM authorships WHERE id = :id"),
            {"id": authorship_id},
        )
        row = result.first()
        return dict(row._mapping) if row else None

    def reject_authorship(self, publication_id: int, person_id: int) -> None:
        """Enregistre le rejet d'une paire (publication, personne) dans le
        store `rejected_authorships`. Idempotent."""
        self._conn.execute(
            text(
                "INSERT INTO rejected_authorships (publication_id, person_id) "
                "VALUES (:pub, :pid) ON CONFLICT DO NOTHING"
            ),
            {"pub": publication_id, "pid": person_id},
        )

    def find_rejected_authorship(self, publication_id: int, person_id: int) -> datetime | None:
        """Date du rejet de la paire dans `rejected_authorships`, ou None."""
        return self._conn.execute(
            text(
                "SELECT created_at FROM rejected_authorships "
                "WHERE publication_id = :pub AND person_id = :pid"
            ),
            {"pub": publication_id, "pid": person_id},
        ).scalar_one_or_none()

    def delete_rejected_authorship(self, publication_id: int, person_id: int) -> None:
        """Retire la paire de `rejected_authorships` (lève le rejet). Idempotent."""
        self._conn.execute(
            text(
                "DELETE FROM rejected_authorships WHERE publication_id = :pub AND person_id = :pid"
            ),
            {"pub": publication_id, "pid": person_id},
        )

    def unlink_all_source_authorships_for_pair(
        self,
        publication_id: int,
        person_id: int,
    ) -> int:
        """Nulle `person_id` sur toutes les `source_authorships` de cette
        personne dont la `source_publication` pointe sur cette publication.

        Détache la vérité source de la paire entière : « cette personne n'est
        pas l'auteur de cette publication » vaut pour toutes ses sources.
        Retourne le nombre de rows détachées."""
        result = self._conn.execute(
            text("""
                UPDATE source_authorships sa
                SET person_id = NULL
                FROM source_publications sp
                WHERE sa.source_publication_id = sp.id
                  AND sp.publication_id = :pub
                  AND sa.person_id = :pid
            """),
            {"pub": publication_id, "pid": person_id},
        )
        return result.rowcount

    def delete_authorship(self, authorship_id: int) -> None:
        self._conn.execute(
            text("DELETE FROM authorships WHERE id = :id"),
            {"id": authorship_id},
        )

    def delete_orphan_authorships_for_person(self, person_id: int) -> int:
        result = self._conn.execute(
            text("""
                DELETE FROM authorships a
                WHERE a.person_id = :pid
                  AND NOT EXISTS (
                      SELECT 1 FROM source_authorships sa
                      JOIN source_publications sd ON sd.id = sa.source_publication_id
                      WHERE sa.person_id = :pid AND sd.publication_id = a.publication_id
                  )
            """),
            {"pid": person_id},
        )
        return result.rowcount

    # ── confirmed_authorships (épinglage admin, must-link grain signature) ──

    def pin_authorships(self, source_authorship_ids: list[int], person_id: int) -> None:
        if not source_authorship_ids:
            return
        self._conn.execute(
            text("""
                INSERT INTO confirmed_authorships (source_authorship_id, person_id)
                SELECT unnest(CAST(:ids AS integer[])), :pid
                ON CONFLICT (source_authorship_id)
                    DO UPDATE SET person_id = EXCLUDED.person_id
            """),
            {"ids": source_authorship_ids, "pid": person_id},
        )

    def unpin_authorships_for_pair(self, publication_id: int, person_id: int) -> int:
        result = self._conn.execute(
            text("""
                DELETE FROM confirmed_authorships ca
                USING source_authorships sa, source_publications sp
                WHERE ca.source_authorship_id = sa.id
                  AND sa.source_publication_id = sp.id
                  AND sp.publication_id = :pub
                  AND ca.person_id = :pid
            """),
            {"pub": publication_id, "pid": person_id},
        )
        return result.rowcount

    def unpin_authorships_for_name_form(self, person_id: int, name_form: str) -> int:
        result = self._conn.execute(
            text("""
                DELETE FROM confirmed_authorships ca
                USING source_authorships sa, author_identifying_keys aik
                WHERE ca.source_authorship_id = sa.id
                  AND sa.identity_id = aik.id
                  AND ca.person_id = :pid
                  AND aik.author_name_normalized = :form
            """),
            {"pid": person_id, "form": name_form},
        )
        return result.rowcount

    def enforce_confirmed_authorships(self) -> int:
        result = self._conn.execute(
            text("""
                UPDATE source_authorships sa
                SET person_id = ca.person_id
                FROM confirmed_authorships ca
                WHERE ca.source_authorship_id = sa.id
                  AND sa.person_id IS DISTINCT FROM ca.person_id
            """)
        )
        return result.rowcount

    # ── Propagation périmètre UCA depuis les adresses ──────────────

    def find_source_authorships_by_addresses(
        self,
        address_ids: list[int],
    ) -> list[int]:
        result = self._conn.execute(
            text("""
                SELECT DISTINCT saa.source_authorship_id
                FROM source_authorship_addresses saa
                WHERE saa.address_id = ANY(:ids)
            """),
            {"ids": address_ids},
        )
        return [row.source_authorship_id for row in result]

    def recompute_in_perimeter_on_source_authorships(
        self,
        source_authorship_ids: list[int],
        perimeter_structure_ids: list[int],
    ) -> None:
        # `source_authorship_structures` est une matview (réalignée par le
        # pipeline) : on ne l'écrit pas ici. On recalcule in_perimeter
        # directement depuis les adresses résolues
        # filtrées par le périmètre restreint, pour les sa donnés — équivalent
        # à l'ancien EXISTS sur la table de jointure construite avec le même
        # filtre.
        self._conn.execute(
            text("""
                UPDATE source_authorships sa
                SET in_perimeter = EXISTS (
                    SELECT 1
                    FROM source_authorship_addresses saa
                    JOIN address_structures ast ON ast.address_id = saa.address_id
                    WHERE saa.source_authorship_id = sa.id
                      AND ast.structure_id = ANY(:struct_ids)
                      AND ast.is_confirmed IS DISTINCT FROM FALSE
                )
                WHERE sa.id = ANY(:sa_ids)
            """),
            {"sa_ids": source_authorship_ids, "struct_ids": perimeter_structure_ids},
        )

    def propagate_in_perimeter_to_authorships(
        self,
        source_authorship_ids: list[int],
    ) -> None:
        # Identifie les (publication_id, person_id) impactées par les
        # source_authorships modifiées, puis resync le booléen `in_perimeter`
        # sur les authorships correspondantes. Les structures dérivées vivent
        # dans la matview `authorship_structures` : le caller la rafraîchit
        # (`refresh_authorship_structures`) après cette propagation.
        self._conn.execute(
            text("""
            CREATE TEMP TABLE _affected_authorships AS
            SELECT DISTINCT a.id AS authorship_id
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            JOIN authorships a ON a.publication_id = sd.publication_id
                              AND a.person_id = sa.person_id
            WHERE sa.id = ANY(:ids)
              AND sd.publication_id IS NOT NULL
              AND sa.person_id IS NOT NULL
        """),
            {"ids": source_authorship_ids},
        )

        self._conn.execute(
            text("""
            UPDATE authorships a
            SET in_perimeter = EXISTS (
                    SELECT 1 FROM source_publications sd
                    JOIN source_authorships sa ON sa.source_publication_id = sd.id
                                              AND sa.person_id = a.person_id
                                              AND sa.source = sd.source
                    WHERE sd.publication_id = a.publication_id
                      AND sa.in_perimeter = TRUE
                )
            FROM _affected_authorships af
            WHERE a.id = af.authorship_id
        """)
        )

        self._conn.execute(text("DROP TABLE _affected_authorships"))
