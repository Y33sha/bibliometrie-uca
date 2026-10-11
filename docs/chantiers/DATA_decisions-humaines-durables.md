# Chantier — Décisions humaines durables

## Contexte

Le référentiel des personnes est ouvert : le pipeline crée une personne pour toute signature du périmètre qu'il ne rattache à personne. Il compte plus de 15 000 personnes, avec des faux positifs et des doublons. Les corrections à la main (fusions, rejets, exclusions, statuts) sont une part importante du travail. Les systèmes comparables partent au contraire d'une liste fermée de personnes, l'annuaire, et cherchent leurs publications ; la question de la survie des décisions ne s'y pose pas dans les mêmes termes.

### Deux manières de perdre une décision

- **L'écrasement.** La décision est écrite dans une colonne que le pipeline écrit aussi. Une valeur écrasée est perdue, sans trace.
- **La disparition du support.** La décision est dans une table ou une colonne à part, mais elle est accrochée à une entité dérivée (`publication_id`, `person_id`, identifiant de signature). La suppression de l'entité l'emporte par cascade.

Le mode de stockage ne suffit donc pas à dire si une décision est à l'abri : une table dédiée protège de l'écrasement, pas de la disparition du support.

### Mesure en base locale (2026-10-10)

Le journal d'audit garde chaque rejet (`authorship.rejected`). Sur 761 rejets journalisés : 128 sont en place, 136 ont été levés, 53 ont disparu avec leur publication, environ 440 avec leur personne, 4 sans explication. La base locale a connu des scripts ponctuels de fusion et de suppression de personnes : la part du pipeline n'y est pas isolable.

La disparition du support est la perte dominante. Les rejets sont pourtant dans une table dédiée.

### Le cycle des personnes supprimées

La phase `persons` supprime une personne qui n'a plus aucune signature (`delete_empty_persons`), sauf si elle a une notice dans l'annuaire. Une personne perd ses signatures quand l'administration la rejette de sa seule publication, rejette sa forme de nom, ou quand un rattachement ambigu est défait. La suppression emporte ses décisions. Les signatures du périmètre restent : au run suivant, la cascade crée une nouvelle personne, et les corrections sont à refaire.

La docstring de `delete_empty_persons` pose qu'une personne vide n'a pas de décision humaine. La mesure le contredit.

## Décisions

- **Une entité visée par une décision humaine est conservée par défaut**, même vide ou hors périmètre. Elle peut être masquée dans l'interface et l'API publiques.
- **Fusion de personnes : les décisions sont reportées sur la personne conservée.** Les personnes n'ont pas d'identifiant naturel général. La fusion applique déjà les rejets des deux personnes.
- **Une décision sur un lien est une entrée de la résolution**, rattachée autant que possible à des identifiants stables : notice (source et identifiant dans la source), identifiant naturel (DOI, ISSN, ROR, ORCID, IdRef). La résolution en tient compte au lieu de la subir.
- **Une correction de valeur est stockée à part et l'emporte sur la valeur calculée.** La valeur d'un champ est la valeur humaine si elle existe, sinon la valeur calculée. Ce qu'un humain a décidé se lit en un seul endroit, avec son auteur et sa date.
- **Une fusion d'entités laisse des alias** : formes de nom et identifiants transférés à l'entité conservée, qui la font retrouver aux runs suivants. C'est déjà le cas pour les revues et les éditeurs.
- **Les décisions vivent dans un schéma PostgreSQL dédié.** L'API y écrit, le pipeline y lit seulement. C'est la catégorie « décision » de la fiche [Architecture cible du pipeline](CODE_architecture-cible-pipeline.md).
- **Les décisions sur des liens restent dans des tables typées**, avec leurs clés : la résolution les lit par jointure. Pas de journal générique rejoué après coup.

## Recensement

Le recensement part des actions d'administration : tout ce qui fusionne, rattache, détache ou modifie une entité. Partir des tables laisserait de côté les actions qui n'y laissent pas de trace propre.

