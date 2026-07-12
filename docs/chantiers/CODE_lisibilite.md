# Lisibilité

## Contexte

Objectif : réduire la complexité inutile et organiser la complexité nécessaire pour qu'un développeur extérieur comprenne le code rapidement. Le critère de réussite est qu'un dossier, un module ou une fonction s'explique à quelqu'un qui découvre le projet, sans détour par l'histoire du code.

Méthode : dossier par dossier, module par module, sans ordre imposé. Cette passe précède les analyses transversales par fonctionnalité ou par agrégat, qui viendront ensuite s'appuyer sur un terrain déjà assaini. Au fil des passes, les problèmes repérés mais laissés à plus tard sont notés dans le Phasage à l'emplacement qui correspond à leur place dans l'arborescence, pour ne pas les perdre.

Leviers mobilisés selon les cas : réécriture, suppression ou factorisation de code ; réorganisation de l'arborescence ; réécriture de docstrings et de commentaires. On supprime au passage, systématiquement, les retours à la ligne non sémantiques dans les docstrings (chaque paragraphe s'écrit d'un trait), qui gênent la lecture en écran divisé.

Garde-fous : import-linter (contrats de couches), mypy, ruff et pytest restent verts de bout en bout. Toute réorganisation d'arborescence est mécanique et réversible, guidée par ces filets.

## Décisions

### `application/` — aligner le sommet sur un seul axe

Le sommet de `application/` mélange deux axes de classification : des subdivisions techniques (`ports/`, `pipeline/`) et des dossiers par agrégat du domaine, tous de forme identique (`commands.py` pour les command handlers d'écriture API, `core.py` pour les briques transaction-agnostiques réutilisées par le pipeline, les CLI et l'API). On regroupe l'axe par-agrégat pour rendre le sommet homogène.

- Les neuf services d'agrégat — `addresses`, `authorships`, `config`, `journals`, `perimeters`, `persons`, `publications`, `publishers`, `structures` — passent sous `application/services/`. « Application services » est le terme consacré pour cette couche.
- `ports/` et `pipeline/` restent au sommet : ce sont des subdivisions techniques, et `pipeline` est un sous-système nommé à part entière, avec sa propre structure interne.
- `application/observability/` (vide) est supprimé.
- `application/audit.py` reste au sommet : c'est une préoccupation transverse et technique (journalisation des opérations destructives dans `audit_log`), pas un agrégat. Il est renommé `audit_log.py` pour lever la confusion avec les scripts d'inspection `interfaces/cli/oneshot/audit_*.py`, qui portent le même mot dans un sens différent (inspecter une donnée, non journaliser un événement).
- `application/publishers_enrichment/` est fondu dans l'agrégat publishers, sous `services/publishers/enrichment/`. Tous les CLI de maintenance délèguent leur logique à `application.<agrégat>` ; ce package à plat était le seul orphelin de ce patron. Son port `ports/publishers_enrichment.py` est conservé — dès que la logique vit dans `application/`, la couche interdit d'y toucher `infrastructure` en direct, donc le port n'est pas spéculatif — et sa place au sein de `ports/` se décide lors de la passe dédiée.

Cible :

```
application/
  ports/
  pipeline/
  services/
    addresses/  authorships/  config/  journals/  perimeters/
    persons/  publications/  publishers/  structures/
  audit_log.py
```

## Phasage

### Phase 1 - `application/`

Réorganisation du sommet :

- [x] Supprimer `observability/` (vide).
- [x] Créer `application/services/` et y déplacer les neuf agrégats (`ec5c7879`).
- [x] Renommer `audit.py` → `audit_log.py` (`5b96b61f`).
- [x] Fondre `publishers_enrichment/` dans `services/publishers/enrichment/` (`7a14b517`). Le port reste à `ports/publishers_enrichment.py` ; son placement se décide en 1.2.
- [ ] Passe docstrings du dossier : retours à la ligne non sémantiques, formulations, présent intemporel.

#### 1.1 - `application/pipeline`

16 phases (`PHASE_ORDER`) pour 14 dossiers, écart réconcilié :

