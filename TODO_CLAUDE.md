# Notes techniques et idées (Claude)

## Page admin "Configuration"

**Idée** : externaliser dans une page admin les paramètres actuellement codés dans `config/settings.py`, pour pouvoir les modifier sans toucher au code ni redéployer.

**Paramètres candidats :**
- Années de requête (actuellement `HAL["years"]`, `OPENALEX["years"]`, etc.)
- Collections HAL à requêter (actuellement `HAL["collections"]`)
- Structures à requêter par source (portail HAL, institutions OpenAlex, orga WoS)
- Périmètres UCA (étroit vs large : structures `est_tutelle_de` vs `est_partenaire_de`)

**Implémentation envisagée :**
- Backend : table `config` en base (clé/valeur JSONB), lue par les scripts au démarrage à la place de `settings.py`
- API : `GET /api/config`, `PUT /api/config/:key`
- Frontend : page `/admin/config` avec formulaires par section
- Les scripts chargeraient la config depuis la base avec fallback sur `settings.py` (progressivité)

**Avantages :**
- Pas besoin d'accès au code pour ajuster un paramètre
- Traçabilité (qui a changé quoi, quand)
- S'inscrit dans la logique d'urbanisation : la configuration est une donnée, pas du code

**Note :** `config/settings.py` contient actuellement un mélange de paramètres configurables (années, formes de noms par source) et de données déjà en base (intitulés collections HAL des labos). À rationaliser lors de la mise en place de la page admin config.

## Prévention des fusions erronées (publications)

`split_bad_merges.py` a été supprimé — il défusionnait a posteriori des publications mal fusionnées. Le vrai problème est en amont : `services/publications.py` fusionne par DOI sans vérifier la compatibilité.

**Cas connu :** ouvrage + chapitre avec le même DOI (DOI de l'ouvrage attribué au chapitre). Contrainte unique sur `lower(doi)` → impossible d'avoir les deux. Il faudrait supprimer le DOI sur l'un des deux (celui qui est en fait le chapitre) et maintenir les deux publications distinctes.

**À implémenter :** garde-fous dans `find_or_create()` ou en amont dans les normalizers, pour détecter les cas où un DOI identique recouvre des publications de types incompatibles (livre vs chapitre, article vs erratum).

**Note :** les garde-fous chapitre/ouvrage sont désormais implémentés dans `find_or_create()` (testés dans `test_dedup_publications.py`).

## Tests d'idempotence du pipeline

Vérifier que lancer deux fois de suite chaque phase du pipeline produit le même résultat (pas de doublons de personnes, pas d'authorships rattachées en double, pas de publications créées en double).

**Scénario type :**
1. Insérer des données de test dans le staging
2. Lancer la phase (ex: `create_persons`)
3. Compter les résultats (nb personnes, nb authorships rattachées)
4. Relancer la même phase
5. Vérifier que les compteurs n'ont pas bougé

**Phases à tester en priorité :**
- `create_persons_from_source_authorships.py` (risque de créer des personnes en double)
- `build_authorships.py` (risque de doublons dans la table authorships)
- `normalize_*.py` (risque de doublons de documents/auteurs)

## Automatisation de l'attribution des pays aux adresses

Actuellement, `addresses.countries` est assigné manuellement via l'interface admin. Il faudrait une couche d'automatisation a minima pour les adresses qui se terminent par un nom de pays.

**Implémentation envisagée :**
- Nouvelle table `country_name_forms` (formes de noms de pays dans différentes langues)
- Script de parsing des adresses pour détecter les name_forms et assigner automatiquement des pays
- Les attributions auto seraient en `suggested_countries`, validables manuellement

**Note :** chantier conséquent, à planifier séparément.

## Uniformisation compatibilité de noms (Python vs SQL)

Les fonctions de compatibilité de noms existent en deux versions :
- Python : `utils/names.py` (`names_compatible`, `first_names_compatible`, etc.)
- SQL : requêtes dans `backend/routers/admin_person_duplicates.py` (`PERSON_DUP_QUERIES`)

Les deux implémentent la même logique mais indépendamment. Idéalement, le backend devrait utiliser les fonctions Python de `utils/names.py` pour la détection de doublons. Mais les requêtes SQL sont plus performantes pour le matching en masse (JOIN direct en base). À réévaluer si la logique diverge.
