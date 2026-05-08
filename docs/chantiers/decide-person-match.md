# Chantier — Cascade unifiée de matching personnes (`decide_person_match`)

Rassemblement préalable des éléments. Structure (contexte, décisions,
phasage) à formaliser au démarrage du chantier.

## Périmètre

Le pipeline persons (`create_persons_from_source_authorships.py`)
exécute la cascade de matching personne en **5 boucles séquentielles
indépendantes** sur `all_authorships` — chaque étape skip ce qui est
déjà rattaché par les étapes précédentes. La hiérarchie de fiabilité
n'est pas exprimée comme une décision pure unique mais résulte
implicitement de l'ordre des appels.

Deux dimensions imbriquées :

- **Refactorisation** : passer de 5 boucles à 1 boucle qui prefetch
  les lookups + appelle `decide_person_match`. La cascade devient
  testable hors BDD avec des fixtures simples.
- **Changement de logique** : interroger l'ordre actuel (compte HAL
  avant ORCID Crossref ?), gérer les méga-papers, formaliser les
  invariants (statuts `pending`/`confirmed`/`rejected` côté
  `person_identifiers`).

## Item concerné

### `contrat de la cascade globale`
- **localisation** :
  `application/pipeline/persons/create_persons_from_source_authorships.py:1-33`
  (docstring) + `:389-420` (orchestrateur)
- **description** : Hiérarchie de fiabilité (compte HAL > cross-source
  > IdRef > ORCID > nom), aujourd'hui dispersée dans 5 fonctions
  `step0_hal_accounts`, `step1_cross_source`, `step1b_idref`,
  `step2_orcid`, `step3_name_forms`.
- **destination** : `domain/persons/matching.py` →
  `decide_person_match(*, hal_account_match, cross_source_match,
  idref_match, orcid_match, name_form_outcome) -> PersonMatchDecision`.

## État réel du code (5 boucles séquentielles)

```python
# orchestrateur l. 389-420
s0 = step0_hal_accounts(...)
s1 = step1_cross_source(..., linked_index, ...)
s1b = step1b_idref(...)
s2 = step2_orcid(...)
s3 = step3_name_forms(...)
```

Chaque step itère sur `all_authorships`, skip ce qui est dans
`linked_ids`, fait son lookup spécifique, ajoute à `linked_ids` si
match.

## Briques déjà en place côté domain

Les 3 sous-décisions partielles existent déjà dans
[`domain/persons/matching.py`](../../domain/persons/matching.py) :

- `decide_cross_source_match(authorship_source, last_norm, first_norm, candidates)`
  — étape 1
- `decide_match_by_identifier(value, identifier_map)`
  — étapes 1b (IdRef) et 2 (ORCID)
- `decide_name_form_outcome(person_ids, allow_create)`
  — étape 3

Manque uniquement `decide_person_match` qui orchestre les 4 lookups
(hal_account + cross_source + idref/orcid via decide_match_by_identifier
+ name_form_outcome) en une décision unique.

## Hiérarchie de fiabilité — à formaliser et discuter

Hiérarchie actuelle (de la plus fiable à la moins) :

1. **Compte HAL** (`hal_person_id`) : compte créé par l'auteur ou un
   curateur ; quelques erreurs possibles mais globalement fiable.
2. **Cross-source par publication × position auteur** : on relie une
   signature à la `person_id` connue d'une autre source à la même
   `(publication_id, author_position)`. Garde-fou `names_compatible`.
3. **IdRef** : PPN SUDOC (`person_identifiers`).
4. **ORCID** issu de `person_identifiers`.
5. **Lookup `person_name_forms`** : matching par nom normalisé.
6. **Création** si rien ne matche.

**Hiérarchie proposée (regles-metier-domain.md) — à arbitrer** :

1. **ORCID Crossref** : un ORCID dans Crossref vient de l'éditeur,
   directement de l'auteur lors de la soumission. Le plus fiable. (À
   ajouter en tête, pas encore implémenté).
