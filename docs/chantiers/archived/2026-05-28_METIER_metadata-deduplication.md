# Chantier — Déduplication des publications par métadonnées

Commencé le 2026-05-24. Cadre technique posé, première règle figée (PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT). Le chantier passe en **maintenance long terme** : ajout de règles au fil de l'eau via le playbook [ajouter-une-regle-de-deduplication](../playbooks/ajouter-une-regle-de-deduplication.md). Cette fiche conserve le contexte du problème et le catalogue des règles figées.

Chantier itératif par nature, transformé en playbook et clôturé le 2026-05-28.

## Contexte

Deux publications sont fusionnées automatiquement à la création si elles partagent un identifiant cross-source (DOI, NNT, HAL_ID), via la cascade [`decide_publication_match`](../../domain/publications/deduplication.py), ou via une règle figée par métadonnées implémentée dans [`metadata_deduplication_rules.py`](../../application/pipeline/publications/metadata_deduplication_rules.py). Chaque règle métier est documentée sur le membre correspondant de `MetadataDeduplicationCase`.

Pour les publications hors-thèse sans identifiant partagé, les doublons restent en base. L'onglet « Par métadonnées » de [hal-problems/duplicate-pubs](../../interfaces/frontend/src/routes/hal-problems/duplicate-pubs/+page.svelte) en révèle un nombre non-négligeable : c'est le révélateur empirique sur lequel ce chantier s'adosse.

Un fallback `(title_normalized, year, journal_id)` avait été tenté dans `find_or_create` puis retiré : 3 critères aussi légers produisent plus de fusions fautives que de rattrapages légitimes. Cet épisode dicte la prudence du chantier : aucune règle générale a priori, chaque règle vit un cycle empirique d'observation → critères → inventaire → validation → figeage (cf. playbook).

## Cadre technique en place

- Enum [`MetadataDeduplicationCase`](../../domain/publications/deduplication.py) côté domain — chaque membre énonce sa règle métier dans son docstring.
- Helpers `match_<cas>` dans [`metadata_deduplication_rules.py`](../../application/pipeline/publications/metadata_deduplication_rules.py) côté application.
- Branchement dans [`match_or_create_publications.process_document`](../../application/pipeline/publications/match_or_create_publications.py) — pré-fetch + passage à `decide_publication_match` via `metadata_match`.
- Audit via `PublicationMatchDecision.matched_by` (trace automatique du membre déclenché).
- Migration Alembic data par règle (SQL pur, rattrapage rétroactif des doublons en base).
- `distinct_publications` respecté côté pipeline (helper) et côté migration (filtre du SQL d'inventaire).

Le **mode d'emploi détaillé** pour ajouter une règle : [docs/playbooks/ajouter-une-regle-de-deduplication.md](../playbooks/ajouter-une-regle-de-deduplication.md).

## Règles figées

### `PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT`

Critères :
- `doc_type = 'proceedings'` des deux côtés.
- `title_normalized` identique, avec `LENGTH(title_normalized) > 30` pour écarter les titres pauvres (« Foreword », « Welcome message »).
- `pub_year` identique.
- Nombre d'auteurs `source_authorships` non-excluded identique. Côté pub canonique, c'est le `MAX` du compteur par source (la source la plus exhaustive représente le « vrai » nombre, cohérent avec ce qu'affiche la page hal-problems).
- Au moins un des deux DOI est null. La contrainte UNIQUE sur `lower(doi)` exclut deux DOI égaux ; deux DOI non-nuls = forcément différents = conflit.
- Paire absente de `distinct_publications`.

SQL d'inventaire (référence persistante, base d'un éventuel dashboard de non-régression) :

```sql
WITH pub_author_counts AS (
  SELECT sp.publication_id, MAX(c.n) AS max_n_auth
  FROM source_publications sp
  JOIN LATERAL (
    SELECT COUNT(*) AS n
    FROM source_authorships sa
    WHERE sa.source_publication_id = sp.id AND NOT sa.excluded
  ) c ON true
  GROUP BY sp.publication_id
)
SELECT p1.id AS id_a, p2.id AS id_b
FROM publications p1
JOIN publications p2
  ON p1.id < p2.id
 AND p1.title_normalized = p2.title_normalized
 AND p1.pub_year = p2.pub_year
 AND p1.doc_type = p2.doc_type
JOIN pub_author_counts c1 ON c1.publication_id = p1.id
JOIN pub_author_counts c2 ON c2.publication_id = p2.id
WHERE p1.doc_type = 'proceedings'
  AND LENGTH(p1.title_normalized) > 30
  AND c1.max_n_auth = c2.max_n_auth
  AND NOT (p1.doi IS NOT NULL AND p2.doi IS NOT NULL)
  AND NOT EXISTS (
    SELECT 1 FROM distinct_publications dp
    WHERE dp.pub_id_a = p1.id AND dp.pub_id_b = p2.id
  )
ORDER BY p1.id;
```

Inventaire au figeage : 6 couples remontés sans le filtre `LENGTH > 30`, dont 5 vrais doublons et 1 faux positif (« propos introductifs », 19 car.). Avec `LENGTH > 30` : les 5 vrais doublons sont conservés, le faux disparaît. Le second titre le plus court parmi les vrais doublons est « Frailty Onset Predictions Using Sleep Analysis » (46 car.), donc la marge avec le seuil reste confortable.

Implémentation : [`match_proceedings_by_title_year_authorcount`](../../application/pipeline/publications/metadata_deduplication_rules.py) + migration [`b9a2c8d4e7f1`](../../alembic/versions/2026_05_24_2030-b9a2c8d4e7f1_dedup_proceedings_title_year_authorcount.py).

### `THESIS_TITLE_YEAR` (préexistante au chantier)

Critères : même `title_normalized`, même `pub_year`, compatibilité de l'auteur primary (via `thesis_authors_compatible`). Implémentation : [`match_thesis_by_title_year`](../../application/pipeline/publications/metadata_deduplication_rules.py). Pas de migration data dédiée (règle préexistante, déjà appliquée par le pipeline historique).

## Liens

- [docs/playbooks/ajouter-une-regle-de-deduplication.md](../playbooks/ajouter-une-regle-de-deduplication.md) — mode d'emploi pour les règles suivantes.
- [`METIER_metadata-correction.md`](METIER_metadata-correction.md) — les règles de dedup s'appuient sur le canonique corrigé par `effective_metadata` ; les inventaires SQL des règles figées lisent donc des `doc_type` qui peuvent avoir été corrigés (par exemple `journal.type=proceedings ⇒ doc_type=conference_paper`), ce qui élargit le périmètre détectable par chaque règle.
