# Chantier — Déduplication des publications par métadonnées.

## Contexte / Problème

Deux publications sont fusionnées automatiquement à la création si elles partagent un identifiant cross-source (DOI, NNT, HAL_ID), via la cascade [`decide_publication_match`](../../domain/publications/deduplication.py), ou via une règle figée par métadonnées implémentée dans [`metadata_deduplication_rules.py`](../../application/pipeline/publications/metadata_deduplication_rules.py). Chaque règle métier est documentée sur le membre correspondant de `MetadataDeduplicationCase`.

Pour les publications hors-thèse sans identifiant partagé, les doublons restent en base. L'onglet « Par métadonnées » de [hal-problems/duplicate-pubs](../../interfaces/frontend/src/routes/hal-problems/duplicate-pubs/+page.svelte) en révèle un nombre non-négligeable : c'est le révélateur empirique sur lequel ce chantier s'adosse.

Un fallback `(title_normalized, year, journal_id)` avait été tenté dans `find_or_create` puis retiré : 3 critères aussi légers produisent plus de fusions fautives que de rattrapages légitimes. Cet épisode dicte la prudence du chantier : aucune règle générale a priori.

### Méthode

Approche empirique bottom-up, par règles successivement figées :

1. **Observer** un vrai doublon (visiblement le même article) dans `hal-problems/duplicate-pubs` (ou via la revue manuelle `admin/duplicates`).
2. **Construire** le set de critères **le plus contraignant possible** qui aurait permis de dédupliquer ce couple.
3. **Inventorier** : SQL qui compte tous les couples de publications correspondant à ces critères en base.
4. **Valider** : revue de chaque couple détecté. Si **100% sont de vrais doublons**, la règle est figée. Sinon, raffiner les critères et reprendre en 3. Le marquage `distinct_publications` n'est pas une porte de sortie pour une règle imparfaite : il ne couvre que les paires actuelles, alors qu'une règle laxiste continuera à produire des faux positifs sur les publications qui arriveront par le pipeline.
5. **Figer** : intégrer la règle à `match_or_create_publications` (le helper de cascade) ET livrer une migration Alembic data qui fusionne rétroactivement les couples concernés en base.
6. **Recommencer** sur un autre cas.

Plus tard, **factoriser** : si plusieurs règles figées ne diffèrent que sur un champ (`X` ou `Y` à la place de `X` seul), les regrouper pour la lisibilité — sans changement de comportement.

### Difficulté principale : la comparaison d'auteurs

Les `raw_name` sont rarement identiques d'un côté à l'autre (variations de casse, accents, initiales, ordre prénom/nom, présence de l'affiliation collée). Deux signaux exploitables qui ressortiront probablement dans les règles :

- **Intersection raw-names non-vide** (après normalisation légère) : signal positif fort quand il existe, mais souvent absent.
- **Cohérence du nombre d'auteurs** : signal faible mais quasi toujours disponible.

L'absence d'identifiants ORCID/IdHAL en commun n'est pas un signal exploitable à ce stade.

## Décisions (proposées — à valider)

1. **Pas de définition a priori d'un premier cas.** Le premier cas sort de l'observation, pas d'un raisonnement théorique. La méthode du Contexte est le cœur du chantier.

2. **Architecture d'une règle figée** :
   - Un membre dans `MetadataDeduplicationCase` (domain), avec un commentaire détaillant les critères + le nom de la fonction d'implémentation.
   - Une fonction `match_<cas>(...)` dans `application/pipeline/publications/metadata_deduplication_rules.py` qui retourne `(pub_id, case) | None`. Pré-fetchée par `match_or_create_publications.process_document` et passée à `decide_publication_match`. C'est le matching à la création (pipeline).
   - Une migration Alembic data dédiée (SQL pur, sans import de code applicatif) qui fusionne rétroactivement les couples détectés sur la base existante. Jouée automatiquement par `alembic upgrade head` en prod. La duplication du SQL d'inventaire entre la fiche et la migration est assumée — elle disparaîtra au prochain squash de schéma.

3. **Branchement à `match_or_create_publications`.** La règle vit dans le helper de cascade, qui est déjà appelé dans la phase pipeline `match_or_create_publications`. Pas de phase pipeline additionnelle. Détails d'intégration (où exactement placer l'appel, comment pré-fetcher) à voir au moment de la première règle.

