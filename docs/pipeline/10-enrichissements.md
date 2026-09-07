#  Enrichissements

*À jour le 2026-09-06.*

Ces quatre phases enrichissent les métadonnées des publications (relations, sujets, pays, statut *open access* à jour).

## Relations entre publications (`relations`)

Peuple la table `publication_relations`. Une relation rattache deux publications apparentées : preprint et version publiée, article et supplément de données, chapitre et ouvrage, article et erratum, data paper et jeu de données…

La table est reconstruite à chaque exécution, à partir de signaux indépendants appliqués dans l'ordre ci-dessous.

**Relations déclarées par les sources.** DataCite et Crossref publient des relations typées entre DOI, que la phase traduit vers un vocabulaire unifié.

**Clés de confirmation partagées.** Deux publications qui partagent un identifiant (HAL, arXiv, PMID, NNT) sans avoir fusionné, leurs DOI étant distincts, sont apparentées — typiquement un preprint et sa version publiée. On déduit la relation à partir des types de document.

**Rapprochement par titre.** Un erratum rejoint l'article dont il reprend le titre, un preprint sa version publiée au titre identique, à condition qu'une seule publication porte ce titre.

## Sujets (`subjects`)

Deux étapes enchaînées.

**Étape 1 — Ingestion.**
Les sujets que les sources déclarent sur chaque `source_publication` sont rattachés à la publication, dans les tables `subjects` et `publication_subjects`. Le lien garde la source qui a fourni le sujet. Seuls les concepts issus des ontologies des sources entrent dans `subjects` ; les mots-clés libres restent portés par les `source_publications`.

Les publications traitées sont celles nouvellement créées, et celles dont le contenu a changé depuis la dernière ingestion de leurs sujets. Leurs liens existants sont supprimés — sauf ceux marqués `rejected` — puis reconstruits depuis les sources. L'option `--rebuild-subjects` étend le traitement à toutes les publications.

Les sujets qu'aucun lien ne référence plus sont supprimés.

**Étape 2 — Co-occurrences.**
Recalcule depuis `publication_subjects` :
1. `subjects.usage_count` — nombre de publications distinctes par sujet.
2. `subject_cooccurrences` — paires de sujets co-présents sur une même publication, avec leur effectif. Seules les paires co-présentes sur au moins 2 publications sont conservées, pour borner la cardinalité.

Idempotent : le résultat ne dépend que de l'état courant de `publication_subjects`.

## Pays des adresses (`countries`)

Associe des pays aux adresses pour permettre l'analyse des collaborations internationales. Quatre étapes enchaînées :

1. **Détection par nom de pays.** Parse le dernier segment après la dernière virgule et le matche contre les noms de pays de `place_name_forms` (`kind = 'country'` : variantes anglais/français, codes ISO, abréviations WoS). Rapide et fiable.

2. **Détection par nom de lieu.** Pour les adresses restées sans pays, cherche dans tout le texte de l'adresse — pas seulement le dernier segment — les noms d'institutions et de villes connus (`place_name_forms`, `kind IN ('institution', 'city')`), chacun rattaché à un pays, via un automate Aho-Corasick. Le pays n'est posé que si les lieux trouvés désignent un pays unique.

3. **Suggestion pour validation manuelle.** Pour les adresses encore sans pays, cherche parmi les adresses *au pays connu* celles qui contiennent l'adresse cible comme sous-chaîne de leur texte normalisé, et retient le ou les pays les plus fréquents. Le pool est balayé en un seul passage (automate Aho-Corasick) ; les pays proposés sont stockés dans `suggested_countries`, à valider dans l'interface admin.

4. **Report sur les publications.** Recalcule `publications.countries` comme union des `source_publications.countries` de toutes les sources rattachées à chaque publication.

Code : `application/pipeline/countries/`, un module par étape.

## Statut open access (`oa_status`)

Interroge [Unpaywall](../glossaire.md#unpaywall) par DOI pour rafraîchir `publications.oa_status` — souvent plus à jour que le statut renseigné dans les sources.

Incrémentale : pour lisser dans le temps les appels API, chaque exécution est plafonnée (10 000 DOI) et ne (re)vérifie que les publications jamais interrogées ou dont le statut n'a pas été revu depuis 15 jours.

Code : `application/pipeline/oa_status/phase.py`.
