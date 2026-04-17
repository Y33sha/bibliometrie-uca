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


class PgPersonRepository:
    """Accès PostgreSQL à l'agrégat Person."""

    def __init__(self, cur):
        """cur : curseur psycopg2 dans la transaction courante (fournie
        par le service appelant, qui gère le cycle de vie de la connexion)."""
        self._cur = cur

    # ── persons ────────────────────────────────────────────────────

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
