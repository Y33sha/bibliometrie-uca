# Workflow admin

## En amont du pipeline

### Définition des structures

`structures`, en session d'administration

Le moissonnage nécessite des **structures** :

* Créer les structures à moissonner.
* Renseigner les relations de tutelle entre structures.
* Pour le moissonnage, renseigner les identifiants de structure (au moins pour l'établissement de tutelle) :
    * identifiant [OpenAlex](../../glossaire.md#openalex), de forme `I198244214` ;
    * theses.fr : PPN de l'établissement (ex. : `252404955`) ;
    * numéro SIREN pour [ScanR](../../glossaire.md#scanr) (ex. : `130028061`) ;
    * forme de nom standardisée [WoS](../../glossaire.md#web-of-science-wos) (ex. : `Univ Clermont Auvergne`) ;
    * code de [collection HAL](../../glossaire.md#collection-hal) (ex. : `PRES_CLERMONT`) ;
    * mots-clés cherchés dans les affiliations DataCite (ex. : `Clermont, Auvergne`).

    Chaque champ peut contenir plusieurs identifiants séparés par des virgules.

![Gestion d'une structure](../../img/screenshots/admin_structure_management.png)

* Pour chaque structure à identifier dans les publications, renseigner les **formes de nom** à détecter dans les adresses. On peut commencer par les plus évidentes (nom complet, acronyme, numéro d'UMR). Les contrôles ultérieurs permettent d'affiner d'après les adresses des publications.

> Une forme **ambiguë** (acronyme, numéro d'UMR partagé) peut recevoir une contrainte de contexte : elle identifie la structure seulement si une autre structure, prise dans une liste, est détectée dans la même adresse.
>
> Exemple : la forme *LMV* identifie le *Laboratoire Magmas et Volcans* seulement si l'UCA ou le site clermontois sont identifiés dans l'adresse.
>
> ```Université Clermont Auvergne, CNRS, F-63000 Clermont-Ferrand, IRD, OPGC, LMV, France``` => UCA identifiée => laboratoire identifié par la forme « LMV »
>
> ```LMV - Laboratoire de Mathématiques de Versailles (Bâtiment Fermat - UFR de sciences 45 avenue des Etats-Unis 78035 VERSAILLES - France)``` => pas d'identification

> Une forme trop permissive peut être complétée par des formes **excluantes** : une adresse qui contient une forme excluante n'identifie pas la structure.
>
> Exemple : l'*UMR Territoires* est identifiée par le mot *territoires*, à condition que l'UCA soit reconnue dans l'adresse. La forme excluante *territoires uranifères* évite une fausse identification : ```Université Clermont Auvergne, CNRS, GEOLAB, Clermont-Ferrand 63000, France; LTSER "Zone Atelier Territoires Uranifères", Clermont-Ferrand, Aubière F-63000, France``` => pas d'identification, malgré *territoires* + *Université Clermont Auvergne*.

### Configuration du pipeline

Les années, les périmètres et les délais de réinterrogation des sources se règlent dans `admin/config`.

#### Années

Le pipeline a [deux modes](../../pipeline/01-vue-d-ensemble.md) :

- le mode *full* interroge les sources depuis l'année de début configurée jusqu'à l'année courante ;
- le mode *daily* interroge seulement les dépôts HAL parus depuis le dernier lancement.

#### Délais de réinterrogation

Au-delà d'un délai réglable en jours, le pipeline interroge de nouveau une source :

- un document non revu depuis ce délai est réinterrogé à sa source (90 jours par défaut) ;
- un identifiant introuvable dans une source y est cherché de nouveau (30 jours par défaut) ;
- le statut open access d'une publication est vérifié de nouveau auprès d'Unpaywall (15 jours par défaut) ;
- le fichier du DOAJ est téléchargé de nouveau (30 jours par défaut).

#### Périmètres

Un périmètre se définit par une ou plusieurs structures racines, et inclut tous leurs descendants par les tutelles.

Pour moissonner tous les laboratoires d'une université :

- créer l'université et ses laboratoires dans `structures`, avec leurs relations de tutelle ;
- créer un périmètre avec l'université pour structure racine ;
- dans « Rôles des périmètres », choisir ce périmètre pour le moissonnage et pour la création des personnes.

#### Identifiants d'accès aux sources

[WoS](../../sources/04-wos.md) demande une clé API, [ScanR](../../sources/05-scanr.md) un compte. [OpenAlex](../../sources/03-openalex.md) et [Crossref](../../sources/06-crossref.md) demandent une adresse électronique de contact. La documentation de chaque source explique comment obtenir ses identifiants.

Ces identifiants se règlent dans l'environnement du serveur : cf. [documentation d'exploitation](../../exploitation/03-pipeline.md#identifiants-daccès-aux-sources). Une source sans identifiants est sautée au lancement, avec un avertissement.

## En aval du pipeline

### Contrôle des affiliations

Le contrôle des affiliations affine les formes de nom de chaque structure :

- confirmer ou rejeter les liens adresse-structure détectés par le pipeline, un par un ou par lot ;
- comparer la détection automatique et les décisions manuelles (bouton « Qualité de la détection ») : un lien créé à la main signale une forme de nom manquante, un lien rejeté une forme trop permissive.

![Affiliations des adresses](../../img/screenshots/admin_addresses.png)

Les formes de nom ajoutées ou supprimées prennent effet au run suivant, y compris pour les adresses déjà en base. Une décision manuelle l'emporte toujours sur la détection automatique.

### Gestion du référentiel de personnes

#### Fusion des doublons

Quand l'auteur d'une publication n'a pas d'identifiant ([PID](../../glossaire.md#pid)), la [résolution des personnes](../../pipeline/09-persons.md) l'identifie par la forme de son nom. Plusieurs formes de nom pour une même personne créent donc des doublons.

Il faut **fusionner** les doublons, en particulier après les premiers runs. Une fusion transfère à la personne conservée :

- les formes de nom : les rattachements futurs par ces formes aboutissent à cette personne ;
- les identifiants ;
- les publications.

Deux personnes présentes dans l'[extraction RH](../../sources/10-imports-manuels.md) ne fusionnent pas.

La file des doublons par nom, dans la liste des personnes, présente les paires candidates : doublons probables en tête, homonymes en fin. Pour chaque paire, on fusionne vers la personne à conserver, ou on marque la paire comme distincte, ce qui la retire de la file.

#### Détachement des contributions attribuées à tort

Une publication attribuée à la mauvaise personne se détache depuis le volet de la personne, par la forme de nom concernée. La contribution détachée rejoint les [contributions orphelines](#contributions-orphelines).

#### Vérification des identifiants de personne

La [résolution des personnes](../../pipeline/09-persons.md) rattache aux personnes les identifiants (ORCID, IdRef, idHAL) présents dans les publications.

Un identifiant attribué à une personne est en attente (*pending*) par défaut. Après vérification, on le confirme ou on le rejette depuis le volet de la personne. On peut aussi ajouter à la main un identifiant trouvé sur https://orcid.org/ ou https://www.idref.fr/.

Un identifiant appartient à une seule personne. Il peut être réattribué à une autre personne une fois rejeté.

#### Correction du nom

Le volet de la personne permet de corriger le nom et le prénom venus des sources. Les noms de famille composés sont souvent mal découpés : la première partie du nom passe dans le prénom (Alain Le Grand => prénom « Alain Le », nom « Grand »). Le nom et le prénom sont parfois inversés.

#### Contributions orphelines

La page `admin/orphan-contributions` liste les [contributions](../../glossaire.md#contribution) de l'établissement sans personne. Deux causes :

- la contribution a été détachée à la main ;
- le pipeline n'a pas pu décider. Le plus souvent, aucun identifiant ne désigne une personne et le nom en désigne plusieurs, fréquent quand le prénom est réduit à l'initiale. Autres causes : identifiants ou épinglages contradictoires, candidats tous rejetés, rôle de jury seul ([rattachement des personnes](../../pipeline/09-persons.md)).

On rattache ces contributions, une par une ou par lot, à une personne existante ou à une personne créée à la main.
