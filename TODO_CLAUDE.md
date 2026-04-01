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
