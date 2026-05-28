# Ajouter une règle de déduplication des publications par métadonnées

Procédure d'écriture, validation et déploiement d'une règle dans `domain/publications/deduplication.py` + `application/pipeline/publications/metadata_deduplication_rules.py`.

Le chantier [METIER_metadata-deduplication](../chantiers/METIER_metadata-deduplication.md) explique le *pourquoi* (cadre, contraintes, méthode empirique) et tient le **catalogue des règles figées**. Ce playbook est le *comment*, écrit pour être réutilisé à chaque nouvelle règle.

## Quand utiliser ce playbook

À chaque fois qu'un doublon évident remonte (typiquement via [hal-problems/duplicate-pubs](../../interfaces/frontend/src/routes/hal-problems/duplicate-pubs/+page.svelte) onglet « Par métadonnées », ou via `admin/duplicates`) et que la cascade `decide_publication_match` ne le rattrape pas faute d'identifiant cross-source partagé (DOI, NNT, HAL_ID).

Hors-scope : les paires qui ne **sont pas** de vrais doublons. Marquer dans `distinct_publications` et passer.

## Points fixes de l'architecture

- **Cascade unique** : la règle vit dans la cascade `decide_publication_match` ([domain/publications/deduplication.py](../../domain/publications/deduplication.py)), au rang `metadata_match`, après DOI/NNT/HAL_ID. Premier non-None gagne.
- **Deux artefacts par règle figée** :
  - Un membre de `MetadataDeduplicationCase` (domain) qui *énonce la règle métier* dans son docstring.
  - Une fonction `match_<cas>` dans [metadata_deduplication_rules.py](../../application/pipeline/publications/metadata_deduplication_rules.py) (application) qui *implémente* le prefetch + matching.
- **Branchement unique** : pré-fetch dans `match_or_create_publications.process_document`, passage à `decide_publication_match` via `metadata_match: (pub_id, case)`. Pas de phase pipeline additionnelle.
- **Audit** : `PublicationMatchDecision.matched_by` reçoit le membre `MetadataDeduplicationCase`. Trace automatique de la règle déclenchée.
- **Rattrapage rétroactif** : migration Alembic data (SQL pur, sans import applicatif) qui fusionne en base les doublons déjà accumulés. Jouée par `alembic upgrade head`.
- **Négatif respecté** : `distinct_publications` est consulté par la règle (au matching pipeline) et par la migration data (au filtrage des couples).

## Procédure pas-à-pas

La règle se construit par **observation empirique bottom-up**. L'enjeu est de ne *jamais* figer une règle qui produirait des faux positifs sur les couples actuels ni sur ceux qui arriveront. Les étapes 1 à 4 sont méthodologiques (avant tout code) ; les étapes 5 à 8 sont la livraison technique.

### 1. Observer

Un vrai doublon dans `hal-problems/duplicate-pubs` ou `admin/duplicates`. « Vrai » au sens : à l'œil et après lecture des deux fiches, c'est manifestement le même article — même titre, même journal/conf, mêmes auteurs ou presque.

### 2. Construire les critères

Énumérer le set de critères **le plus contraignant possible** qui aurait permis de matcher ce couple à la création :

