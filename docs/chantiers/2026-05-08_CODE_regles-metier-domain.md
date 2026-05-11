# Chantier — Formalisation des règles métier dans `domain/`
Commencé le 2026-05-05
Terminé le 2026-05-08

## Contexte

Plusieurs règles métier étaient dispersées dans les scripts du pipeline
(`application/pipeline/normalize/*.py`), parfois dupliquées, parfois
conditionnelles à un détail d'extraction d'une source précise.
Exemples :

- `doc_type = "thesis"` si la `source = theses.fr`, indépendamment du
  type prétendu par OpenAlex
- `doc_type = "memoir"` si OpenAlex annonce `dissertation` et l'URL
  est `dumas.*`
- `doc_type = "thesis" if dateSoutenance else "ongoing_thesis"` —
  dupliqué deux fois dans `normalize_theses.py`
- Détection de la source figshare/Zenodo via DOI : éparpillée
- Logique de rattachement personnes (matching ORCID/idHAL/idref →
  persons, gestion des conflits) : éclatée entre `application/persons.py`,
  les normalizers et les queries
- Règles de déduplication publications (matching DOI / NNT / titre) :
  partagées entre `find_or_create_publication`, `try_merge_by_doi` et
  les normalizers source par source

Le risque : règles invisibles aux tests unitaires de domaine (qui ne
voient que les fonctions pures relocalisées), divergences silencieuses
entre sources (ex. règle de doc_type différente selon le normalizer qui
écrit la publi en premier), évolutions difficiles (ajouter une règle
oblige à toucher N normalizers).

## Objectif

