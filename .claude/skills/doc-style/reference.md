<!-- vale off -->

# Avant / après

Format : la tournure d'origine telle quelle en AVANT, la version resserrée en APRÈS. Une paire par défaut constaté.

## Docstrings verbeuses

AVANT :
    def normaliser_doi(doi: str) -> str:
        """
        Normalise un DOI.

        Cette méthode permet de normaliser un DOI passé en paramètre afin
        d'obtenir une forme canonique utilisable par la suite du traitement.

        Args:
            doi: le DOI à normaliser.
        Returns:
            Le DOI normalisé.
        """

APRÈS :
    def normaliser_doi(doi: str) -> str:
        """Forme canonique : minuscules, préfixe https://doi.org/ retiré."""


## Commentaires redondants

AVANT :
    # Clés que la lecture publique de la configuration rend. Liste blanche : une clé qu'on n'y
    # inscrit pas reste réservée à une session, ce qui protège par défaut tout réglage ajouté
    # sans que quiconque ait tranché sa nature. Une clé y figure quand une page publique la
    # consomme

APRÈS :
    # Clés de configuration consommées par une page publique

## Commentaire de ce qui a disparu

AVANT :
    Les identifiants d'accès aux sources n'y figurent pas : ce sont des secrets, lus depuis l'environnement du processus comme les autres secrets de l'application (cf. `infrastructure.settings`).

APRÈS :
    (rien)

## Explications superflues
AVANT :
    Décider quels enregistrements désignent le même document est le travail de dédoublonnage, et la raison d'être de la moitié des règles du noyau.

APRÈS :
    Le dédoublonnage consiste à décider quels enregistrements désignent le même document.

AVANT :
    **`PersonIdentifier`** (`domain/persons/`) est un agrégat séparé, d'identité naturelle `(id_type, id_value)` : c'est l'attribution d'un identifiant externe à une personne qui porte un statut, car c'est elle qu'on confirme ou qu'on rejette, non la personne.

APRÈS :
    **`PersonIdentifier`** (`domain/persons/`) est un identifiant de personne, défini par son type et sa valeur (`id_type`, `id_value`), et rattaché à une seule personne.

AVANT :
    Hydrater, c'est charger une ligne de la base dans l'entité qui lui correspond. Cela sert là où le traitement porte sur une entité à la fois : les commandes de curation, qui chargent, modifient et enregistrent l'entité éditée, et `refresh_from_sources`, qui recalcule les métadonnées canoniques d'une publication depuis ses sources. Un invariant porté par un objet a alors quelque chose à garantir.

APRÈS :
    L'hydratation sert là où le traitement porte sur une entité à la fois : les commandes de curation, qui chargent, modifient et enregistrent l'entité éditée, et `refresh_from_sources`, qui recalcule les métadonnées canoniques d'une publication depuis ses sources.

## Pronoms « y » et « en » à antécédent lointain

N'employer « y » ou « en » que si l'antécédent est le groupe nominal qui précède immédiatement, dans la même phrase. Sinon, répéter le nom.

AVANT :
    La règle générale est que les use-cases commitent (cf. discipline transactionnelle). Côté pipeline, les phases qui traitent des dizaines de milliers d'items commitent par batch. Les phases concernées y sont listées.

APRÈS :
    La règle générale est que les use-cases commitent (cf. discipline transactionnelle). Côté pipeline, les phases qui traitent des dizaines de milliers d'items commitent par batch.

AVANT :
    Une `SourcePublication` est ce qu'une source dit d'un document. Une `Publication` est la référence unifiée que le pipeline en dérive.

APRÈS :
    Une `Publication` est l'entité unifiée que le pipeline dérive de plusieurs `SourcePublication` désignant le même document.

## Périphrases obscures

AVANT :
    Le noyau porte les règles qui ne dépendent de rien

APRÈS :
    Le noyau porte les règles métier indépendamment de leur implémentation

## Définir par contraste : « X et non Y »

Écarter une lecture que personne n'a proposée fait porter au lecteur les deux termes au lieu d'un. Supprimer le « et non Y », puis vérifier que X se suffit — s'il ne se suffit pas, c'est X qu'il faut écrire plus précisément.

AVANT :
    L'étape se déclenche sur l'âge du dernier import, et non revue par revue : tant que cet import a moins de 30 jours, elle est sautée entièrement.

APRÈS :
    L'étape se déclenche seulement si le dernier import date de plus de 30 jours.

## Tournures littéraires

Dire la chose dans les mots du domaine, plutôt qu'en cherchant une image ou une formule.

AVANT :
    chaque préfixe est marqué interrogé, succès ou échec, pour qu'un préfixe muet côté API soit tenté une fois et une seule.

APRÈS :
    chaque préfixe est marqué interrogé, succès ou échec, pour qu'un préfixe non trouvé ne soit pas retenté.

AVANT :
    Elle est réattribuée par **consensus** à la personne que soutient la majorité des signatures qui la portent — recalant la capture sur son propriétaire, sans qu'un porteur étranger minoritaire ne la vole.

APRÈS :
    Une valeur d'identifiant que deux personnes se disputent revient à celle que soutient la majorité des signatures qui la portent.

## Exemples inutiles

AVANT :
    Une même donnée se lit et s'écrit depuis deux contextes : le pipeline la recalcule en masse, l'API la sert ou la retouche après une édition manuelle. Chacun a son port et son adaptateur, rangés selon leur contexte — `application/ports/pipeline/*` et `infrastructure/pipeline/*` d'un côté, `application/ports/read_models/*` et `infrastructure/read_models/*` de l'autre. Les sujets en donnent l'exemple : le port d'ingestion `application/ports/pipeline/subjects.py` écrit le référentiel, le port de lecture `application/ports/read_models/subjects_queries.py` le sert au router, et leurs deux adaptateurs vivent chacun dans leur dossier.

