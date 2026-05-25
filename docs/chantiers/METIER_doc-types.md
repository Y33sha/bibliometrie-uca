# Chantier — Types de documents : enum, mappings, règles suspects

Issu de [`regles-metier-domain.md`](regles-metier-domain.md) (Phase 2
historique) + items TODO_LAURA « Types de documents : fixer l'enum et
le mapping, algo de résolution de conflits ».

## Contexte

Trigger initial : sondage 2026-05-05 sur les ~300 publis avec DOI
figshare. **229 sont des « Additional file X of … »** (suppléments PDF
figures/tableaux), classées « article » par OpenAlex donc remontées
comme telles dans la BDD UCA. La règle qui aurait dû les écarter
n'existe nulle part — il faut un endroit propre où l'écrire et la
tester.

Autres patterns problématiques constatés :

- DOI figshare collection (`10.6084/m9.figshare.c.*`) : ce sont des
  bundles, pas la publi canonique.
- DOI Zenodo (`10.5281/zenodo.*`) + titre suspect (« Supplementary
  materials… », « Données supplémentaires… »).
- DOI DataCite (au sens RA) + `doc_type=article` mais titre suspect.
- Publications de type « article » avec source OpenAlex et revue
  inconnue : généralement des préprints sur des archives en ligne, à
  corriger.
- Enum `doc_type` à revoir : correction/erratum/corrigendum,
  compte-rendu (= « autre » sur HAL), review (= book review ou revue
  de la littérature ?), posters (ne pas fusionner avec conf si même
  DOI ?), preprints en accès gold selon OpenAlex, data papers.
- Types WoS « composites » : étudier, voir si ça représente des
  types/sous-types comme dans HAL.

145/229 cas figshare au 2026-05-05 sont des suppléments **orphelins**
(le parent n'est pas en BDD).

## Périmètre

### Inclus

- **Helpers de détection** par préfixe DOI / pattern titre :
  - `is_figshare_doi(doi)` (préfixe `10.6084/m9.figshare.*` et
    collections `10.6084/m9.figshare.c.*`)
  - `is_datacite_doi(doi)` (par préfixe — partiellement couvert par
    `doi_prefixes` après chantier
    [doi-ra-datacite](doi-ra-datacite.md), mais une fonction pure de
    détection prefix → RA reste utile pour les règles qui s'appliquent
    avant la table `doi_prefixes`)
  - `is_supplement_title(title)` : pattern « Additional file X of … »,
    « Supplementary material(s) for … », « Données supplémentaires
    de … », « Supporting information for … ». Multi-langue (FR + EN),
    regex compilées en module-level.
- **Cascade `correct_openalex_doc_type`** étendue : aujourd'hui (cf.
  [`domain/sources/openalex.py:272`](../../domain/sources/openalex.py))
  elle gère theses.fr → `thesis` et dumas → `memoir`. À étendre avec
  la cascade « DOI figshare/Zenodo/DataCite + titre supplément →
  doc_type='other' ».
- **Reclassement préprints article OA inconnu** : règle décisionnelle
  pour repérer les préprints classés « article » par OpenAlex avec
  une revue inconnue.
- **Révision de l'enum `doc_type`** :
  - correction/erratum/corrigendum
  - compte-rendu (= « autre » sur HAL ?)
  - review (= book review ou revue de la littérature ?)
  - posters (ne pas fusionner avec conf si même DOI)
  - preprints OA gold (cas suspect)
  - data papers
- **Types WoS composites** : étudier, voir si ça représente des
  types/sous-types comme dans HAL.
- **Détection des suppléments orphelins** (145 cas figshare au
  2026-05-05 dont le parent n'est pas en BDD) → règle d'élimination
  ou marqueur explicite (à arbitrer).
- **Reclassement one-shot** des cas existants en fin de chantier
  (SQL aligné sur les nouvelles règles + vérification au prochain
  run pipeline).

### Exclus

- L'ingestion DataCite proprement dite : couverte par
  [doi-ra-datacite.md](doi-ra-datacite.md). Ce chantier-ci se contente
  d'utiliser les helpers/données qui en sortent.
- Modifications du schéma SQL au-delà de l'enum `doc_type` (ex. colonne
  `publications.doc_type_overridden`) : décisions au cas par cas.