- [x] `resolve_ra` sorti de `publishers_journals/resolve_doi_prefixes.py` vers `pipeline/resolve_ra/run.py` ; volet publisher isolé en `publishers_journals/resolve_publishers.py` (`bd6f5061`).
- [x] `cooccurrences` (sous-étape de `subjects`, absente de `PHASE_ORDER`) nichée en `pipeline/subjects/cooccurrences.py` (`b7dfbaa6`).
- `refresh_stale` et `refetch_truncated` restent dans `extract/` (opérations d'extraction) — cohérent, statu quo.
- [ ] `normalize/base.py` (et sans doute `extract/base.py`) : l'argparse (`--limit`/`--reset`/`--batch-size`, `run(argv)`) hérite des CLI de phase supprimés. Sans CLI pipeline, potentiellement vestigial — à vérifier au dossier `normalize`.
- [ ] Passe de fond du dossier (docstrings, lisibilité des modules).
- [ ] `pipeline/persons/` : la cascade `enforce → reset → match → create → populate → purge` concentre plusieurs points lourds (surtout `cascade.py`) — voir la fiche dédiée `CODE_phase-persons.md`.
- [ ] `pipeline/subjects/` : l'ingestion moissonne mots-clés libres (bruit) et concepts avec un modèle surdimensionné (`ontologies` codes/level/parent, colonne `score`) largement inexploité — voir la fiche dédiée `CODE_simplification-sujets.md`.
- [ ] Concurrence async des phases : `extract/refresh_stale` (pool de workers borné + compteur/commit sous `db_lock`), `oa_status` et `extract/refetch_truncated` (gather par paquets) sont sains. Reste `cross_imports/fetch_missing_hal` : gather global qui crée toutes les coroutines d'un coup (compteur-commit sous lock, donc correct, mais non borné) — à passer au gather par paquets lors de la passe `cross_imports`. (Basse priorité : correct, seulement non borné.)

#### 1.2 - `application/services`

- [ ] `persons/core.py` : `import_authenticated_orcids` est une opération d'ingestion (lecture d'ORCID authentifiés depuis une source externe pour les injecter) logée dans le référentiel d'écriture de l'agrégat, où elle détonne. À requalifier.
- [ ] `publishers/enrichment/` : les orchestrateurs parsent du JSON d'API brut (OpenAlex, Crossref, ROR) directement dans la couche application — d'où les exceptions `ruff C901` (une fonction à complexité 18) et l'override mypy `Any` (deux alias `dict[str, Any]` de fetchers, deux `dict` nus). Extraire le parsing vers des fonctions pures typées (patron `domain/sources/*_extract.py` déjà en place ailleurs) ; l'orchestrateur ne manipule plus que du typé, la complexité retombe sous le seuil et l'`Any` quitte la couche, ce qui dissout les deux exceptions.
- [ ] `publishers/enrichment/` : forme du sous-package — garder les trois modules par source, ou consolider (les autres services sont plats).
- [x] `publications/core.py` (`merge_publications`) : chemin de fusion et règle `absorb` — traité par la fiche dédiée `archived/2026-07-12_CODE_merge-publications.md`.

#### 1.3 - `application/ports`

- [ ] Placement du port `publishers_enrichment.py`, aujourd'hui à plat sous `ports/` (comme `config.py`). Sa place définitive se tranche en réorganisant `ports/`.
- [ ] `ports/pipeline/enrich.py` (`EnrichQueries`) : port grab-bag hérité de la phase monolithique `enrich`, depuis scindée en `oa_status` + `publishers_journals`. Il regroupe deux familles de requêtes disjointes (publications OA vs journaux/DOAJ) ; chaque phase tire des méthodes qu'elle n'utilise pas (violation d'*Interface Segregation*). À scinder en deux ports étroits — l'impl `PgEnrichQueries` implémentant les deux, ou se scindant elle aussi. Le nom `EnrichQueries` disparaît avec.

### Phase 2 - `infrastructure/`

### Phase 3 - `interfaces/`

- [ ] CLI `maintenance/` : coquille-ification. `enrich_publishers` séquence ses trois étapes dans son `main()` au lieu de déléguer en un appel à un orchestrateur applicatif, contrairement à ses voisins.
- [ ] Passe des CLI `maintenance/` et `oneshot/`.

### Phase 4 - `domain/`

## Questions ouvertes

- **Style de logging incohérent** (transverse). f-string vs `%`-lazy : ~79 occurrences sur 22 fichiers du seul `application/pipeline`, motif probablement plus large. Faible nuisance (le logging de progression et de bilan est une observabilité légitime, feeding `pipeline.log` que l'UI admin ressort par phase). Ne vaut le coup que couplé à un durcissement lint (règles ruff `G`/`LOG`) qui verrouille le style. Hors périmètre de ce chantier ; éventuel chantier dédié.