4. **Le négatif `distinct_publications` reste respecté** par le helper de matching et par la migration data : une paire marquée distincte n'est jamais fusionnée, et un couple détecté lors d'une revue manuelle qui se révèle non-doublon est marqué dans `distinct_publications`, ce qui le retire des inventaires futurs.

5. **Audit** : `PublicationMatchDecision.matched_by: DeduplicationKey | MetadataDeduplicationCase | None` trace déjà la règle qui a déclenché la fusion. La migration data logue par cas le nombre de couples fusionnés.

6. **Helpers auteurs unifiés** créés à la volée au moment où le premier cas le demande (dans `domain/publications/`, fonctions pures). Pas anticipés.

7. **Factorisation tardive uniquement.** Si deux règles figées ne diffèrent que sur un champ, on peut les fusionner en une seule règle de forme « X ou Y », pour la lisibilité. Jamais en anticipation.

## Phasage

### Phase 1 — Première règle

Suivre directement le cycle de la méthode. Le cadre technique (enum + helper de matching + migration Alembic data + branchement dans `match_or_create_publications`) se matérialise au moment du figeage de cette première règle ; il devient le patron des règles suivantes. Commit unique : enum + helper + migration + branchement.

### Phases 2, 3, … — Règles suivantes

Une phase = une règle figée. Chaque règle vit un cycle complet du process. Pas de plan à l'avance sur le nombre ni la nature des règles.

### Phase finale (optionnelle) — Factorisations

Quand au moins deux règles figées sont assimilables (un seul champ varie), les regrouper.

## Décisions complémentaires sur le process

- **SQL d'inventaire** : démarrer ad hoc à la main pour chaque règle. **Mais conserver** chacun dans la section « Règles figées » ci-dessous — ce sont les requêtes de référence d'une règle figée, et la base d'un éventuel dashboard de non-régression.

## Règles figées

### `PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT`

Critères :
- `doc_type = 'proceedings'` des deux côtés.
- `title_normalized` identique, avec `LENGTH(title_normalized) > 30` pour écarter les titres pauvres (« Foreword », « Welcome message »).
- `pub_year` identique.
- Nombre d'auteurs `source_authorships` non-excluded identique. Côté pub canonique, c'est le `MAX` du compteur par source (la source la plus exhaustive représente le « vrai » nombre, cohérent avec ce qu'affiche la page hal-problems).
- Au moins un des deux DOI est null. La contrainte UNIQUE sur `lower(doi)` exclut deux DOI égaux ; deux DOI non-nuls = forcément différents = conflit.
- Paire absente de `distinct_publications`.

SQL d'inventaire (à conserver pour rejouer / dashboard) :

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

Inventaire au moment du figeage : 6 couples remontés sans le filtre `LENGTH > 30`, dont 5 vrais doublons et 1 faux positif (« propos introductifs », 19 car.). Avec `LENGTH > 30` : les 5 vrais doublons sont conservés, le faux disparaît. Le second titre le plus court parmi les vrais doublons est « Frailty Onset Predictions Using Sleep Analysis » (46 car.), donc la marge avec le seuil reste confortable.

## Questions ouvertes

- **Dashboard admin de non-régression données.** Idée : une vue qui rejoue les SQL d'inventaire de chaque règle figée et affiche le compteur. Tant qu'il vaut zéro, la cascade création tient ; un compteur non-nul signale un trou logique (cas qui réapparaît malgré la règle). À envisager une fois plusieurs règles figées.