## Décisions actées (héritées)

1. **Détection figshare/Zenodo : hardcoded au démarrage, via
   `doi_prefixes` quand le chantier
   [doi-ra-datacite](doi-ra-datacite.md) aura abouti**. Helpers
   `is_figshare_doi`/`is_zenodo_doi` à préfixe en dur (suffisant pour
   les patterns connus). Si après doi-ra-datacite on constate que
   `doi_prefixes` couvre l'intégralité des cas réels, on migrera
   entièrement et on retirera les helpers préfixe. Pas de double
   path à maintenir intentionnellement — la migration est un
   objectif, pas un fallback permanent.
2. **Reclassement one-shot des cas existants** en fin de chantier.
   SQL aligné sur la nouvelle règle, suivi d'une passe de
   vérification au prochain run pipeline pour s'assurer que la
   cascade en `domain/` produirait le même résultat.

## Open questions

- **Suppléments orphelins** (145 cas figshare au 2026-05-05 dont le
  parent n'est pas en BDD) : à sonder au cas par cas. Hypothèses à
  tester : (a) parent présent avec un titre légèrement différent
  (matching à raffiner), (b) parent réellement absent et c'est
  correct (publi non-UCA), (c) parent réellement absent à tort (à
  retrouver). Cette question rejoint un futur chantier de
  modélisation des **relations entre publications** (parent ↔
  supplément, ouvrage ↔ chapitre, version ↔ révision, …) — à n'ouvrir
  qu'une fois ce chantier-ci abouti.

## Risques

- **Performance** : les regex de `is_supplement_title` doivent rester
  O(1) par titre — patterns compilés en module-level.
- **Coordination avec [doi-ra-datacite](doi-ra-datacite.md)** : la
  détection RA peut bénéficier de `doi_prefixes` plutôt que d'un
  hardcode Zenodo + figshare. À séquencer après doi-ra-datacite
  phase 1, ou à mener en parallèle avec un fallback hardcodé.
- **Compatibilité avec
  [`refresh_from_sources`](../../application/publications.py)** :
  cette fonction recalcule le `doc_type` canonique depuis les sources
  (priorité theses.fr > ScanR > HAL > OpenAlex > WoS). Une nouvelle
  règle « doc_type suspect → other » doit s'appliquer **après** la
  sélection de la source prioritaire, ou être encodée dans le mapping
  de chaque source. À choisir : règle au niveau source (chaque
  normalizer corrige son propre `source_publications.doc_type`) ou
  règle au niveau canonique (`refresh_from_sources` applique
  l'override). Plus propre = au niveau source pour ne pas perdre
  l'info brute.

## Liens

- [regles-metier-domain.md](regles-metier-domain.md) — chantier parent
  (rapatriement des règles existantes vers `domain/`)
- [doi-ra-datacite.md](doi-ra-datacite.md) — chantier jumeau,
  prérequis pour détection RA via préfixe
- [crossref.md](crossref.md) — architecture CrossRef ingest
- État actuel : [`domain/sources/openalex.py`](../../domain/sources/openalex.py)
  (`correct_openalex_doc_type`),
  [`domain/doc_types.py`](../../domain/doc_types.py)
  (`map_doc_type` + `_SOURCE_MAPS`),
  [`application/publications.py`](../../application/publications.py)
  (`refresh_from_sources`)


## idées à intégrer
- book reviews: trouver critères titre pour détecter (ISBN; titre terminé par "année, nombre de pages")
- type "media" ou "presse"
- conf, conference paper, proceedings: clarifier
- détecter les patterns d'incohérence les plus fréquents
- type "données additionnelles?"

## Règles à mettre en place
* Toutes les revues contenant les mots "conference", "symposium", "proceedings", "lecture notes" sont de type "proceedings".
* Toutes les publications dans une revue de type "proceedings" sont des "conference papers".
* Toutes les publications dans une revue de type "media" sont des "interventions médias" (type à créer)
* Toutes les publications commençant par "Interview" sont de type "intervention média" (? vérifier)
* Toutes les publications commençant par "Erratum", "Errata", "Corrigendum" sont de type "erratum".
