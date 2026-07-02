# Ajouter une règle de déduplication des publications

*Obsolète, à réécrire*

Procédure d'écriture, validation et déploiement d'une règle de rapprochement de `source_publications`.

Ce playbook est le *comment*. Le cadre conceptuel et le catalogue des décisions par type vivent dans la fiche [DATA_dedup-pairwise-gated](../chantiers/archived/2026-06-26_DATA_dedup-pairwise-gated.md).

## Modèle : clustering par tokens de confirmation

La déduplication est un record-linkage par graphe. Chaque `source_publication` est un nœud ; deux SP sont reliées si elles partagent une **clé de confirmation** (un *token*). Une publication canonique est une **composante connexe** de ce graphe, partitionnée par DOI.

- **Projection des tokens** : [`project_confirmation_keys`](../../domain/source_publications/keys.py) lit une SP (colonnes corrigées + `external_ids`) et renvoie son jeu de tokens. Tokens en place : `doi`, `nnt`, `hal_id` (multivalué), `pmid`, et `metadata_block` (`<doc_type>|<title_normalized>|<pub_year>`, gardé par une longueur minimale de titre).
- **Clustering** : [`connected_components`](../../domain/entity_resolution.py) regroupe les SP reliées par token partagé (fermeture transitive).
- **Assignation** : [`plan_reconciliation`](../../domain/publications/reconciliation.py) assigne chaque SP au pub-ancre de sa partition `(composante ∩ DOI)`. La passe applicative est [`reconcile_components`](../../application/pipeline/publications/reconcile_components.py) (phase `publications`).
- **Univers SQL** : [`publications_reconciliation.py`](../../infrastructure/queries/pipeline/publications_reconciliation.py) construit le voisinage 1-hop des SP `keys_dirty` — une branche `UNION` par type de token, qui ramène les SP partageant ce token avec une SP dirty.

Un token est une **égalité** : deux SP au même token sont la même œuvre, sans comparaison. C'est ce qui le rend `GROUP BY`-able et le fait entrer nativement dans le clustering.

**Cannot-link DOI** : deux DOI non-nuls distincts ne fusionnent jamais, à aucun palier. La partition `∩ DOI` les sépare même s'ils sont co-bloqués par un autre token.

## Quand un signal est-il un token ?

Un signal devient un token quand l'**égalité** d'une valeur dérivable de la SP vaut identité d'œuvre — assez sélective pour ne pas regrouper des œuvres distinctes. Les identifiants (DOI, NNT, hal_id, pmid) le sont par nature. Une clé composite de métadonnées (`metadata_block`) l'est pour les classes où l'audit le démontre.

Un token est une **valeur unique** que la SP porte : on range les SP par elle (`GROUP BY`), sans comparaison. Un signal qui n'est pas une telle valeur — l'accord d'auteurs est un *recouvrement* entre deux listes, pas une valeur à ranger — ne peut pas être un token ; le rapprochement par auteurs relève d'un autre mécanisme (cf. fiche chantier). Ce playbook couvre les tokens.

## Procédure pas-à-pas

La règle se construit par **observation empirique bottom-up**. L'enjeu : ne jamais figer un token qui produirait des fusions fautives, sur le stock actuel comme sur les arrivées futures. Les étapes 1 à 4 sont méthodologiques (avant tout code) ; 5 à 7 sont la livraison.

### 1. Observer