APRÈS :
    Une même donnée se lit et s'écrit depuis deux contextes : le pipeline la recalcule en masse, l'API la sert ou la retouche après une édition manuelle. Chacun a son port et son adaptateur, rangés selon leur contexte — `application/ports/pipeline/*` et `infrastructure/pipeline/*` d'un côté, `application/ports/read_models/*` et `infrastructure/read_models/*` de l'autre.

## Phrases d'annonce

Une phrase dont le seul contenu est « ce qui suit comporte deux points » fait attendre le texte au lieu de le donner. Supprimer, et porter la relation dans les phrases qui suivent.

AVANT :
    Le pipeline s'en écarte des deux côtés. Une phase qui traite de grands ensembles commit toutes les N opérations : son travail occupe plusieurs transactions au lieu d'une.

    À l'inverse, chaque item d'un lot est enveloppé dans un SAVEPOINT : le découpage descend cette fois sous la transaction.

APRÈS :
    Une phase qui traite de grands ensembles commit toutes les N opérations : son travail occupe plusieurs transactions au lieu d'une.

    Le découpage descend aussi sous la transaction : chaque item d'un lot est enveloppé dans un SAVEPOINT.

## Méta-langage : annoncer le nombre d'étapes

« Trois sous-étapes », « deux étapes enchaînées » décrivent la liste au lieu de décrire le traitement. La liste porte déjà son compte. Remplacer par une phrase qui dit ce que la phase fait.

AVANT :
    Phase `publishers_journals` : enrichit le référentiel `journals` (revues) à partir de sources externes, après sa création initiale en phase normalize.

    Trois sous-étapes. `resolve_publishers` s'exécute à chaque lancement du pipeline ; les deux enrichissements journaux ne tournent que lorsque l'enrichissement des référentiels est activé pour le mode courant.

APRÈS :
    La phase `publishers_journals` complète deux référentiels que la phase normalize alimente au fil des documents : elle rattache chaque préfixe DOI à son éditeur, et va chercher auprès de sources externes le type des revues et leurs frais de publication.

## Accumulation de détails sur un objet simple

Une table dont le rôle tient en une phrase n'a pas besoin d'un paragraphe. Garder ce qu'elle contient et la conséquence qui compte ; couper le chemin d'écriture, les cas de conflit, les comparaisons avec l'alternative écartée.

AVANT :
    Store univoque `(publication_id, person_id, created_at)`, PK composite, FK `ON DELETE CASCADE` vers `publications` et `persons`. Écrit par l'exclusion canonique (croix de la page personne → `PATCH /api/authorships/{id}/exclude`), qui y insère la paire et supprime la row `authorships`. Tous les sites de création d'`authorships` (build + assignation d'orphelins) anti-joignent ce store, de sorte que le rejet survit aux rebuilds — contrairement à un drapeau sur la table dérivée, purgé en mode `full`. Une fusion de personnes transfère les rejets de l'absorbée vers l'absorbante (dédoublonnage sur conflit de PK).

APRÈS :
    Paires (publication, personne) écartées. Clé primaire `(publication_id, person_id)`. Les sites de création d'`authorships` les anti-joignent, si bien que le rejet ne se défait pas au rebuild.

AVANT :
    Pendant du rejet : store `(source_authorship_id, person_id)` des attributions épinglées à la main. `enforce_confirmed_authorships` (phase `persons`) réapplique l'épingle à chaque run — `source_authorships.person_id` est recalé sur la personne épinglée — et le matching la respecte : une signature épinglée n'est ni re-orphelinée ni réattribuée. Durable aux reconstructions, comme `rejected_authorships`.

APRÈS :
    Signatures épinglées sur une personne. Clé primaire `source_authorship_id` seul : une signature ne s'épingle qu'à une personne. La phase `persons` réapplique l'épingle à chaque exécution, et une signature épinglée n'est ni ré-orphelinée ni réattribuée.


## Doc qui explique ce qu'on ne fait pas, sans dire ce qu'il faut faire

AVANT :
    Ce sont des secrets : ils sont lus dans l'environnement du processus, jamais en base, et ne se règlent donc pas depuis l'interface d'administration.

APRÈS :
    Ils s'écrivent dans le fichier .env, à la racine du dépôt, d'où les descriptions docker les injectent dans l'environnement du conteneur.

## Le verbe « vivre » pour situer une chose

Une variable qui « vit » dans un fichier, un verrou qui « vit » avec une connexion : l'image remplace la relation, et le lecteur ne sait ni comment la chose arrive là, ni ce qui l'en fait partir. Nommer la relation rend la phrase vérifiable — être stocké, être déclaré, être défini, être lu, être libéré, durer autant que, appartenir à.

AVANT :
    Les données vivent dans le volume docker `pgdata`.

APRÈS :
    Le volume docker `pgdata` contient les données.

AVANT :
    Le verrou vit avec la connexion qui le détient, et tombe avec elle.

APRÈS :
    La fermeture de la connexion qui le détient libère le verrou.

AVANT :
    Tous les secrets vivent dans l'environnement du processus, lus au démarrage par `pydantic-settings`.

APRÈS :
    `pydantic-settings` lit tous les secrets dans l'environnement du processus, au démarrage.