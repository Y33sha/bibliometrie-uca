# Chantier — Scinder `source_authorships` (identité ⊥ liaison)

Décomposer `source_authorships` en deux tables, **à comportement strictement constant** : une table des **identités d'auteur** (forme de nom normalisée + identifiants, dédupliquées) et la table de **liaison** allégée (une FK vers l'identité en remplacement des colonnes déménagées). C'est une pure correction de forme normale : les colonnes d'identification dépendent de *qui est l'auteur*, pas de la clé de liaison `(source, source_publication_id, author_position)` ; les stocker sur la liaison est une dépendance partielle, d'où une répétition d'un facteur ≈ 25. La cible restaure une symétrie déjà à demi-écrite dans le schéma : `addresses` est la table d'identités-source des structures (dédup de chaînes brutes alimentant le matching) ; les personnes n'ont pas d'équivalent, leur identité étant diluée dans la liaison.

Le périmètre se limite au **déplacement des colonnes** : aucun changement de logique de matching, de valeur produite, ni de contrat de lecture (au résultat près, identique). Les gains de performance et les nouveaux diagnostics que la table débloque sont listés en **Suites possibles** et relèvent de chantiers ultérieurs, sur base stable.

## Contexte

### La table et sa redondance

`source_authorships` porte une ligne par authorship source : la relation (`source`, `source_publication_id`, `author_position`, `in_perimeter`, `is_corresponding`, `roles`, `countries`, `authorship_id`, `person_id`) et l'identification de l'auteur (`author_name_normalized`, `raw_author_name`, `person_identifiers`). Les colonnes d'identification sont massivement répétées : une même personne y figure en moyenne une cinquantaine de fois, autant que de signatures qu'elle a déposées.

### Mesures sur une base de travail (≈ 16,75 M lignes ; ≈ 19 M en production)

La table pèse environ 3,3 Go : ≈ 2,58 Go de heap et ≈ 0,74 Go d'index, dont la clé primaire (≈ 0,36 Go) et l'unique `(source_publication_id, author_position)` (≈ 0,36 Go) à eux seuls. Les identités distinctes au sens `(author_name_normalized, person_identifiers)` sont ≈ 645 000, soit un facteur de répétition d'environ 25. Le `person_identifiers` est `NULL` sur ≈ 64 % des lignes.

## Décisions

1. **Deux tables.** `author_identifying_keys` (`id`, `author_name_normalized`, `person_identifiers`) dédupliquée, unique sur `(author_name_normalized, person_identifiers)`. `source_authorships` perd `author_name_normalized` et `person_identifiers`, gagne `identity_id` (FK NOT NULL → `author_identifying_keys`), et garde tout le reste inchangé (`raw_author_name`, `person_id`, `authorship_id`, `in_perimeter`, `author_position`, `is_corresponding`, `roles`, `countries`, `source_structures`).

2. **Clé d'identité = `(author_name_normalized, person_identifiers)`.** Le nom **normalisé** déménage ; le **`raw_author_name` reste sur la liaison** (trace brute par signature). La dédup se fait sur le nom normalisé (déjà le grain du matching) : deux `raw` distincts qui normalisent pareil et portent les mêmes identifiants collapsent en une identité. Le marquage `_dubious` fait partie de la clé (deux valeurs d'identifiant distinctes = deux identités), donc reste invisible au matching comme aujourd'hui.

3. **Relation N:1 : une FK, pas de table de liaison.** Une signature porte exactement une identité — simple FK. Plus simple que le cas des adresses (N:M, via `source_authorship_addresses`), où une signature peut porter plusieurs affiliations.

4. **Pas de `person_id` sur l'identité.** À comportement constant, le matching reste par signature et écrit `person_id` sur la liaison, au même endroit et au même moment. Une colonne `person_id` sur l'identité serait morte : elle n'apparaît qu'avec l'optimisation du matching (Suites possibles), pas ici.

## Gains et coûts

**Gains**
- **Place** : ≈ 1 Go (≈ 30 %) une fois la table réécrite/repackée — les colonnes creuses (identifiants absents sur 64 % des lignes) cessent d'être répétées. Modéré mais réel sur une table de cette taille.
- **Lisibilité du schéma** : l'identité d'auteur devient une entité nommée, symétrique d'`addresses` ; la liaison n'est plus qu'une liaison.
- **Débloque la suite** : la table dédupliquée est le préalable au matching par identité et aux diagnostics de dédoublonnage (cf. Suites possibles).