Un vrai doublon que le clustering ne rattrape pas : deux publications manifestement identiques (à l'œil, après lecture des deux fiches) que les tokens en place ne relient pas, faute de clé partagée.

### 2. Construire le critère d'égalité

Énoncer la valeur composite **la plus sélective possible** dont l'égalité aurait relié ce couple :

- `doc_type` identique (les types se mélangent rarement sans erreur de typage — cf. fiche).
- Champs textuels normalisés (`title_normalized`, éventuellement `container_title`).
- `pub_year` identique.
- Garde de sélectivité : longueur minimale de titre (écarte les titres génériques), présence d'un champ discriminant.

Le token est cette valeur sérialisée en chaîne (ex. `"<doc_type>|<title_normalized>|<pub_year>"`). Penser garde **par classe** : un token restreint à un `doc_type` est plus défensif qu'un token universel.

### 3. Inventorier et mesurer

SQL d'audit qui compte les blocs que le token regrouperait, et **mesure leur pureté**. Le contrôle de référence : comparer le recouvrement d'auteurs des couples que le token relierait à celui des couples reliés par DOI (vérité terrain « même œuvre »). Si le token n'est pas plus bruité que le DOI, il n'introduit pas d'excédent de collision.

Outils d'audit : [`audit_dedup_author_overlap`](../../interfaces/cli/oneshot/audit_dedup_author_overlap.py) (taux de non-recouvrement, token candidat vs DOI, par paire de sources) et [`audit_dedup_overmerge_examples`](../../interfaces/cli/oneshot/audit_dedup_overmerge_examples.py) (dump des couples suspects pour qualification manuelle).

### 4. Valider

Revue du résidu suspect (couples sans recouvrement d'auteurs). Trois sorties :

- **Excédent nul ou négligeable** vs la référence DOI → le token est mûr.
- **Excédent identifiable** → durcir la garde (longueur, restreindre les `doc_type`) et reprendre en 3.
- **Excédent irréductible par durcissement de la garde** (il faut comparer les listes d'auteurs pour trancher) → ce n'est pas un token ; le rapprochement passe par le mécanisme décrit dans la fiche chantier (hors playbook).

### 5. Matérialiser le token

#### 5.1 Projection

Dans [`domain/source_publications/keys.py`](../../domain/source_publications/keys.py) :

- ajouter le champ à `ConfirmationKeys` et son émission dans `tokens()` (`("<nom>", "<valeur>")`) ;
- le calculer dans `project_confirmation_keys`, avec sa garde de sélectivité.

La projection est l'**unique définition** de « quelles clés porte cette SP ». Un seuil de garde déclaré ici (ex. `_METADATA_BLOCK_MIN_TITLE_LENGTH`) est dupliqué côté SQL : le commenter des deux côtés (« garder synchrone »).

#### 5.2 Branche d'univers

Dans [`publications_reconciliation.py`](../../infrastructure/queries/pipeline/publications_reconciliation.py), ajouter une branche `UNION` à `_UNIVERSE_SQL` qui joint les SP partageant le token avec une SP dirty :

```sql
UNION
SELECT {_COLS.format(a="o")}
FROM dirty d
JOIN source_publications o ON <égalité du token entre o et d>
LEFT JOIN publications p ON p.id = o.publication_id
WHERE <garde sur d, identique à celle de la projection>
```

La branche doit ramener exactement les voisins que la projection relie : même critère d'égalité, même garde. C'est l'invariant à tenir entre `keys.py` (le clustering en mémoire) et le SQL (le voisinage chargé) ; un **test différentiel** le garde (cf. § 6).

### 6. Tests

- **Projection** ([`test_keys.py`](../../tests/unit/domain/source_publications/test_keys.py)) : une SP émet le token quand la garde passe, ne l'émet pas sinon ; cas-limites de la garde (longueur juste sous/au-dessus du seuil).
- **Univers + bout-en-bout** ([`test_reconcile_components.py`](../../tests/integration/pipeline/test_reconcile_components.py)) : deux SP au même token entrent dans le même univers et fusionnent ; deux DOI distincts co-bloqués ne fusionnent pas (cannot-link).
- **Différentiel anti-divergence** (`test_reconcile_components.py`) : étendre `TestUniverseMatchesPythonTokens` au token ajouté — semer des SP qui le portent (et les bords de garde : longueur juste sous/au-dessus du seuil) et vérifier que le voisinage SQL relie exactement les SP que les tokens Python relient. C'est ce qui garde la synchronisation `keys.py` ↔ SQL.

### 7. Rollout sur le stock

Un token neuf ne s'applique qu'aux SP `keys_dirty`. Pour matérialiser les fusions sur le stock existant, re-marquer les SP concernées :

- ciblé : [`redirty_publications --where "<condition du token>"`](../../interfaces/cli/maintenance/redirty_publications.py), puis `run_pipeline.py --only publications` ;
- total : `run_pipeline.py --only publications --rebuild-publications` (re-dirty complet → la réconciliation devient le clustering global).

Vérifier l'effet : reprendre le SQL d'audit de l'étape 3 — les blocs ciblés doivent être consolidés (une publication par bloc, hors séparations légitimes par DOI).

## Anti-patterns

- **Token laxiste sans garde de sélectivité** : un titre générique (« Foreword », « Introduction ») partagé par des œuvres distinctes fusionne à tort. La garde de longueur / la restriction de `doc_type` est la défense.
- **Critère d'égalité divergent entre `keys.py` et le SQL** : la branche d'univers ne ramène pas les voisins que le clustering relie (ou l'inverse) → fusions partielles ou manquées. Garder les deux strictement synchrones, et étendre le test différentiel (§ 6) au token ajouté pour verrouiller cette synchronisation.
- **Oublier le rollout** : sans re-dirty, le token ne s'applique qu'aux SP touchées par une (re-)normalisation ultérieure ; le stock existant reste non consolidé.

## Limites du périmètre

Les œuvres sans clé d'égalité fiable, dont le rapprochement exige de comparer les listes d'auteurs (types à titre faible, dépôts multiples au typage incertain), relèvent du mécanisme décrit dans la fiche chantier, pas d'un token. Les collisions résiduelles d'un token validé relèvent de la revue admin.
