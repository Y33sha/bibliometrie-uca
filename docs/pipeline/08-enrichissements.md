#  Enrichissements

## Pays des adresses

Phase `countries`: Associe des pays aux adresses pour permettre l'analyse des collaborations internationales. Trois étapes enchaînées :

1. **`interfaces/cli/pipeline/detect_address_countries.py`** : détection automatique du pays des adresses sans pays. Parse le dernier segment après la dernière virgule et le matche contre la table `country_name_forms` (276 formes, 140 pays, variantes anglais/français/codes ISO/abréviations WoS). Rapide et fiable.

2. **`interfaces/cli/pipeline/suggest_address_countries.py`** : pour les adresses restantes (pays absent du dernier segment), cherche une adresse similaire avec pays connu via LIKE sur le texte normalisé (index trigramme). Plus lent, résultats stockés dans `suggested_countries` pour validation manuelle via l'interface admin.

3. **`interfaces/cli/pipeline/refresh_publication_countries.py`** : recalcule `publications.countries` comme union des `source_publications.countries` de toutes les sources rattachées à chaque publication canonique.

## Sujets associés aux publications

Phase `subjects`: deux étapes enchaînées :

**Étape 1 — Ingestion.**
Pour chaque source : purge les liens `publication_subjects` existants pour cette source **sauf ceux marqués `rejected = TRUE`** (rejet manuel via l'UI à venir), puis ré-ingère les sujets/mots-clés des `source_publications` rattachées à une publication canonique. Dispatch par source dans `application/pipeline/subjects/ingest_<source>.py` ; un `SubjectCache` partagé évite les UPSERT répétés sur les sujets récurrents.

Le référentiel `subjects` n'est jamais purgé : un sujet peut rester orphelin si plus aucune publication ne le référence (historique des labels observés).

**Étape 2 — Co-occurrences.**
Recalcule depuis `publication_subjects` (en excluant les liens `rejected`) :
1. `subjects.usage_count` — nombre de publications distinctes par sujet.
2. `subject_cooccurrences` — paires de sujets co-présents sur une même publication, avec leur effectif. Filtré par `min_count >= 2` par défaut pour borner la cardinalité.

Idempotent : le résultat ne dépend que de l'état courant de `publication_subjects`.

##  Statut open access, APC

Phase `enrich`: exécutée uniquement en mode `full` :

| Script | Rôle |
|--------|------|
| `interfaces/cli/pipeline/enrich_oa_status.py` | Statut *open access* via API [Unpaywall](../glossaire#unpaywall) => souvent plus à jour que le statut renseigné dans les sources |
| `interfaces/cli/pipeline/enrich_journal_apc.py` | Montant [[apc|APC]] par revue via API OpenAlex Sources => **ne sert à rien pour l'instant**, voir si on garde ou pas |
