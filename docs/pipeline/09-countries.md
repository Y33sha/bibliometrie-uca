# `countries` : Pays des publications

Trois étapes enchaînées :

1. **`interfaces/cli/pipeline/detect_address_countries.py`** : détection automatique du pays des adresses sans pays. Parse le dernier segment après la dernière virgule et le matche contre la table `country_name_forms` (276 formes, 140 pays, variantes anglais/français/codes ISO/abréviations WoS). Rapide et fiable.

2. **`interfaces/cli/pipeline/suggest_address_countries.py`** : pour les adresses restantes (pays absent du dernier segment), cherche une adresse similaire avec pays connu via LIKE sur le texte normalisé (index trigramme). Plus lent, résultats stockés dans `suggested_countries` pour validation manuelle via l'interface admin.

3. **`interfaces/cli/pipeline/refresh_publication_countries.py`** : recalcule `publications.countries` comme union des `source_publications.countries` de toutes les sources rattachées à chaque publication canonique.
