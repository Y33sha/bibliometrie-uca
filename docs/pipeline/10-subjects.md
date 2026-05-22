# `subjects` : Sujets, mots-clés et co-occurrences

Deux étapes enchaînées, indissociables (l'une sans l'autre n'a pas de sens).

**Étape 1 — Ingestion.**
Pour chaque source : purge les liens `publication_subjects` existants pour cette source **sauf ceux marqués `rejected = TRUE`** (rejet manuel via l'UI à venir), puis ré-ingère les sujets/mots-clés des `source_publications` rattachées à une publication canonique. Dispatch par source dans `application/pipeline/subjects/ingest_<source>.py` ; un `SubjectCache` partagé évite les UPSERT répétés sur les sujets récurrents.

Le référentiel `subjects` n'est jamais purgé : un sujet peut rester orphelin si plus aucune publication ne le référence (historique des labels observés).

**Étape 2 — Co-occurrences.**
Recalcule depuis `publication_subjects` (en excluant les liens `rejected`) :
1. `subjects.usage_count` — nombre de publications distinctes par sujet.
2. `subject_cooccurrences` — paires de sujets co-présents sur une même publication, avec leur effectif. Filtré par `min_count >= 2` par défaut pour borner la cardinalité.

Idempotent : le résultat ne dépend que de l'état courant de `publication_subjects`.
