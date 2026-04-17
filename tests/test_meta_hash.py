"""
Tests d'intégration — protection des publications >100 auteurs via meta_hash.

Vérifie que le mécanisme meta_hash empêche l'écrasement des authorships
complètes (obtenues par refetch individuel) lors d'un import bulk ultérieur
qui ne contient que 100 auteurs (troncature API OpenAlex).

Scénarios testés :
1. meta_hash identique → raw_data inchangé (authorships préservées)
2. meta_hash différent mais plus d'auteurs en base → metadata mise à jour,
   authorships préservées
3. meta_hash différent et moins d'auteurs en base → remplacement complet
"""

from psycopg2.extras import Json

from extraction.common import compute_hash


def compute_meta_hash(raw_data: dict) -> str:
    filtered = {k: v for k, v in raw_data.items() if k != "authorships"}
    return compute_hash(filtered)


def _make_work(openalex_id, n_authors, title="Test Publication", cited_by_count=10):
    """Crée un work OpenAlex synthétique avec n auteurs."""
    authorships = [
        {
            "author_position": "first" if i == 0 else "middle",
            "author": {
                "id": f"https://openalex.org/A{i:06d}",
                "display_name": f"Author {i}",
                "orcid": None,
            },
            "institutions": [],
            "raw_author_name": f"Author {i}",
            "raw_affiliation_strings": [],
        }
        for i in range(n_authors)
    ]
    return {
        "id": f"https://openalex.org/{openalex_id}",
        "doi": f"https://doi.org/10.1234/{openalex_id.lower()}",
        "title": title,
        "display_name": title,
        "publication_year": 2024,
        "publication_date": "2024-01-15",
        "type": "article",
        "language": "en",
        "primary_location": {"source": {"display_name": "Test Journal"}},
        "locations": [],
        "open_access": {"is_oa": False, "oa_status": "closed"},
        "authorships": authorships,
        "cited_by_count": cited_by_count,
        "biblio": {"volume": "1", "issue": "1"},
        "is_retracted": False,
    }


def _insert_staging(db, work):
    """Insère un work dans staging."""
    raw_hash = compute_hash(work)
    meta_hash = compute_meta_hash(work)
    doi = work.get("doi", "").replace("https://doi.org/", "")
    openalex_id = work["id"].replace("https://openalex.org/", "")
    db.execute(
        """
        INSERT INTO staging (source, source_id, doi, raw_data, raw_hash, meta_hash)
        VALUES ('openalex', %s, %s, %s::jsonb, %s, %s)
        ON CONFLICT (source, source_id) DO UPDATE SET
            raw_data = CASE
                WHEN staging.meta_hash IS NOT DISTINCT FROM EXCLUDED.meta_hash
                    THEN staging.raw_data
                WHEN jsonb_array_length(staging.raw_data->'authorships')
                     > jsonb_array_length(EXCLUDED.raw_data->'authorships')
                    THEN jsonb_set(staging.raw_data,
                         '{title}', EXCLUDED.raw_data->'title')
                      || jsonb_build_object(
                         'open_access', EXCLUDED.raw_data->'open_access',
                         'primary_location', EXCLUDED.raw_data->'primary_location',
                         'locations', EXCLUDED.raw_data->'locations',
                         'cited_by_count', EXCLUDED.raw_data->'cited_by_count',
                         'type', EXCLUDED.raw_data->'type',
                         'language', EXCLUDED.raw_data->'language',
                         'biblio', EXCLUDED.raw_data->'biblio',
                         'is_retracted', EXCLUDED.raw_data->'is_retracted')
                ELSE EXCLUDED.raw_data
            END,
            raw_hash = CASE
                WHEN staging.meta_hash IS NOT DISTINCT FROM EXCLUDED.meta_hash
                    THEN staging.raw_hash
                ELSE EXCLUDED.raw_hash
            END,
            meta_hash = COALESCE(EXCLUDED.meta_hash, staging.meta_hash),
            processed = CASE
                WHEN staging.meta_hash IS NOT DISTINCT FROM EXCLUDED.meta_hash
                    THEN staging.processed
                ELSE FALSE
            END,
            last_seen_at = now()
    """,
        (openalex_id, doi, Json(work), raw_hash, meta_hash),
    )


