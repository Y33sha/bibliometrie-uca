# Nettoyer les tables journals et publishers

*A revoir pour automatiser le maximum d'opérations*

Procédure de diagnostic et de remédiation des défauts récurrents sur les tables `journals` et `publishers`.

Le chantier [DATA_revues-issn-et-doublons](../chantiers/DATA_revues-issn-et-doublons.md) explique le *pourquoi*. Ce playbook est le *comment*, à appliquer **en prod**.

## Quand utiliser ce playbook

- Périodiquement, en accompagnement d'un run pipeline complet : les nouveaux documents peuvent introduire des doublons de revues ou d'éditeurs.
- Après une fusion d'imports cross-source qui aurait créé des publishers parallèles.

## Pré-requis

- Accès psql à la base de prod (`DB_NAME=bibliometrie`).
- Accès à l'UI admin (`/admin/journals`, `/admin/publishers`) avec session active.

## Cas 1 — Doublons de journaux

**Symptôme** : 2 rows distinctes dans `journals` pour la même revue (titre court vs titre long, abréviation INSPIRE vs nom complet, ponctuation différente).

### Diagnostic

Deux onglets de `/admin/journals` listent les doublons potentiels : « Titres identiques », les revues de même titre normalisé, et « ISSN partagés », les revues qui portent le même ISSN dans `issn` ou `eissn`. Le premier écarte deux revues de même titre qui ont chacune un ISSN, homonymes probables.

Cas typiques observés : `Physical Review Letters` / `Phys.Rev.Lett.`, `The European Physical Journal C` / `Eur.Phys.J.C`, `Journal of Instrumentation` / `JINST`.

### Action

Dans ces deux onglets, le bouton « Garder celle-ci » fusionne les autres revues du groupe dans la revue choisie. Pour une paire hors des onglets : onglet « Toutes les revues » → recherche du journal cible → bouton « Fusionner » → sélectionner la source (le doublon) → confirmer. L'endpoint backend (`POST /api/journals/{id}/merge`) repointe les publis et supprime la row source.

Choisir comme cible la row au titre complet et aux métadonnées les plus riches.

Une collection et l'un de ses volumes peuvent partager un ISSN : l'ISSN revient à la collection. Le retirer du volume, dans la modale « Modifier », le sort de l'onglet.

## Cas 2 — Doublons de publishers (sources vs Crossref)

**Symptôme** : `journals.publisher_id` (créé par les normalizers HAL/OA/WoS à partir du nom brut) ≠ `doi_prefixes.publisher_id` (créé par `resolve_publishers` à partir de l'API Crossref). Ex. *Nature Portfolio* (id source) vs *Springer Science and Business Media LLC* (id Crossref) pour le préfixe `10.1038`.

### Diagnostic

```sql
-- Journaux dont le publisher déclaré diffère du publisher du préfixe DOI le plus fréquent de leurs publis.
WITH journal_top_prefix AS (
    SELECT j.id AS journal_id, j.publisher_id AS j_pub,
           split_part(p.doi, '/', 1) AS prefix,
           COUNT(*) AS n,
           ROW_NUMBER() OVER (PARTITION BY j.id ORDER BY COUNT(*) DESC) AS rn
    FROM journals j
    JOIN publications p ON p.journal_id = j.id
    WHERE p.doi IS NOT NULL
    GROUP BY j.id, j.publisher_id, split_part(p.doi, '/', 1)
)
SELECT j.title AS journal,
       p_j.name AS journal_publisher,
       p_dp.name AS prefix_publisher,
       jtp.prefix, jtp.n AS n_pubs
FROM journal_top_prefix jtp
JOIN journals j ON j.id = jtp.journal_id
JOIN doi_prefixes dp ON dp.prefix = jtp.prefix
LEFT JOIN publishers p_j ON p_j.id = jtp.j_pub
LEFT JOIN publishers p_dp ON p_dp.id = dp.publisher_id
WHERE jtp.rn = 1
  AND jtp.j_pub IS NOT NULL
  AND dp.publisher_id IS NOT NULL
  AND jtp.j_pub != dp.publisher_id
ORDER BY jtp.n DESC;
```

### Action

Le nom Crossref désigne le déposant des DOI : souvent le groupe (*Informa UK Limited* pour Taylor & Francis), parfois une plateforme (CAIRN.INFO, OpenEdition). Il ne sert pas de référence. Une marque reste l'éditeur que donnent les sources (Routledge, Dove Medical Press). Seul l'usage décide d'un rattachement, comme *Elsevier Masson* dans *Elsevier* : UI admin `/admin/publishers` → recherche → fusion.

## Cas 3 — Recueils d'actes typés revue

### Diagnostic

L'onglet « Recueils d'actes probables » de `/admin/journals` liste les revues typées « revue » dont la majorité des documents sont des articles de congrès, d'après le type donné par chaque source. La colonne « Articles de congrès » donne leur part. Les revues sans ISSN viennent en tête.

### Action

Le bouton « Recueil d'actes » type la revue en recueil d'actes, après confirmation. Les publications de la revue sont requalifiées, et la revue sort de la file. Une vraie revue qui publie les résumés d'un congrès en supplément (*Value in Health*, *Diabetologia*) reste dans la file.

## Liens

- [DATA_revues-issn-et-doublons](../chantiers/DATA_revues-issn-et-doublons.md) — ISSN, doublons de revues et d'éditeurs, livres et recueils d'actes.
- [METIER_doi-ra-datacite](../chantiers/archived/2026-06-20_METIER_doi-ra-datacite.md) — table `doi_prefixes` (préfixes ↔ Registration Agency ↔ publisher).
