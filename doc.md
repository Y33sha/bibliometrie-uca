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