### Grille

Pour chaque action, trois caractères :

- **Stockage**, l'un de ces cas :
  - table dédiée ;
  - colonne dédiée, que le pipeline n'écrit pas ;
  - valeurs dédiées dans une colonne partagée (statut `pending` par défaut, `confirmed` ou `rejected` posés par l'administration seule) ;
  - colonne que le pipeline remplit seulement si elle est vide ;
  - colonne que le pipeline écrit aussi, avec un marqueur d'origine ;
  - colonne que le pipeline écrit aussi, sans marqueur.
- **Support** : l'entité ou l'identifiant auquel la décision est accrochée.
- **Détruite par** : les étapes du pipeline qui écrasent la valeur ou suppriment le support.

Une action est à risque si son stockage est le dernier cas, ou si son support peut disparaître. Une colonne que le pipeline remplit seulement si elle est vide préserve une valeur saisie, mais pas une remise à vide.

### État connu

Repris de l'inventaire du pipeline. Stockages vérifiés dans le code le 2026-10-11.

#### Décisions sur des liens

- **Rejet d'une paire** (`rejected_authorships`)
  - Stockage : table dédiée, une ligne par notice de la publication.
  - Support : notice, personne.
  - Détruite par : suppression de la notice (document disparu de sa source, notice rejetée) ; suppression de la personne.
- **Confirmation d'une signature** (`confirmed_authorships`)
  - Stockage : table dédiée.
  - Support : signature, personne.
  - Détruite par : suppression de la signature par `normalize` (signature disparue de sa notice, ou dont le nom ou les identifiants changent ; notice rejetée ; document disparu) ; suppression de la personne.
- **Non-doublon** (`distinct_persons`)
  - Stockage : table dédiée.
  - Support : deux personnes.
  - Détruite par : suppression de l'une des personnes.
- **Identifiant manuel ou confirmé** (`person_identifiers`)
  - Stockage : valeurs dédiées dans une colonne partagée.
  - Support : personne.
  - Détruite par : suppression de la personne.
- **Statut d'une forme de nom** (`person_name_forms`)
  - Stockage : valeurs dédiées dans une colonne partagée.
  - Support : personne.
  - Détruite par : suppression de la personne.
- **Lien adresse-structure confirmé ou manuel** (`address_structures`)
  - Stockage : colonne dédiée (`is_confirmed`). Dans la même ligne, le pipeline écrit seulement `matched_form_id`, et ne supprime que les liens automatiques non confirmés.
  - Support : adresse, structure.
  - Détruite par : rien dans le pipeline ; côté administration, suppression de la structure.

#### Décisions sur des valeurs

- **Exclusion d'une personne** (`persons.exclusion`)
  - Stockage : colonne dédiée.
  - Support : personne.
  - Détruite par : suppression de la personne.
- **Type de revue**
  - Stockage : colonne que le pipeline écrit aussi, avec marqueur d'origine (`journals.manual_fields`).
  - Support : revue.
  - Détruite par : suppression de la revue vide.
- **APC d'une revue**
  - Stockage : colonne que le pipeline écrit aussi, avec marqueur d'origine (`journals.manual_fields`). L'APC saisi est en euros.
  - Support : revue.
  - Détruite par : suppression de la revue vide.
- **Titre, ISSN et modèle OA d'une revue**
  - Stockage : colonnes et table que le pipeline écrit aussi, avec marqueur d'origine (`journals.manual_fields`). Des ISSN saisis sortent de la vérification Sudoc ; un titre saisi n'est pas remplacé par le titre de série du Sudoc ; un modèle OA saisi, même vide, n'est pas rempli.
  - Support : revue.
  - Détruite par : suppression de la revue vide.
- **Champs d'un éditeur** (`name`, `country`, `publisher_type`)
  - Stockage : colonne que le pipeline remplit seulement si elle est vide. Le pipeline pose le nom à la création ; l'enrichissement des éditeurs (script de maintenance) remplit le pays s'il est vide.
  - Support : éditeur.
  - Détruite par : suppression de l'éditeur vide.
- **Pays d'une adresse** (`addresses.countries`)
  - Stockage : colonne que le pipeline remplit seulement si elle est vide (normalisation ScanR, détection des pays).
  - Support : adresse.
  - Détruite par : une remise à vide est annulée par la détection suivante ; un pays saisi est préservé.

#### Actions d'administration

Relevé des routes d'écriture de l'API. Une action qui écrit une décision déjà décrite y renvoie.

Personnes et signatures :

- **Fusion de deux personnes**
  - Stockage : aucun. La personne absorbée est supprimée ; le journal d'audit garde la fusion. Le domaine recense les données d'une personne et la règle de fusion de chacune (`PERSON_DATA`) ; un test le confronte au schéma.
  - Support : personne conservée. Une personne qui a une notice dans l'annuaire est toujours conservée.
  - Reportés : signatures, authorships, rejets, confirmations, non-doublons, identifiants et formes de nom avec leurs statuts, exclusion la plus forte.
  - Perdu : le nom de la personne absorbée ; ses formes de nom restent.
- **Rattachement d'une signature orpheline**, à une personne existante ou créée pour l'occasion : confirmation d'une signature. Avec forçage, lève le rejet de la paire.
- **Détachement de signatures** : rejet de la paire, pour chaque publication des signatures choisies.
- **Exclusion d'une authorship** : rejet de la paire.
- **Rejet d'une forme de nom** : statut d'une forme de nom. Détache aussi les signatures non confirmées qui ont cette forme, sans rejet de paire.
- **Ajout d'un identifiant** : identifiant manuel, statut `pending`. Support : couple (type, valeur), unique en base.
- **Réattribution d'un identifiant** à une autre personne : statut remis à `pending`.
- **Nom de la personne** (`persons.last_name`, `first_name`)
  - Stockage : colonne que le pipeline écrit aussi, sans marqueur. Le pipeline complète un prénom réduit à des initiales.
  - Support : personne.
  - Détruite par : suppression de la personne.

Revues et éditeurs :

- **Édition d'une revue** : titre, type, modèle OA, caractère académique, APC, ISSN. La présence au DOAJ n'est pas modifiable : le DOAJ fait autorité. Un champ modifié rejoint `journals.manual_fields` ; le caractère académique, que le pipeline n'écrit pas, n'a pas de marqueur. Support : revue.
- **Changement de type d'une revue** : réécrit les métadonnées des notices de la revue, puis recalcule leurs publications.
- **Fusion de deux revues**
  - Stockage : alias. ISSN et formes de nom passent à la revue conservée ; le pipeline la retrouve par eux. Le domaine recense les données d'une revue et la règle de fusion de chacune (`JOURNAL_DATA`) ; un test le confronte au schéma.
  - Reportés : publications, notices, monographies, paiements d'APC ; éditeur, identifiant OpenAlex, APC et modèle OA si la revue conservée n'en a pas ; type si celui de la conservée est inconnu ; présence au DOAJ si l'une des deux y est.
  - Perdus : titre et caractère académique de la revue absorbée.
- **Édition d'un éditeur** : champs d'un éditeur.
- **Fusion de deux éditeurs**
  - Refusée si les deux éditeurs ont des membres Crossref sans aucun membre commun.
  - Stockage : alias. Formes de nom, préfixes DOI, revues, monographies et paiements d'APC passent à l'éditeur conservé. Les revues homonymes des deux éditeurs sont fusionnées. Le domaine recense les données d'un éditeur et la règle de fusion de chacune (`PUBLISHER_DATA`) ; un test le confronte au schéma.
  - Reportés : identifiant OpenAlex et pays si l'éditeur conservé n'en a pas ; type si celui de l'éditeur conservé est inconnu.
  - Perdu : le nom de l'éditeur absorbé.

Adresses :

- **Revue d'un lien adresse-structure** : lien adresse-structure. La remise en attente supprime un lien manuel, et remet un lien automatique à `is_confirmed = NULL`.
- **Pays d'une adresse**, unitaire ou par lot : pays d'une adresse. La valeur saisie est recopiée sur les adresses de même texte normalisé.

Référentiels que seule l'administration écrit (`structures`, `structure_name_forms`, `structure_tutelles`, `perimeters`, `config`) :

- Stockage : tables que le pipeline n'écrit pas. Support : la ligne elle-même.
- **Suppression d'une structure** : supprime par cascade ses formes de nom, ses tutelles et ses liens adresse-structure, confirmés compris. La confirmation affiche ce qu'elle emporte ; l'événement d'audit en garde un instantané, qui permet de la réparer à la main.

## Phasage

### Phase 1 — Recensement

- [x] Lister les actions d'administration à partir des routes de l'API et des services appelés.
- [x] Remplir la grille pour chacune : stockage, support, détruite par.
- [x] Vérifier les confirmations des signatures theses.fr : theses.fr passe par le writer commun des signatures.
- [x] Revue au cas par cas des actions à risque.

### Phase 2 — Les entités visées par une décision ne sont plus supprimées

- [x] Définir les décisions qui protègent une entité : un lien confirmé ou rejeté, et l'exclusion, qui évite la réapparition. Une modification d'attribut ou une confirmation d'identifiant ne protège pas. Revues et éditeurs n'ont pas de décision sur un lien : rien ne les protège.
- [x] `delete_empty_persons` épargne ces personnes ; la condition dérive des données de nature décision de `PERSON_DATA`.
- [x] Corriger la docstring de `delete_empty_persons`.
- [x] Masquer dans l'annuaire public une personne sans authorship ni fiche RH.
- [x] Signature dont tous les candidats par forme de nom sont rejetés : elle reste orpheline, avec un motif dédié (`all_candidates_rejected`).

### Phase 3 — Les écrasements

- [x] Marqueur d'origine dans la ligne (`journals.manual_fields`) plutôt qu'une table de décisions à part : un champ saisi à la main n'est plus écrit par le pipeline, et le journal d'audit garde l'auteur et la date.
- [x] Revues : titre, ISSN, type, modèle OA, APC. Reprise des types saisis depuis le journal d'audit.
- [x] Présence au DOAJ : retirée de l'édition, le DOAJ fait autorité.
- [x] Éditeurs : le pipeline n'écrit ni le nom, ni le type, et remplit le pays seulement s'il est vide ; pas de marqueur.

### Phase 4 — Les supports instables

Ce qui reste à risque après la phase 2.

- [x] Rejets d'une paire : rattachés aux notices de la publication. Une publication est rejetée pour une personne dès qu'une de ses notices l'est ; une signature confirmée l'emporte sur le rejet.
- [ ] File d'administration des décisions contradictoires (notice rejetée et signature confirmée pour la même personne dans une publication).
- [ ] Autres cas relevés par la phase 1.

### Phase 5 — Schéma dédié

- [ ] Créer le schéma des décisions, avec ses droits : l'API écrit, le pipeline lit.
- [ ] Y faire atterrir les tables créées par les phases 3 et 4.
- [ ] Y déplacer les tables de décisions sans perte, si le gain le justifie.

## Questions ouvertes

- Valeurs dédiées dans une colonne partagée (statuts) : les laisser en place, ou les sortir vers le schéma des décisions ?

## Reporté

- Mesure sur la base de prod, avec un script qui confronte chaque type de décision journalisé à l'état de la base. Ne bloque pas les phases 1 à 3.
- Correction de valeur face à une source jugée plus fiable : la valeur humaine l'emporte-t-elle toujours ?