2. **Compte HAL** (`hal_person_id`).
3. **IdRef / ORCID provenant d'autres sources** (HAL hors compte, OA,
   WoS) : les ORCID OA/WoS viennent souvent d'un matching par nom
   côté éditeur de la source, donc régulièrement fautifs. À surveiller
   — voire à retirer si ratio bruit/signal défavorable.
4. **Matching par nom**.

## Question ouverte — matching par publication cross-source

Actuellement utilisé en complément du matching par nom pour
désambiguïser : « on relie cette signature à la person X parce qu'elle
est déjà reliée à la même publication, en même position auteur, dans
une autre source ». Pose problème sur les méga-papers (consortiums,
papers à 100+ auteurs) avec des désalignements + homonymes
"initiale+nom" fréquents.

À réexaminer pendant ce chantier : maintien tel quel, restriction à
un seuil max d'auteurs (ex. ≤ 30 auteurs), ou suppression. Décision à
prendre après mesure du ratio matchings utiles / faux positifs sur
les cas méga-paper.

### Sous-point : seuil méga-paper

Court-circuit à ajouter sur `decide_cross_source_match` si le
`source_publication` a plus de N auteurs (constante
`MAX_AUTHORS_CROSS_SOURCE`, à harmoniser avec `MAX_AUTHORS_CONFLICT`
côté `TODO_LAURA.md`). Renvoie `None` direct (pas de cross-source)
au-delà du seuil.

Coût : ajout d'un argument `total_author_count` à
`decide_cross_source_match` + compute du count côté caller (depuis le
prefetch ou une query supplémentaire).

## À rapatrier de l'application

Au-delà du `decide_person_match` lui-même :

- Règles d'arbitrage (ordre des sources d'identité, comportement en
  cas d'ambiguïté).
- Gestion des statuts `pending` / `confirmed` / `rejected` côté
  `person_identifiers`.
- Invariants métier (ex. « jamais de fusion automatique entre deux
  persons ayant chacune un `persons_rh` distinct » — déjà appliqué
  côté API et scripts via `check_can_merge_persons`, à formaliser
  comme partie de la cascade si pertinent).

## Signature suggérée

```python
@dataclass(frozen=True)
class PersonMatchDecision:
    action: Literal["match", "create", "skip"]
    person_id: int | None = None
    reason: str = ""
    # 'orcid_crossref' | 'hal_account' | 'cross_source' |
    # 'idref' | 'orcid' | 'single_name' | 'name_ambiguous' | …

def decide_person_match(
    *,
    hal_account_match: int | None,
    cross_source_match: int | None,
    idref_match: int | None,
    orcid_match: int | None,
    name_form_outcome: NameFormDecision,
) -> PersonMatchDecision:
    """Cascade de matching personne, du signal le plus fiable au moins
    fiable. Pure, testable sans BDD."""
```

Côté application : 1 boucle qui prefetch les 4 maps de lookup, calcule
chaque match par authorship, appelle `decide_person_match`, applique
l'effet selon la décision (INSERT person + identifiers, ou attache
person_id existant, ou skip).

## Plan de chantier (résumé)

1. Implémenter `decide_person_match` en domain en s'appuyant sur les
   3 sous-décisions déjà en place.
2. Restructurer `create_persons_from_source_authorships` : passer de
   5 boucles à 1 boucle avec prefetch des 4 maps + appel
   `decide_person_match`.
3. Décider du sort du matching cross-source (seuil, suppression…).
4. Surveiller la perf — un seul prefetch global vs lookups par étape.
5. Tests unitaires sur la cascade (toutes les branches), tests
   d'intégration adaptés.

## Liens

- Pattern de référence (décision pure déjà en domain) :
  [`resolve_doi_conflict`](../../domain/publication.py#L562)
- Briques sous-décisions déjà migrées :
  [`domain/persons/matching.py`](../../domain/persons/matching.py)
