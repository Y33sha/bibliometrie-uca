# Nettoyer les tables journals et publishers

*A revoir pour automatiser le maximum d'opérations*

Procédure de diagnostic et de remédiation des défauts récurrents sur les tables `journals`, `publishers`, `doi_prefixes` et leurs relations.

Le chantier [METIER_publishers-journals](../chantiers/archived/2026-05-29_METIER_publishers-journals.md) explique le *pourquoi* (typage, dédup, Phase 4a cohérence DOI ↔ journal). Ce playbook est le *comment*, à appliquer **en prod**.

## Quand utiliser ce playbook

- Périodiquement, en accompagnement d'un run pipeline complet (les nouveaux journaux peuvent introduire des doublons ou des préfixes incohérents).
- Avant un audit de cohérence DOI ↔ journal (les doublons et les préfixes faux-positifs polluent toutes les vues d'incohérence).
- Après une fusion d'imports cross-source qui aurait créé des publishers parallèles.

## Pré-requis

- Accès psql à la base de prod (`DB_NAME=bibliometrie`).
- Accès à l'UI admin (`/admin/journals`, `/admin/publishers`) avec session active.
- Le script de seed est à jour : `interfaces/cli/oneshot/seed_journals_doi_prefix.py` (commit ≥ `bb2aa232`).

## Cas 1 — Doublons de journaux

**Symptôme** : 2 rows distinctes dans `journals` pour la même revue (titre court vs titre long, abréviation INSPIRE vs nom complet, ponctuation différente). Toutes les publis d'une row "vraie" sont signalées comme incohérentes avec la row "doublon" lors de l'audit Phase 4a.

### Diagnostic

```sql
-- Journaux partageant un même doi_prefix : signal fort de doublon.
SELECT doi_prefix, array_agg(id ORDER BY id) AS ids,
       array_agg(title ORDER BY id) AS titles
FROM journals
WHERE doi_prefix IS NOT NULL
GROUP BY doi_prefix
HAVING COUNT(*) > 1
ORDER BY doi_prefix;
```

```sql
-- Journaux partageant un même ISSN ou eISSN (au-delà du doi_prefix).
SELECT issn, array_agg(id ORDER BY id) AS ids, array_agg(title ORDER BY id) AS titles
FROM journals WHERE issn IS NOT NULL
GROUP BY issn HAVING COUNT(*) > 1
UNION ALL
SELECT eissn, array_agg(id ORDER BY id), array_agg(title ORDER BY id)
FROM journals WHERE eissn IS NOT NULL
GROUP BY eissn HAVING COUNT(*) > 1;
```

Cas typiques observés : `Physical Review Letters` / `Phys.Rev.Lett.`, `The European Physical Journal C` / `Eur.Phys.J.C`, `Journal of Instrumentation` / `JINST`.

### Action

UI admin `/admin/journals` → recherche du journal cible → bouton « Fusionner » → sélectionner la source (le doublon) → confirmer. L'endpoint backend (`POST /api/journals/{id}/merge`) repointe les publis et supprime la row source.

Choisir comme cible la row avec le titre le plus canonique (nom long, métadonnées les plus riches).

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

Les paires (journal_publisher, prefix_publisher) qui reviennent souvent désignent les fusions à faire (un publisher absorbe l'autre).

### Action

UI admin `/admin/publishers` → recherche → fusion. Cible : le nom Crossref (le plus rigoureux du point de vue éditorial). Source : le nom issu des sources.

Si l'arbre est complexe (imprint vs groupe : *Nature Portfolio* est un imprint de *Springer Nature*), garder les deux entités distinctes et marquer le parent côté hiérarchie (à instruire au cas par cas).

## Cas 3 — `journals.doi_prefix` qui est un ISBN-13

**Symptôme** : préfixe contenant `/978...` ou `/979...`. DOIs Springer/CUP/etc. de chapitres de livres encodent l'ISBN dans le chemin (`10.1007/978-3-030-XXXXX-X_n`) ; la LCP a attrapé un fragment d'ISBN qui est commun à *plusieurs* séries de livres du même publisher, donc pas spécifique au journal.

### Diagnostic

```sql
SELECT id, title, doi_prefix, journal_type
FROM journals
WHERE doi_prefix ~ '/97[89]'
ORDER BY doi_prefix;
```

### Action

```sql
UPDATE journals SET doi_prefix = NULL WHERE doi_prefix ~ '/97[89]';
```

Le script de seed embarque depuis `bb2aa232` un guard `_ISBN_PREFIX_RE` qui empêche la réintroduction au prochain run.

Note : pour les vraies séries de livres, `doi_prefix` reste structurellement non-discriminant (les DOIs ne distinguent pas les séries du même imprint). Laisser `NULL` est la bonne réponse — la cohérence DOI ↔ journal pour les *book_series* / *ebook_platform* se fera via un autre signal (titre + ISBN + métadonnées éditeur), pas via préfixe.

## Cas 4 — `doi_prefix` trop court (faux positifs intra-publisher)

**Symptôme** : `10.1039/d` (toutes les revues RSC depuis 2020), `10.1017/s` (toutes les revues CUP), `10.1001/jama` (tout JAMA Network). Ces préfixes sont *valides* au sens du script (≥1 char après le `/`) mais ne discriminent pas entre journaux du même publisher.

### Diagnostic

```sql
-- Préfixes qui matchent des DOIs publiés dans plus d'un journal en base.
SELECT j.doi_prefix,
       array_agg(DISTINCT j.title ORDER BY j.title) AS journals_with_prefix,
       (SELECT COUNT(DISTINCT p.journal_id)
        FROM publications p
        WHERE p.doi LIKE j.doi_prefix || '%') AS n_journals_matched_by_publis
FROM journals j
WHERE j.doi_prefix IS NOT NULL
GROUP BY j.doi_prefix
HAVING (SELECT COUNT(DISTINCT p.journal_id)
        FROM publications p
        WHERE p.doi LIKE j.doi_prefix || '%') > 1
ORDER BY n_journals_matched_by_publis DESC;
```

### Action

Cas par cas :

- **Préfixe vraiment générique** (`10.1039/d`, `10.1017/s`) — pas de prefix plus long stable possible : `UPDATE journals SET doi_prefix = NULL` pour les journaux concernés. Le contrôle de cohérence retombe sur le publisher (`doi_prefixes.publisher_id`).
- **Préfixe générique mais journal-spécifique reconstructible** : ex. RSC encode parfois le code journal en lettres après le tiret (`10.1039/d4fo00346h` pour Food & Function). On peut écrire un préfixe enrichi `10.1039/d?fo` (regex) ou laisser NULL si le pattern n'est pas stable. La règle du script (`MIN_CHARS_AFTER_SLASH=1`) reste défensive — préférer NULL au préfixe trompeur.

## Cas 5 — Incohérences DOI ↔ journal résiduelles

Une fois les cas 1-4 traités, lancer l'audit final.

### Diagnostic

```sql
-- Publications dont le DOI matche un doi_prefix d'un autre journal que celui d'attache.
-- Exclut les preprint servers et repositories (incohérence attendue / hors scope).
WITH best_match AS (
    SELECT p.id AS pub_id, p.doi, p.journal_id,
           j_match.id AS match_id, j_match.title AS match_title,
           j_match.doi_prefix AS match_prefix,
           j_match.journal_type::text AS match_type,
           ROW_NUMBER() OVER (PARTITION BY p.id ORDER BY length(j_match.doi_prefix) DESC) AS rn
    FROM publications p
    JOIN journals j_match ON p.doi LIKE j_match.doi_prefix || '%'
    WHERE p.doi IS NOT NULL AND j_match.doi_prefix IS NOT NULL
)
SELECT bm.pub_id, bm.doi,
       j_pub.title AS journal, j_pub.journal_type::text AS journal_type,
       bm.match_title, bm.match_prefix, bm.match_type
FROM best_match bm
JOIN journals j_pub ON j_pub.id = bm.journal_id
WHERE bm.rn = 1
  AND bm.match_id != bm.journal_id
  AND j_pub.journal_type NOT IN ('preprint_server', 'repository')
  AND bm.match_type NOT IN ('preprint_server', 'repository')
ORDER BY j_pub.title, bm.match_title;
```

### Action

Audit manuel par paire (journal_publi, journal_match_DOI) :

- **DOI correct, journal_id erroné** : la publi a été attribuée au mauvais journal lors d'un import. → corriger `publications.journal_id` (UI admin de la publi, ou via une règle de correction au cas pertinent — cf. [playbook ajouter-une-regle-de-correction](ajouter-une-regle-de-correction.md)).
- **DOI corrompu** : DOI mal extrait ou mal saisi côté source. → corriger le DOI sur la publi, ou flagger côté source.
- **DOI d'un preprint qui aurait dû être filtré** : ajouter le préfixe à `OUTLIER_DOI_PREFIXES` dans `seed_journals_doi_prefix.py` et re-runner.
- **Faux positif persistant** : indique probablement un préfixe encore trop court — retour Cas 4.

## Refresh post-nettoyage

Après chaque session de nettoyage (Cas 1-4), re-runner le seed pour bénéficier des données dédoublonnées :

```bash
python -m interfaces.cli.oneshot.seed_journals_doi_prefix --min-pubs 3
```

Le script écrase systématiquement les préfixes calculables et laisse intacts les ambigus (les valeurs manuelles éventuelles posées via l'admin sont préservées si le journal n'est plus calculable — sinon écrasées). Inspecter `data/doi_prefix_seed_ambiguous.csv` pour les cas résiduels qui demanderont curation manuelle via l'admin.

Re-lancer ensuite la query Cas 5 pour mesurer la baisse d'incohérences.

## Liens

- [METIER_publishers-journals](../chantiers/archived/2026-05-29_METIER_publishers-journals.md) — fiche chantier (Phase 4a, contexte global).
- [METIER_doi-ra-datacite](../chantiers/archived/2026-06-20_METIER_doi-ra-datacite.md) — table `doi_prefixes` (préfixes ↔ Registration Agency ↔ publisher).
- `interfaces/cli/oneshot/seed_journals_doi_prefix.py` — script de seed des `journals.doi_prefix`.