def _get_staging(db, openalex_id):
    db.execute(
        "SELECT raw_data, raw_hash, meta_hash, processed FROM staging WHERE source = 'openalex' AND source_id = %s",
        (openalex_id,),
    )
    return db.fetchone()


class TestMetaHashProtection:
    def test_same_meta_hash_preserves_authorships(self, db):
        """Import bulk avec meta_hash identique → authorships complètes préservées."""
        # 1. Simuler un refetch : 150 auteurs
        full_work = _make_work("W100", 150)
        _insert_staging(db, full_work)

        row = _get_staging(db, "W100")
        assert len(row["raw_data"]["authorships"]) == 150

        # Marquer comme processed (simule normalisation)
        db.execute(
            "UPDATE staging SET processed = TRUE WHERE source = 'openalex' AND source_id = 'W100'"
        )

        # 2. Import bulk : même work, mais tronqué à 100 auteurs
        truncated_work = _make_work("W100", 100)  # même metadata
        _insert_staging(db, truncated_work)

        row = _get_staging(db, "W100")
        # Les 150 auteurs doivent être préservés
        assert len(row["raw_data"]["authorships"]) == 150
        # processed doit rester TRUE (pas de changement réel)
        assert row["processed"] is True

    def test_different_meta_hash_preserves_authorships_updates_metadata(self, db):
        """Meta_hash différent mais plus d'auteurs en base → metadata MAJ, authorships préservées."""
        # 1. Version complète : 150 auteurs
        full_work = _make_work("W200", 150, title="Original Title")
        _insert_staging(db, full_work)

        # 2. Import bulk avec titre modifié mais tronqué à 100
        updated_work = _make_work("W200", 100, title="Updated Title", cited_by_count=42)
        _insert_staging(db, updated_work)

        row = _get_staging(db, "W200")
        # Authorships préservées (150)
        assert len(row["raw_data"]["authorships"]) == 150
        # Metadata mise à jour
        assert row["raw_data"]["title"] == "Updated Title"
        assert row["raw_data"]["cited_by_count"] == 42
        # processed = FALSE (changement réel détecté)
        assert row["processed"] is False

    def test_different_meta_hash_fewer_authors_replaces(self, db):
        """Meta_hash différent et moins d'auteurs en base → remplacement complet."""
        # 1. Version initiale : 50 auteurs
        initial_work = _make_work("W300", 50, title="Initial")
        _insert_staging(db, initial_work)

        # 2. Import avec plus d'auteurs et titre différent
        updated_work = _make_work("W300", 80, title="Updated")
        _insert_staging(db, updated_work)

        row = _get_staging(db, "W300")
        # Remplacement complet : 80 auteurs
        assert len(row["raw_data"]["authorships"]) == 80
        assert row["raw_data"]["title"] == "Updated"

    def test_exact_100_then_refetch_preserves(self, db):
        """Scénario complet : import bulk (100) → refetch (200) → reimport bulk (100)."""
        # 1. Import bulk initial : exactement 100 auteurs (tronqué)
        truncated = _make_work("W400", 100)
        _insert_staging(db, truncated)
        assert _get_staging(db, "W400")["raw_data"]["authorships"].__len__() == 100

        # 2. Refetch individuel : 200 auteurs (complet)
        full = _make_work("W400", 200)
        db.execute(
            """
            UPDATE staging
            SET raw_data = %s::jsonb, raw_hash = %s, meta_hash = %s,
                processed = FALSE
            WHERE source = 'openalex' AND source_id = 'W400'
        """,
            (Json(full), compute_hash(full), compute_meta_hash(full)),
        )

        row = _get_staging(db, "W400")
        assert len(row["raw_data"]["authorships"]) == 200

        db.execute(
            "UPDATE staging SET processed = TRUE WHERE source = 'openalex' AND source_id = 'W400'"
        )

        # 3. Reimport bulk : 100 auteurs, mêmes métadonnées
        reimport = _make_work("W400", 100)
        _insert_staging(db, reimport)

        row = _get_staging(db, "W400")
        # Les 200 auteurs doivent être préservés
        assert len(row["raw_data"]["authorships"]) == 200
        assert row["processed"] is True