Rassembler dans `domain/` la logique métier pure existante,
indépendante des sources et de l'infrastructure. L'enrichissement
de la logique métier par de nouvelles règles (suppléments figshare,
Zenodo, DataCite suspects, révision de l'enum `doc_type`, etc.)
fait l'objet d'un chantier dédié [doc-types.md](doc-types.md).

**Définition de « pur »** : une fonction qui prend en arguments tout
ce dont elle a besoin (y compris les résultats de lookups SQL faits
par la couche application) et qui renvoie une décision (souvent un
value object). Les algorithmes de matching personnes, de
déduplication publications, d'arbitrage doc_type relèvent tous de ce
modèle — l'arbre de décision est pur, ce sont les SELECT en amont et
les INSERT/UPDATE en aval qui sont impurs et restent en
`application/`. Pattern déjà éprouvé sur
[`resolve_doi_conflict`](../../domain/publication.py).

Hypothèse de travail : les règles vivent dans `domain/` sous forme de
fonctions pures + dataclasses immuables, testées en unit pur (sans
BDD). Les normalizers et services applicatifs consomment ces fonctions
au lieu d'inliner les conditions.

## Périmètre fonctionnel

### Inclus

- **Inventaire** des règles métier inlinées dans
  `application/pipeline/normalize/*.py`,
  `application/persons.py`,
  `application/publications.py` et identification de celles qui sont
  pures (pas d'I/O, pas de cur, pas de repo).
- **Relocation** dans `domain/` des fonctions pures identifiées,
  regroupées par concept.
- **Tests unitaires purs** pour chaque règle relocalisée.
- **Refactor** des normalizers pour consommer les fonctions de
  `domain/` au lieu de leurs versions inlinées.

### Exclus

- Les **effets de bord** (SELECT/INSERT/UPDATE, gestion de
  transactions, appels API externes) restent en `application/` ou
  `infrastructure/`. Mais les **algorithmes de décision** qui les
  pilotent sont relocalisables : on extrait dans `domain/` la fonction
  pure qui prend en entrée le résultat des lookups (déjà faits par la
  couche application) et renvoie une décision (value object), puis
  l'application applique l'effet. Pattern de référence :
  [`resolve_doi_conflict`](../../domain/publication.py).
- **L'enrichissement de la logique métier par de nouvelles règles**
  (suppléments figshare, doc_types suspects, révision de l'enum…) :
  chantier dédié [doc-types.md](doc-types.md).
- **Refactor structurel des cascades** (matching personnes,
  déduplication / fusion publications) : 2 chantiers dédiés
  [decide-person-match.md](decide-person-match.md) et
  [dedup-fusion-publications.md](dedup-fusion-publications.md).

## Phases d'implémentation

### Phase 0 — Inventaire complet
- [x] Lister toutes les fonctions/blocs `application/pipeline/normalize/*`
      et `application/{persons,publications}.py` qui contiennent une
      règle métier (≠ orchestration).
- [x] Pour chaque règle, classer : (a) déjà pure → relocalisable
      directement, (b) non pure → décomposable en partie pure +
      effets, (c) intrinsèquement liée à la transaction → reste en
      `application/`.
- [x] Note de synthèse listant les fonctions à créer côté `domain/`.
- **Livrable** : fichier `docs/chantiers/regles-metier-inventaire.md`
  (ou section ajoutée à ce doc).

### Phase 1 — Relocations sans changement de comportement ✅
- [x] Déplacer `is_theses_fr_source` vers `domain/` (renommé
      `is_theses_fr_location` dans
      [`domain/sources/openalex.py`](../../domain/sources/openalex.py)).
- [x] Créer `theses_doc_type(date_soutenance)` (`derive_theses_doc_type`
      dans [`domain/sources/theses.py`](../../domain/sources/theses.py)),
      remplacer les 2 occurrences inlinées dans `normalize_theses.py`.
- [x] Créer la cascade d'override (`correct_openalex_doc_type` dans
      [`domain/sources/openalex.py`](../../domain/sources/openalex.py)),
      intégrant theses.fr → thesis et dissertation+dumas → memoir.
- [x] Tests unitaires purs (cf. `tests/unit/domain/sources/`).
- **Livrable** : fonctions relocalisées, comportement inchangé,
  tests verts. Phase achevée — plus de quarante items rapatriés au
  fil de l'eau dans `domain/{publications,persons,sources,dates,…}`.

### Phase 2 — Enrichissement par nouvelles règles → chantier dédié

Sort du périmètre de cette roadmap (qui est un pur rapatriement de
règles existantes). Repris dans [doc-types.md](doc-types.md) :
helpers de détection (`is_figshare_doi`, `is_datacite_doi`,
`is_supplement_title`), extension de `correct_openalex_doc_type`,
révision de l'enum `doc_type`, suppléments orphelins, reclassement
one-shot des cas existants.

### Phase 3 — Refactors structurels des cascades → 2 chantiers dédiés

Sortent également du périmètre du rapatriement pur — ce sont des
refactors de structure d'exécution avec dimension métier
(changements de logique). Repris dans :

- [decide-person-match.md](decide-person-match.md) — cascade unifiée
  de matching personnes (5 boucles → 1 boucle prefetch +
  `decide_person_match`).
- [dedup-fusion-publications.md](dedup-fusion-publications.md) —
  5 cascades de matching publications + règles de fusion multi-source
  + simplification du choix de cible de fusion.

## Décisions actées

1. **Granularité = dossier `domain/publications/` plutôt que fichiers
   plats à la racine de `domain/`**. Préfixe d'import explicite
   (`from domain.publications.dedup import …`) qui rend le rôle de
   chaque module immédiat à la lecture, et permet d'évoluer (sous-
   modules `domain/persons/`, `domain/structures/`) sans refactor
   plus tard. Coût : un `__init__.py` par dossier, négligeable.

## Liens

- [doc-types.md](doc-types.md) — chantier enfant : nouvelles règles
  doc_types (suppléments, suspects, révision enum)
- [decide-person-match.md](decide-person-match.md) — chantier enfant :
  cascade unifiée de matching personnes
- [dedup-fusion-publications.md](dedup-fusion-publications.md) —
  chantier enfant : déduplication / fusion publications
