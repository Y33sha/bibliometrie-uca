# Hiérarchie du pipeline — arborescence cible

Annexe de la fiche [Hiérarchie du pipeline](CODE_hierarchie-du-pipeline.md). L'arborescence vise seulement la lisibilité. Chaque élément a sa phrase d'entrées → sorties. Les noms entre parenthèses désignent les phases et les tâches actuelles.

## Arborescence

**Pipeline** : sources, périmètre, référentiel RH → publications, contributions et personnes du périmètre, avec leurs métadonnées

1. **Collecte** : périmètre, personnes RH, documents connus → documents bruts complets (`staging`)
   1. **Découverte** : périmètre, personnes RH, identifiants connus → documents bruts
      - par affiliation (`harvest`) : une tâche par source
      - par personne (`harvest_by_person`) : une tâche par source
      - par identifiant trouvé dans une autre source (`fetch_missing`) : une étape par source, sources en parallèle, recherches de chaque source enchaînées (hal-id, NNT, numéro de brevet, DOI)
   2. **Recherche des documents non revus** (`fetch_stale`) : documents non revus depuis un délai → documents rafraîchis, documents disparus marqués
   3. **Complétion** (`fetch_truncated`) : documents OpenAlex au plafond d'auteurs → listes d'auteurs complètes
2. **Enregistrements sources** : documents bruts → enregistrements sources normalisés, rattachés aux référentiels, corrigés
   1. **Normalisation** (`normalize`) : documents bruts → enregistrements sources, contributions sources, adresses
      - normalisation par source
      - retraits : contributions sources OpenAlex doublées par INSPIRE-HEP, enregistrements sources des documents disparus
      - nettoyage : informations du contributeur et adresses sans contribution source
   2. **Affiliations** (`affiliations`) : adresses et identifiants de structure des contributions sources → structures, pays et indices de périmètre des contributions sources
      1. **Référentiels de structures** : dump ROR, structures HAL citées → référentiels ROR et HAL à jour
      2. **Structures** : adresses, partenaires de thèse → structures des contributions sources
      3. **Pays** : adresses → pays des adresses, des contributions sources et des enregistrements sources ; publications des enregistrements sources modifiés mises en file de consolidation
      4. **Périmètre** (`populate`) : structures atteintes, identifiants des personnes RH → indices de périmètre des contributions sources
   3. **DOI** (`dois`) : DOI connus → agence de chaque préfixe, existence, URL de résolution et verdict d'Unpaywall de chaque DOI ; publications des DOI dont une réponse change mises en file de consolidation
      - agence des préfixes (`resolve_prefixes`) : doi.org
      - existence et URL de résolution (`resolve_dois`) : API des handles de doi.org, pour tous les DOI connus
      - statut open access (`verify_unpaywall`) : Unpaywall, pour les DOI candidats au DOI d'une publication, hors DOI DataCite
   4. **Édition** (`publishing`) : DOI, noms d'éditeur, ISSN, ISBN et titres → éditeur, revue et monographie de chaque enregistrement source
      1. **Préfixes DOI** (`resolve_crossref_publishers`, `resolve_datacite_publishers`) : préfixes DOI → éditeur titulaire de chaque préfixe
      2. **Éditeurs** : noms d'éditeur → éditeur de chaque enregistrement source, sans doublon
      3. **Revues** : ISSN, titres, identifiants OpenAlex → revue de chaque enregistrement source, typée et qualifiée
      4. **Monographies** : ISBN, titres → monographie de chaque enregistrement source, rattachée à sa collection, typée
   5. **Correction** (`metadata_correction`) : enregistrements sources rattachés → enregistrements sources corrigés, admis ou écartés de la réconciliation
3. **Entités** : enregistrements sources corrigés → publications, contributions, personnes
   1. **Publications** (`publications`) : enregistrements sources → publications, métadonnées consolidées
      - réconciliation (`reconcile`) : enregistrements sources → publications, dont les publications touchées sont consolidées aussitôt
      - consolidation (`consolidate`) : publications de la file `publications_queue` → métadonnées consolidées
   2. **Contributions** (`author_grouping`) : contributions sources d'une publication → contributions et leurs attributs
   3. **Personnes** (`persons`) : contributions, identifiants → personne de chaque contribution, formes de nom
4. **Données dérivées** (`finalize`, `persons.purge`) : entités → périmètre des publications, purges, vues, compteurs
   1. **Purges** : personnes et publications hors du périmètre
   2. **Périmètre des publications**
   3. **Vues des structures**
   4. **Nettoyage des référentiels de l'édition** : éditeur des revues, suppression des entrées vides
   5. **Compteurs** : publications des adresses, des revues, des éditeurs
5. **Enrichissements** : publications → relations, sujets
   - **Relations** (`relations`) : enregistrements sources, publications → relations entre publications
   - **Sujets** (`subjects`) : sujets des enregistrements sources → sujets des publications, usage, cooccurrences

## Écarts avec l'exécution actuelle

### Lectures du run précédent

- **Découverte.** `fetch_missing` cherche les identifiants des enregistrements sources des publications du périmètre. `harvest_by_person` lit les personnes et leurs contributions. Ces deux tâches lisent les entités du run précédent. Un document découvert au run N élargit la recherche du run N+1.
- **Agence des DOI.** `fetch_missing` cherche dans Crossref et DataCite les DOI dont l'agence est connue, trouvée par la phase `dois` au run précédent. La phase `dois` interroge doi.org sur les DOI des enregistrements sources et sur les DOI cibles des relations du run précédent. Un DOI apparu dans un enregistrement source au run N est cherché au run N+1. Un DOI cible d'une relation au run N est cherché au run N+2. Décision : la phase `dois` suit la normalisation, car l'éditeur titulaire, la réconciliation et Unpaywall lisent l'agence des DOI normalisés dans le même run. Le délai des DOI cibles des relations est accepté.
- **DOI.** Unpaywall exclut les DOI qui ont une cible. Les cibles sont calculées par la correction, placée après la phase `dois` : un DOI de version apparu dans le run peut être soumis une fois à Unpaywall.
- **Édition.** `attach_serials` lit le périmètre et le nombre de publications des revues, calculés au run précédent.

### Écritures dans un autre élément

- **Agence des préfixes DOI.** La phase `dois` pose l'agence. `resolve_crossref_publishers` et `resolve_datacite_publishers`, dans l'édition, corrigent l'agence d'un préfixe inconnu de doi.org et trouvé chez Crossref ou DataCite. Unpaywall lit cette correction au run suivant.

### Responsabilités éclatées

- **Référentiels de l'édition.** Le rattachement relève de « Édition », la suppression des entrées vides et les compteurs relèvent de « Données dérivées ». Le module de chaque référentiel garde ces deux points d'entrée.
- **Rattachement aux revues par DOI.** `serial_by_doi` rattache une revue d'après les espaces de noms DOI. La tâche relève de « Correction », car elle remplit un champ vide de l'enregistrement source.
