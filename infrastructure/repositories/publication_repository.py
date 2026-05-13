"""Adapter PostgreSQL pour la persistance des publications.

Isole le SQL de la couche application. Implémente le port
`PublicationRepository` défini dans domain/ports/.

Toutes les queries publications utilisent `text()` paramétré : trop
intriquées en casts enum (oa_type, doc_type, source_type) et opérations
array pour gagner à passer par MetaData.
"""

from sqlalchemy import Connection, text

from domain.publication import (  # noqa: F401 — re-export pour compat
    PubByDoi,
    PubByNnt,
    PubByTitle,
    PubThesisCandidate,
)
from domain.publications.identifiers import DOI
from domain.publications.publication import Publication


class PgPublicationRepository:
    """Accès PostgreSQL à l'agrégat Publication via une `Connection` SA."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    # ── Recherches ─────────────────────────────────────────────────

    def find_by_doi(self, doi: str) -> PubByDoi | None:
        """Cherche une publication par DOI (case-insensitive)."""
        if not doi:
            return None
        row = self._conn.execute(
            text(
                "SELECT id, CAST(doc_type AS text) AS doc_type, title_normalized "
                "FROM publications WHERE lower(doi) = lower(:doi)"
            ),
            {"doi": doi},
        ).first()
        if not row:
            return None
        return PubByDoi(id=row.id, doc_type=row.doc_type, title_normalized=row.title_normalized)

    def find_by_nnt(self, nnt: str) -> PubByNnt | None:
        """Cherche une publication via NNT stocké dans source_publications.external_ids."""
        if not nnt:
            return None
        row = self._conn.execute(
            text("""
                SELECT p.id, CAST(p.doc_type AS text) AS doc_type, p.title_normalized
                FROM publications p
                JOIN source_publications sd ON sd.publication_id = p.id
                WHERE sd.external_ids->>'nnt' = :nnt
                LIMIT 1
            """),
            {"nnt": nnt.upper()},
        ).first()
        if not row:
            return None
        return PubByNnt(id=row.id, doc_type=row.doc_type, title_normalized=row.title_normalized)

    def find_by_title(
        self,
        title_normalized: str,
        pub_year: int,
        journal_id: int,
    ) -> PubByTitle | None:
        """Cherche une publication par titre normalisé + année + journal.
        Ne matche que les articles avec journal connu."""
        if not title_normalized or not journal_id:
            return None
        row = self._conn.execute(
            text("""
                SELECT id, doi FROM publications
                WHERE title_normalized = :tn AND pub_year = :py AND journal_id = :jid
                LIMIT 1
            """),
            {"tn": title_normalized, "py": pub_year, "jid": journal_id},
        ).first()
        if not row:
            return None
        return PubByTitle(id=row.id, doi=row.doi)

    def find_thesis_by_title(
        self,
        title_normalized: str,
        pub_year: int,
    ) -> list[PubThesisCandidate]:
        """Cherche des thèses par titre normalisé + année.

        Retourne les candidats pour déduplication thesis-specific
        (pas de journal_id, donc le tier 2 standard ne fonctionne pas).
        """
        if not title_normalized or not pub_year:
            return []
        result = self._conn.execute(
            text("""
                SELECT id, doi FROM publications
                WHERE title_normalized = :tn AND pub_year = :py
                  AND doc_type IN ('thesis', 'ongoing_thesis')
                ORDER BY id
            """),
            {"tn": title_normalized, "py": pub_year},
        )
        return [PubThesisCandidate(id=row.id, doi=row.doi) for row in result]

    # ── Chargement / persistance de l'aggregate Publication ────────

    def find_by_id(self, pub_id: int) -> Publication | None:
        """Hydrate l'aggregate Publication depuis la ligne `publications`.

        Charge les attributs métier (title, pub_year, doc_type, doi,
        oa_status, journal_id, container_title, language, countries).
        Les authorships ne sont pas chargées par défaut (projection
        lecture séparée si nécessaire).
        """
        row = self._conn.execute(
            text("""
                SELECT id, title, title_normalized,
                       CAST(doc_type AS text) AS doc_type,
                       pub_year, doi,
                       CAST(oa_status AS text) AS oa_status,
                       journal_id, container_title, language, countries
                FROM publications
                WHERE id = :id
            """),
            {"id": pub_id},
        ).first()
        if not row:
            return None
        m = row._mapping
        return Publication(
            id=m["id"],
            title=m["title"],
            pub_year=m["pub_year"],
            title_normalized=m["title_normalized"],
            doc_type=m["doc_type"],
            doi=DOI(m["doi"]) if m["doi"] else None,
            oa_status=m["oa_status"],
            journal_id=m["journal_id"],
            container_title=m["container_title"],
            language=m["language"],
            countries=tuple(m["countries"]) if m["countries"] else (),
        )

    def save(self, pub: Publication) -> None:
        """Persiste l'état mutable de l'aggregate Publication.

        Met à jour les champs éditables (title, title_normalized, doc_type,
        doi, oa_status, journal_id, container_title, language, countries).
        Le champ `pub_year` n'est pas mis à jour ici (immuable côté métier
        après création). `pub.id` doit être posé (entité persistée).
        """
        if pub.id is None:
            raise ValueError("save(pub) : pub.id doit être posé (utiliser create pour insérer)")
        self._conn.execute(
            text("""
                UPDATE publications SET
                    title = :title,
                    title_normalized = :tn,
                    doc_type = CAST(:dt AS doc_type),
                    doi = :doi,
                    oa_status = CAST(:oa AS oa_type),
                    journal_id = :jid,
                    container_title = :ct,
                    language = :lang,
                    countries = CAST(:c AS text[]),
                    updated_at = now()
                WHERE id = :id
            """),
            {
                "id": pub.id,
                "title": pub.title,
                "tn": pub.title_normalized,
                "dt": pub.doc_type,
                "doi": str(pub.doi) if pub.doi else None,
                "oa": pub.oa_status,
                "jid": pub.journal_id,
                "ct": pub.container_title,
                "lang": pub.language,
                "c": list(pub.countries) if pub.countries else None,
            },
        )

    # ── Écritures simples ──────────────────────────────────────────

    def update_oa_status(self, pub_id: int, oa_status: str) -> None:
        """Met à jour le statut OA d'une publication."""
        self._conn.execute(
            text(
                "UPDATE publications "
                "SET oa_status = CAST(:os AS oa_type), updated_at = now() "
                "WHERE id = :id"
            ),
            {"os": oa_status, "id": pub_id},
        )

    def update_countries(self, pub_id: int, countries: list[str]) -> None:
        """Met à jour les pays d'une publication."""
        self._conn.execute(
            text("UPDATE publications SET countries = :c, updated_at = now() WHERE id = :id"),
            {"c": countries, "id": pub_id},
        )

    def update_sources(self, pub_id: int) -> None:
        """Recalcule publications.sources depuis source_publications.

        Pas de lecture préalable : agrégation SQL directe en une requête.
        """
        self._conn.execute(
            text("""
                UPDATE publications SET sources = COALESCE(sub.srcs, '{}'),
                                        updated_at = now()
                FROM (
                    SELECT array_agg(
                        DISTINCT CAST(source AS source_type)
                        ORDER BY CAST(source AS source_type)
                    ) AS srcs
                    FROM source_publications
                    WHERE publication_id = :id
                ) sub
                WHERE id = :id
            """),
            {"id": pub_id},
        )

    # ── Accès bas niveau au champ doi ──────────────────────────────

    def get_doi(self, pub_id: int) -> str | None:
        """Retourne le DOI courant d'une publication, ou None."""
        return self._conn.execute(
            text("SELECT doi FROM publications WHERE id = :id"), {"id": pub_id}
        ).scalar_one_or_none()

    def set_doi(self, pub_id: int, doi: str) -> None:
        """Attribue un DOI à une publication (ne vérifie pas les conflits
        d'unicité — le caller doit l'avoir fait via find_by_doi)."""
        self._conn.execute(
            text("UPDATE publications SET doi = :doi, updated_at = now() WHERE id = :id"),
            {"doi": doi, "id": pub_id},
        )

    def clear_doi(self, pub_id: int) -> None:
        """Retire le DOI d'une publication (utilisé lors des conflits
        chapitre/ouvrage)."""
        self._conn.execute(
            text("UPDATE publications SET doi = NULL, updated_at = now() WHERE id = :id"),
            {"id": pub_id},
        )

    # ── Agrégation depuis source_publications ──────────────────────

    def get_source_rows(self, pub_id: int) -> list[dict]:
        """Retourne toutes les lignes source_publications attachées à
        une publication, avec les champs nécessaires au recalcul
        d'agrégation (refresh_from_sources).
        """
        result = self._conn.execute(
            text("""
                SELECT source, doi, doc_type, pub_year, journal_id, oa_status,
                       container_title, language, abstract, keywords, countries,
                       topics, biblio, meta, is_retracted, external_ids
                FROM source_publications
                WHERE publication_id = :id
            """),
            {"id": pub_id},
        )
        return [dict(row._mapping) for row in result]

    def update_aggregated(
        self,
        pub_id: int,
        *,
        doi: str | None,
        doc_type: str,
        pub_year: int | None,
        journal_id: int | None,
        oa_status: str | None,
        container_title: str | None,
        language: str | None,
        abstract: str | None,
        keywords: list[str] | None,
        countries: list[str] | None,
        topics: dict | None,
        biblio: dict | None,
        meta: dict | None,
        is_retracted: bool,
    ) -> None:
        """Écrit les valeurs agrégées sur une publication.

        Appelé par refresh_from_sources après calcul des valeurs
        fusionnées. Le caller garde la responsabilité d'appeler
        ensuite `update_sources` pour le tableau `sources`.
        """
        self._conn.execute(
            text("""
                UPDATE publications SET
                    doi = :doi, doc_type = CAST(:doc_type AS doc_type),
                    pub_year = :pub_year, journal_id = :journal_id,
                    oa_status = CAST(:oa_status AS oa_type),
                    container_title = :container_title, language = :language,
                    abstract = :abstract, keywords = :keywords,
                    countries = :countries, topics = CAST(:topics AS jsonb),
                    biblio = CAST(:biblio AS jsonb), meta = CAST(:meta AS jsonb),
                    is_retracted = :is_retracted, updated_at = now()
                WHERE id = :pub_id
            """),
            {
                "doi": doi,
                "doc_type": doc_type,
                "pub_year": pub_year,
                "journal_id": journal_id,
                "oa_status": oa_status,
                "container_title": container_title,
                "language": language,
                "abstract": abstract,
                "keywords": keywords,
                "countries": countries,
                "topics": _json_dumps_or_none(topics),
                "biblio": _json_dumps_or_none(biblio),
                "meta": _json_dumps_or_none(meta),
                "is_retracted": is_retracted,
                "pub_id": pub_id,
            },
        )

    # ── Création ───────────────────────────────────────────────────

    def create(
        self,
        *,
        title: str,
        title_normalized: str,
        doc_type: str,
        pub_year: int,
        doi: str | None,
        oa_status: str,
        journal_id: int | None,
        container_title: str | None,
        language: str | None,
    ) -> int:
        """Insère une publication et retourne son id.

        Le caller est responsable du tier de déduplication avant
        d'appeler `create` — le repo ne fait que le INSERT brut.
        """
        return self._conn.execute(
            text("""
                INSERT INTO publications
                    (title, title_normalized, doc_type, pub_year, doi,
                     oa_status, journal_id, container_title, language)
                VALUES (:title, :tn, CAST(:doc_type AS doc_type), :py, :doi,
                        CAST(:oa AS oa_type), :jid, :ct, :lang)
                RETURNING id
            """),
            {
                "title": title,
                "tn": title_normalized,
                "doc_type": doc_type,
                "py": pub_year,
                "doi": doi,
                "oa": oa_status,
                "jid": journal_id,
                "ct": container_title,
                "lang": language,
            },
        ).scalar_one()

    # ── Fusion ─────────────────────────────────────────────────────

    def merge_into(self, target_id: int, source_id: int) -> None:
        """Plumbing FK de fusion : `source_id` est absorbée par `target_id`.

        Séquence SQL (atomique dans la transaction du caller) :

        1. Transfert des `source_publications` (FK vers target).
        2. Transfert des `authorships` vérité (avec déduplication par `person_id` : si target a déjà une row pour ce person, on supprime celle de source au lieu de la déplacer).
        3. Nettoyage des paires `distinct_publications` impliquant source.
        4. Suppression de la ligne `publications` source.

        L'enrichissement des métadonnées canoniques (doi, oa_status, countries, etc.) est porté par `Publication.absorb(other)` côté domaine et persisté par `repo.save(target)` côté application — pas par cette méthode. Le caller (`application.publications.merge_publications`) orchestre : absorb → save → merge_into → update_sources.
        """
        # 1. Transférer les source_publications
        self._conn.execute(
            text("UPDATE source_publications SET publication_id = :t WHERE publication_id = :s"),
            {"t": target_id, "s": source_id},
        )

        # 2. Transférer les authorships vérité (dédup par person_id)
        self._conn.execute(
            text("""
                DELETE FROM authorships
                WHERE publication_id = :s
                  AND person_id IN (
                      SELECT person_id FROM authorships WHERE publication_id = :t
                  )
            """),
            {"s": source_id, "t": target_id},
        )
        self._conn.execute(
            text("UPDATE authorships SET publication_id = :t WHERE publication_id = :s"),
            {"t": target_id, "s": source_id},
        )

        # 3. Nettoyer distinct_publications et supprimer la source
        self._conn.execute(
            text("DELETE FROM distinct_publications WHERE pub_id_a = :s OR pub_id_b = :s"),
            {"s": source_id},
        )
        self._conn.execute(text("DELETE FROM publications WHERE id = :s"), {"s": source_id})

    # ── distinct_publications ──────────────────────────────────────

    def mark_distinct(self, pub_id_a: int, pub_id_b: int) -> tuple[int, int] | None:
        """Marque deux publications comme distinctes. Idempotent.

        Retourne (a, b) si la paire vient d'être insérée, None sinon —
        le caller décide s'il émet un audit ou pas.
        """
        row = self._conn.execute(
            text("""
                INSERT INTO distinct_publications (pub_id_a, pub_id_b)
                VALUES (LEAST(:a, :b), GREATEST(:a, :b))
                ON CONFLICT DO NOTHING
                RETURNING pub_id_a, pub_id_b
            """),
            {"a": pub_id_a, "b": pub_id_b},
        ).first()
        if not row:
            return None
        return row.pub_id_a, row.pub_id_b


def _json_dumps_or_none(value: dict | None) -> str | None:
    """Sérialise un dict en string JSON pour `CAST(:p AS jsonb)`. None passé tel quel."""
    if value is None:
        return None
    import json

    return json.dumps(value)