**Coûts et risques** (hors charge de travail)
- **Complexité payée maintenant, bénéfice différé.** Le refactor seul ajoute des pièces mobiles (deux tables, FK, contrainte d'unicité, GC des identités orphelines, jointures chez tous les lecteurs) pour un retour immédiat modeste (place + lisibilité de schéma). Le gros du bénéfice (perf du matching, diagnostics) n'arrive qu'aux chantiers suivants. Fait sens comme fondation qu'on **construira**, moins comme fin en soi.
- **Jointure partout sur le read-path.** Chaque lecture de `author_name_normalized` / `person_identifiers` gagne un `JOIN author_identifying_keys` : SQL plus verbeux (contrepoids partiel au gain de lisibilité) et coût de jointure sur les chemins chauds (refresh de matview, audits, fetch du matching). Jointure vers une table de ~645 k lignes : hash join bon marché, mais non nul.
- **Migration lourde et sensible.** Backfill dédupliqué de 17-19 M lignes vers ~645 k identités + pose de la FK, puis `DROP` des deux colonnes (métadonnée immédiate, mais espace récupéré seulement au `VACUUM FULL`/repack). Un bug de dédup ou de gestion du NULL fausserait le grain des identités. Ponctuel, testable sur branche, mais réel.
- **Un invariant de plus à tenir.** Toute écriture de `source_authorships` doit poser `identity_id` ; toute identité sans référent doit être ramassée. Le modèle mono-table actuel a moins de points de défaillance futurs.
- **Une signature n'est plus un enregistrement autonome.** Débogage et SQL ad hoc joignent deux tables au lieu de lire une ligne.

Aucun **coût comportemental** : à migration correcte, les mêmes lignes produisent les mêmes `person_id` et les mêmes lectures (au résultat près, identiques).

## Phasage

### Phase 1 — Instruction de l'impact

- [ ] Tracer exhaustivement les lecteurs/écrivains de `author_name_normalized` et `person_identifiers` (matching, matview `person_identifier_keys`, API/admin, `name_forms.py`, oneshots d'audit/remédiation, frontend — largement insulé, il lit la table canonique `person_identifiers`). Chaque lecture devient une jointure.
- [ ] Trancher les détails de modélisation : NULL des identifiants (`NULLS NOT DISTINCT` sur l'unique, ou stocker `'{}'`) ; stratégie de GC des identités orphelines (patron `addresses`).

### Phase 2 — Schéma et migration

- [ ] Table `author_identifying_keys` + unique sur la clé d'identité.
- [ ] `source_authorships` : colonne `identity_id` (nullable), backfill dédupliqué batché, passage NOT NULL + FK, `DROP` de `author_name_normalized` et `person_identifiers`.

### Phase 3 — Bascule normalize

- [ ] `normalize` : upsert de l'identité (dédup par clé) + pose de `identity_id`, sur le patron déjà éprouvé de la dédup `addresses` (`md5(raw_text)` → `source_authorship_addresses`).

### Phase 4 — Réécriture des lecteurs

- [ ] Matching (fetch de la phase persons) : joindre l'identité, cascade Python inchangée.
- [ ] Matview `person_identifier_keys` : reconstruite en `source_authorships` (⟶ `person_id`) ⋈ `author_identifying_keys` (⟶ identifiants).
- [ ] API / admin / oneshots / `name_forms.py` : jointure à la place de la lecture inline.
- [ ] Tests de non-régression : mêmes rattachements, mêmes lectures qu'avant.

## Suites possibles (hors périmètre, chantiers ultérieurs)

Ce que la table d'identités débloque, une fois le refactor stable :

- **Matching par identité** : calculer les barreaux sans contexte une fois par identité distincte (~645 k) au lieu d'une fois par signature (17-19 M).
- **Double autorité du `person_id`** : verdict recalculable sur l'identité + autorité sur la liaison (le `cross_source` et le rejet restant contextuels).
- **Diagnostics de dédoublonnage** : divergence entre verdict par identifiant et verdict par nom ; identifiant partagé entre personnes (déjà couvert par `person_identifier_keys`).
- **Résolution nominale ordre-indépendante** : traiter la compatibilité initiale/plein (« J. Martin » / « Jean Martin ») en batch sur l'ensemble des identités, corrigeant une source de doublons sensible à l'ordre d'arrivée.

## Questions ouvertes

- **Gain de place réel en production** (≈ 19 M de lignes) à mesurer avant migration.

## Liens

- Tables : `source_authorships`, `source_authorship_addresses`, `authorships`, `persons`, `person_name_forms`, `person_identifiers`.
- Phase personnes : `application/pipeline/persons/create_persons_from_source_authorships.py`.
- Analogie structure : phase `affiliations`, `addresses` → `address_structures`.
- Chantier lié : [DATA_personnes-dedoublonnage-assiste](DATA_personnes-dedoublonnage-assiste.md).
