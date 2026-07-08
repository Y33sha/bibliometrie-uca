#  Enrichissements

*À jour le 2026-06-30.*

## Pays des adresses

Phase `countries`: Associe des pays aux adresses pour permettre l'analyse des collaborations internationales. Quatre étapes enchaînées :

1. **`application/pipeline/countries/detect_by_country_name.py`** : détection du pays des adresses sans pays, par **nom de pays**. Parse le dernier segment après la dernière virgule et le matche contre les noms de pays de `place_name_forms` (`kind = 'country'` : variantes anglais/français, codes ISO, abréviations WoS). Rapide et fiable.

2. **`application/pipeline/countries/detect_by_place_name.py`** : pour les adresses restées sans pays (aucun nom de pays explicite), détection par **nom de lieu**. Cherche dans tout le texte de l'adresse — pas seulement le dernier segment — les noms d'institutions et de villes connus (`place_name_forms`, `kind IN ('institution', 'city')`), chacun rattaché à un pays, via un automate Aho-Corasick. Le pays n'est posé que si les lieux trouvés désignent un pays unique.

3. **`application/pipeline/countries/suggest_countries.py`** : pour les adresses encore sans pays, cherche dans l'ensemble des adresses *au pays connu* celles qui contiennent l'adresse cible comme sous-chaîne de leur texte normalisé, et retient le ou les pays les plus fréquents parmi elles. Le pool est balayé en un seul passage (automate Aho-Corasick) ; les pays proposés sont stockés dans `suggested_countries` pour validation manuelle via l'interface admin.

4. **`application/pipeline/countries/refresh_publication_countries.py`** : recalcule `publications.countries` comme union des `source_publications.countries` de toutes les sources rattachées à chaque publication canonique.

## Sujets

Phase `subjects`: deux étapes enchaînées :

**Étape 1 — Ingestion.**
Incrémentale et centrée publication : seules les publications dont le contenu canonique a changé depuis leur dernière ingestion sont retraitées. Pour ces publications, les liens `publication_subjects` existants sont purgés (**sauf ceux marqués `rejected = TRUE`** — rejet manuel via l'UI à venir), puis les sujets/mots-clés de leurs `source_publications` sont ré-ingérés, source par source. Dispatch dans `application/pipeline/subjects/ingest_<source>.py` ; un `SubjectCache` partagé évite les UPSERT répétés sur les sujets récurrents.

Le référentiel `subjects` n'est jamais purgé : un sujet peut rester orphelin si plus aucune publication ne le référence (historique des labels observés).

**Étape 2 — Co-occurrences.**
Recalcule depuis `publication_subjects` (en excluant les liens `rejected`) :
1. `subjects.usage_count` — nombre de publications distinctes par sujet.
2. `subject_cooccurrences` — paires de sujets co-présents sur une même publication, avec leur effectif. Seules les paires co-présentes sur au moins 2 publications sont conservées, pour borner la cardinalité.

Idempotent : le résultat ne dépend que de l'état courant de `publication_subjects`.

## Statut open access

Phase `oa_status`: interroge [Unpaywall](../glossaire.md#unpaywall) par DOI pour rafraîchir `publications.oa_status` — souvent plus à jour que le statut renseigné dans les sources. Préserve `diamond` qu'Unpaywall ne distingue pas du `gold`.

Incrémentale : chaque run est plafonné (10 000 DOI) et ne (re)vérifie que les publications jamais vérifiées ou dont le statut n'a pas été revu depuis 30 jours (les statuts stables `gold`, `hybrid`, `diamond` ne sont pas réinterrogés). Le retard des jamais-vérifiées s'écoule ainsi sur plusieurs runs au lieu d'un pic. La phase tourne dans tous les modes du pipeline.

Code : `application/pipeline/oa_status/run.py`.

Les enrichissements sur les **revues** et **éditeurs** (APC, type, pays, etc.) sont rassemblés dans la phase distincte [`publishers_journals`](05-publishers-journals.md), positionnée beaucoup plus tôt dans le pipeline (juste après affiliations).