- `doc_type` identique des deux côtés (point de départ universel).
- Champs textuels normalisés (`title_normalized`, éventuellement `container_title`).
- `pub_year` identique.
- Pas de DOI conflictuel (au moins un des deux nul — deux DOI non-nuls = forcément différents, donc à *ne pas* fusionner par cette règle).
- Signaux auteurs (cf. § suivant).
- Tout signal supplémentaire qui distingue ce cas (longueur minimale du titre pour exclure les titres pauvres, présence d'un journal, etc.).

Penser whitelist *par doc_type* : une règle « proceedings » est plus défensive qu'une règle générique « tout doc_type ».

### 3. Inventorier

SQL ad hoc qui compte les couples en base correspondant aux critères. Pattern type :

```sql
SELECT p1.id AS id_a, p2.id AS id_b
FROM publications p1
JOIN publications p2 ON p1.id < p2.id  -- antisymétrie : un seul (a, b) par paire
 AND <critères de match>
WHERE <whitelist doc_type / longueur titre / etc.>
  AND NOT (p1.doi IS NOT NULL AND p2.doi IS NOT NULL)
  AND NOT EXISTS (
      SELECT 1 FROM distinct_publications dp
      WHERE dp.pub_id_a = p1.id AND dp.pub_id_b = p2.id
  )
ORDER BY p1.id;
```

Ce SQL est **conservé** dans la section « Règles figées » de la fiche chantier — il sert de référence et de base à un éventuel dashboard de non-régression.

### 4. Valider

Revue manuelle de **chaque couple** détecté. Trois sorties possibles :

- **100 % vrais doublons** → la règle est mûre, passer au figeage.
- **Quelques faux positifs identifiables** → raffiner les critères (durcir une whitelist, ajouter un signal) et reprendre en 3. Le marquage `distinct_publications` n'est **pas une porte de sortie** pour une règle imparfaite : il couvre les paires actuelles mais une règle laxiste continue de produire des faux positifs sur les publications futures.
- **Le pattern n'est pas atteignable sans faux positifs** → renoncer. Le doublon initial reste à fusionner à la main via `admin/duplicates`.

### 5. Implémentation

#### 5.1 Member de l'enum

Dans [domain/publications/deduplication.py](../../domain/publications/deduplication.py), ajouter un member à `MetadataDeduplicationCase` :

```python
# <Description métier complète : doc_type ciblé, champs identiques,
# signaux auteurs, exclusions DOI, seuils éventuels.>
# Implémentation : `match_<cas>`.
NOM_DU_CAS = "nom_du_cas"
```

Convention de nommage : la valeur reflète la combinaison des champs (`PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT`, `THESIS_TITLE_YEAR`).
Le docstring du member est la **source unique** de l'énoncé métier — pas de duplication ailleurs.

#### 5.2 Helper `match_<cas>`

Dans [application/pipeline/publications/metadata_deduplication_rules.py](../../application/pipeline/publications/metadata_deduplication_rules.py) :

```python
def match_<cas>(
    conn: Connection,
    *,
    queries: PublicationsMatchOrCreateQueries,
    source_publication_id: int,
    title_normalized: str,
    pub_year: int,
    doi: str | None,         # selon les besoins
    pub_repo: PublicationRepository,
) -> tuple[int, MetadataDeduplicationCase] | None:
    candidates = pub_repo.find_<...>(...)   # lookup typé par règle
    if not candidates:
        return None
    # prefetch des signaux comparés (compteur auteurs, intersection raw_names, ...)
    for cand_id, ... in candidates:
        if <règle>:
            return (cand_id, MetadataDeduplicationCase.NOM_DU_CAS)
    return None
```

Tout I/O passe par `queries: PublicationsMatchOrCreateQueries` et `pub_repo: PublicationRepository` — pas de SQL ad hoc dans le helper.

Si la règle a besoin d'un nouveau lookup typé : ajouter `find_<...>` au [`PublicationRepository`](../../application/ports/repositories/publication_repository.py) et son implémentation.
Si elle a besoin d'un compteur/projection sur le SP candidat : ajouter au port [`PublicationsMatchOrCreateQueries`](../../application/ports/pipeline/publications_match_or_create.py) et son implémentation SQL ([infrastructure/queries/publications/match_or_create.py](../../infrastructure/queries/publications/match_or_create.py)).

#### 5.3 Branchement

Dans [application/pipeline/publications/match_or_create_publications.py](../../application/pipeline/publications/match_or_create_publications.py), aiguillage `doc_type → règle` au bloc `# Prefetch dédup par métadonnées`. Une règle par doc_type ; si une seconde règle se révèle nécessaire sur le même doc_type, voir § Conflits.

### 6. Migration Alembic data

Une migration *dédiée* à cette règle, en SQL pur (`op.execute(...)` + bloc `DO $$ ... $$`). Modèle : [b9a2c8d4e7f1_dedup_proceedings_title_year_authorcount.py](../../alembic/versions/2026_05_24_2030-b9a2c8d4e7f1_dedup_proceedings_title_year_authorcount.py).

Squelette par couple détecté :

1. `v_target_id := LEAST(id_a, id_b)`, `v_source_id := GREATEST(...)` — convention déterministe.
2. **Résilience aux chaînes** : skip si target ou source a déjà été absorbée dans cette boucle (la pub a disparu).
3. **Transfert** : `UPDATE source_publications SET publication_id = target WHERE publication_id = source`.
4. **Transfert authorships canoniques** : DELETE des `authorships` source dont le `person_id` existe déjà côté target (dédup), puis UPDATE du reste.
5. **Cleanup** : `DELETE FROM distinct_publications WHERE pub_id_a = source OR pub_id_b = source`.
6. **Stale-mark target** : `UPDATE publications SET updated_at = 'epoch' WHERE id = target` — le prochain `refresh_from_sources` ré-agrège les méta canoniques (DOI promu par `SOURCE_PRIORITY`, oa_status, abstract, etc.).
7. **DELETE source** : ON DELETE CASCADE sur `publication_subjects`, SET NULL sur `apc_payments`.
8. `RAISE NOTICE` par couple + total final.

`downgrade()` est un `pass` documenté : les fusions ne sont pas réversibles.

Sur une base sans doublon (from-scratch ou déjà nettoyée), la migration est un no-op silencieux.

**Duplication SQL d'inventaire** (fiche chantier ↔ migration) assumée : disparaîtra au prochain squash de schéma.

### 7. Tests

Dans [tests/unit/application/pipeline/publications/](../../tests/unit/application/pipeline/publications/) :

- **Cas positif** : un SP entrant + un candidat satisfaisant les critères → `match_<cas>` retourne `(cand_id, MetadataDeduplicationCase.NOM_DU_CAS)`.
- **Cas négatif sur chaque critère** : un test par critère mis en défaut (titre différent, année différente, doc_type hors whitelist, compteurs incompatibles, DOI conflictuel, paire dans `distinct_publications`) → `None`.
- **Cas de robustesse** : variations de signaux auteurs si la règle en utilise (cf. § Difficulté auteurs).
- **Intégration `decide_publication_match`** : un test qui passe `metadata_match=(id, case)` et vérifie que la décision tombe sur `action="match"` avec `matched_by=<case>`.

### 8. Cataloguer dans la fiche chantier

Ajouter une sous-section dans § « Règles figées » de [METIER_metadata-deduplication.md](../chantiers/METIER_metadata-deduplication.md) :

- Énoncé métier en clair (les critères listés à puces).
- SQL d'inventaire complet (celui qui a servi à la migration).
- Inventaire au figeage : combien de couples remontés, combien validés, ce qu'a éliminé le filtre final.

C'est l'**unique trace persistante** côté docs : le chantier ne « phasifie » plus chaque règle, il les catalogue.

## Difficulté principale : la comparaison d'auteurs

Les `raw_name` sont rarement identiques d'un côté à l'autre (casse, accents, initiales, ordre prénom/nom, affiliation collée). Deux signaux récurrents :

- **Intersection raw-names non-vide** (après normalisation légère type `parse_raw_author_name` + comparaison `last + initial(first)`). Signal *positif fort quand présent*, mais souvent absent. À privilégier quand on en a un.
- **Cohérence du nombre d'auteurs**. Signal *faible mais quasi toujours disponible*. Pour la pub canonique, prendre le `MAX(n_sa) par source` (la source la plus exhaustive représente le « vrai » nombre, cohérent avec ce qu'affiche l'UI hal-problems).

Helpers à mutualiser dans `domain/publications/` (fonctions pures) **au moment où la règle qui en a besoin les demande**, jamais en anticipation. La règle proceedings n'utilise actuellement que le compteur ; la première règle qui mobilise l'intersection raw-names introduit son helper et établit la convention.

## Anti-patterns

- **Règle laxiste avec `distinct_publications` comme garde-fou**. Cf. § 4 : `distinct_publications` ne couvre que les paires actuelles, la règle continue de produire des faux positifs sur les pubs qui arriveront.
- **Fallback générique `(title, year, journal_id)` sans qualifier le doc_type**. Tenté et retiré : trois critères légers produisent plus de fusions fautives que de rattrapages légitimes. Toute règle inconditionnelle sur le `doc_type` doit être justifiée par un audit large.
- **Skip de la migration data**. Sans migration, la règle ne corrige que les *futures* arrivées ; les doublons déjà en base restent. Une règle figée sans migration = règle à moitié déployée.
- **SQL d'inventaire perdu**. Le SQL doit vivre dans la fiche § Règles figées *et* dans la migration. C'est le contrat de référence de la règle, base d'un futur dashboard de non-régression.
- **Re-définir l'énoncé métier ailleurs que dans le docstring de l'enum**. Le code de `match_<cas>` implémente, il ne dédouble pas l'énoncé.

## Exemples concrets

### Règle thèse multi-source

**`THESIS_TITLE_YEAR`** — thèse : même `title_normalized`, même `pub_year`, compatibilité de l'auteur primary.

- Lookup : `find_thesis_by_title(title_normalized, pub_year)`.
- Signal auteur : `thesis_authors_compatible(primary_target, primary_source)`. Si l'auteur source est inconnu, le candidat est accepté (préserve le comportement historique de `normalize_theses.find_publication`).
- Pas de migration data : règle préexistante au chantier, déjà appliquée.
- Référence : [metadata_deduplication_rules.py:match_thesis_by_title_year](../../application/pipeline/publications/metadata_deduplication_rules.py)

### Règle proceedings multi-critères avec longueur titre + compteur auteurs

**`PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT`** — proceedings : même `title_normalized` (longueur > 30), même `pub_year`, même `MAX(count source_authorships par source)`, au moins un DOI nul, hors `distinct_publications`.

- Whitelist : `doc_type = 'proceedings'`.
- Seuil titre > 30 car. : exclut les titres pauvres (« Foreword », « Welcome message »). Inventaire au figeage : sans le seuil, 6 couples (5 vrais + 1 faux « propos introductifs » 19 car.). Avec : les 5 vrais conservés, second titre le plus court = « Frailty Onset Predictions Using Sleep Analysis » (46 car.), marge confortable.
- Signal auteur : compteur égal. Côté canonique, `MAX(n_sa) par source`. Côté SP entrant, count direct.
- Migration data : [b9a2c8d4e7f1](../../alembic/versions/2026_05_24_2030-b9a2c8d4e7f1_dedup_proceedings_title_year_authorcount.py).
- Référence : [metadata_deduplication_rules.py:match_proceedings_by_title_year_authorcount](../../application/pipeline/publications/metadata_deduplication_rules.py)

## Décisions différées (à trancher quand le cas se présente)

- **Conflits entre règles sur un même `doc_type`**. Aujourd'hui, un seul `match_<cas>` est consulté par doc_type. Si deux règles se révèlent nécessaires sur le même type, définir un ordre de priorité explicite (analogue à la cascade `_correct_<field>` côté correction).
- **Factorisation tardive**. Si deux règles figées ne diffèrent que sur un champ (`X` ou `Y` à la place de `X` seul), regroupement en une seule règle de forme « X ou Y » pour la lisibilité. Jamais en anticipation.
- **Dashboard de non-régression**. Vue admin qui rejoue les SQL d'inventaire de chaque règle figée et affiche les compteurs. Tant qu'ils valent zéro, la cascade tient ; un compteur non-nul signale un trou logique. À envisager quand plusieurs règles seront en place.

## Limites du périmètre

Les doublons qui ne se réduisent à *aucun* set de critères déterministe (titres très distincts, métadonnées trop incomplètes) relèvent de la **revue manuelle** via `admin/duplicates`. Le chantier ne cherche pas à atteindre la déduplication exhaustive — il fige les cas répétables et trace les autres pour traitement humain.
