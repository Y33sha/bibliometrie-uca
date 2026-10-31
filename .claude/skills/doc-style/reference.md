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
        """Renvoie la forme canonique du DOI : minuscules, préfixe https://doi.org/ retiré."""

## Docstring de classe qui résume ses champs

« Ce que X fait à Y » personnifie le code et reste vague. La liste en prose de tous les champs redit leurs noms. Le résumé dit ce qu'est la classe ; un champ non évident reçoit sa propre docstring.

AVANT :
    class PhaseContext:
        """Ce que le run remet à chaque phase : ses transactions, son journal, ses options, l'exécution de la maintenance des tables (`VACUUM`, `ANALYZE`) hors transaction, le contrôle des identifiants d'accès aux sources et leur débit."""

        open_tx: OpenTransaction
        logger: logging.Logger
        options: RunOptions
        maintain: Callable[[str], None]

APRÈS :
    class PhaseContext:
        """Dépendances d'exécution d'une phase."""

        open_tx: OpenTransaction
        logger: logging.Logger
        options: RunOptions
        maintain: Callable[[str], None]
        """Lance `VACUUM` et `ANALYZE` sur une table, hors transaction."""

## Paramètres non évidents

Seuls les paramètres non évidents ont une ligne, dans une section `Args:`.

AVANT :
    def find_or_create_serial(title, *, issns=(), publisher_id=None, repo):
        """Trouve ou crée un journal. `publisher_id`, l'éditeur du document, restreint la recherche par titre et s'enregistre avec la forme de nom."""

APRÈS :
    def find_or_create_serial(title, *, issns=(), publisher_id=None, repo):
        """Trouve ou crée une revue. Renvoie son id, ou `None` si le titre est vide.

        Args:
            publisher_id: éditeur du document ; restreint la recherche par titre.
        """


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

## Phrases d'annonce

Dire les choses, ne pas les annoncer. Une phrase qui compte ou annonce ce qui suit (« cinq phases font x », « ce module se compose de trois parties ») se supprime.

AVANT :
    Quatre phases écrivent ces tables, dans l'ordre où le pipeline les enchaîne.

    | Phase | Ce qu'elle écrit |

APRÈS :
    | Phase | Ce qu'elle écrit |

AVANT :
    Deux chaînes propagent une écriture de ces tables jusqu'aux colonnes que consultent les pages : `address_structures` → vue matérialisée → `source_contributions.perimeter_evidence`, et `addresses.countries` → `source_records.countries` → `publications.countries`.

    **Appartenance au périmètre.** Dernière étape d'`affiliations` […]

APRÈS :
    **Appartenance au périmètre** : `address_structures` → vue matérialisée → `source_contributions.perimeter_evidence`. Dernière étape d'`affiliations` […]

## Pronoms « y » et « en » à antécédent lointain

N'employer « y » ou « en » que si l'antécédent est le groupe nominal qui précède immédiatement, dans la même phrase. Sinon, répéter le nom.

AVANT :
    La règle générale est que les use-cases commitent (cf. discipline transactionnelle). Côté pipeline, les phases qui traitent des dizaines de milliers d'items commitent par batch. Les phases concernées y sont listées.

APRÈS :
    La règle générale est que les use-cases commitent (cf. discipline transactionnelle). Côté pipeline, les phases qui traitent des dizaines de milliers d'items commitent par batch.

AVANT :
    Un `SourceRecord` est ce qu'une source dit d'un document. Une `Publication` est la référence unifiée que le pipeline en dérive.

APRÈS :
    Une `Publication` est l'entité unifiée que le pipeline dérive de plusieurs `SourceRecord` désignant le même document.

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
    Store univoque `(publication_id, person_id, created_at)`, PK composite, FK `ON DELETE CASCADE` vers `publications` et `persons`. Écrit par l'exclusion canonique (croix de la page personne → `PATCH /api/contributions/{id}/exclude`), qui y insère la paire et supprime la row `contributions`. Tous les sites de création d'`contributions` (build + assignation d'orphelins) anti-joignent ce store, de sorte que le rejet survit aux rebuilds — contrairement à un drapeau sur la table dérivée, purgé en mode `full`. Une fusion de personnes transfère les rejets de l'absorbée vers l'absorbante (dédoublonnage sur conflit de PK).

APRÈS :
    Paires (publication, personne) écartées. Clé primaire `(publication_id, person_id)`. Les sites de création d'`contributions` les anti-joignent, si bien que le rejet ne se défait pas au rebuild.

AVANT :
    Pendant du rejet : store `(source_contribution_id, person_id)` des attributions épinglées à la main. `enforce_confirmed_source_contributions` (phase `persons`) réapplique l'épingle à chaque run — `source_contributions.person_id` est recalé sur la personne épinglée — et le matching la respecte : une signature épinglée n'est ni re-orphelinée ni réattribuée. Durable aux reconstructions, comme `rejected_contributions`.

APRÈS :
    Signatures épinglées sur une personne. Clé primaire `source_contribution_id` seul : une signature ne s'épingle qu'à une personne. La phase `persons` réapplique l'épingle à chaque exécution, et une signature épinglée n'est ni ré-orphelinée ni réattribuée.

Dans une doc de haut niveau, une règle d'implémentation glissée en incise rend la phrase inintelligible sans le contexte du code. La règle va dans la docstring ; la doc nomme seulement la donnée.

AVANT :
    - **Licence** : celle de la localisation principale, normalisée seulement pour une localisation d'éditeur

APRÈS :
    - **Licence** : licence de la localisation principale (`primary_location`)


## Micro-détail que l'interface ou le code montre

La documentation sert à l'onboarding. Ce qu'un nouveau venu apprend en explorant l'interface ou en lisant une docstring ne s'y écrit pas : le supprimer, sans le déplacer ailleurs.

AVANT :
    **Administration**, en session d'administration. La barre de navigation passe en clair et propose le menu Administration :

APRÈS :
    **Administration**, en session d'administration :

AVANT :
    Les captures d'écran se refont avec `python -m interfaces.cli.dev.screenshots`, l'application en cours d'exécution.

APRÈS :
    (rien)

## Définition qui mêle l'essentiel et l'accidentel

Une définition dit ce qu'est l'entité. La façon dont elle est alimentée (saisie à la main, import, calcul) est un détail d'implémentation : elle va ailleurs, ou nulle part.

AVANT :
    | structure | `structures` | Établissement, laboratoire, site ou service, saisi à la main |

APRÈS :
    | structure | `structures` | Établissement, laboratoire, équipe, site ou service |

## Relatives et pronoms en série

« que », « dont », « y » et « en » alourdissent la phrase. Une tournure participiale, un adjectif ou un complément de nom dit la même chose plus court.

AVANT :
    le bidule que schtroumpfe le truc

APRÈS :
    le bidule schtroumpfé par le truc

## Énumération de cas tassée en prose

Des cas parallèles enchaînés par des points-virgules et des fragments sans verbe (« ; version inconnue. Ou son chemin… ») ne se lisent plus. Une liste, une phrase complète par cas.

AVANT :
    - Une adresse enregistrée donne une copie ouverte de la publication, sans licence, dans deux cas. Elle mène à une plateforme en accès libre intégral d'après sa propre déclaration : arXiv, bioRxiv, medRxiv, PubMed Central ; version inconnue. Ou son chemin finit par `.pdf` ; version de l'éditeur. Les autres adresses enregistrées donnent seulement une ligne de `sources.dois`.

APRÈS :
    - Une adresse enregistrée donne une copie ouverte de la publication, sans licence :
      - quand elle mène à arXiv, bioRxiv, medRxiv ou PubMed Central. Ces plateformes déclarent donner librement accès à tout leur contenu. La version de la copie est inconnue.
      - quand son chemin finit par `.pdf`. La copie est en version de l'éditeur.

## Étapes numérotées

Le titre d'une étape la nomme ; un numéro n'apporte rien quand l'ordre se lit déjà dans la suite des paragraphes.

AVANT :
    **Étape 1 — `fetch_missing.hal_by_id` et `fetch_missing.scanr_by_hal_id` : documents manquants, par hal-id.**

APRÈS :
    **`fetch_missing.hal_by_id` et `fetch_missing.scanr_by_hal_id` : documents manquants, par hal-id.**

## Personnification du code

Une phase, un module ou une étape ne « cherche » ni n'« essaie ». Quand l'action est celle du processus, « on » suffit.

AVANT :
    On essaie donc de retrouver dans chaque source les documents trouvés seulement dans les autres.

APRÈS :
    On cherche donc dans chaque source les documents trouvés seulement dans les autres.

## Mot qui fait poser une question au lecteur

Relire hors du contexte du projet. Un mot qui fait poser une question (meilleure selon quel critère ? lequel parmi d'autres ?) se remplace par un mot plus simple qui ne la pose pas.

AVANT :
    Le bouton « Accéder » mène à la meilleure copie ouverte, à défaut au DOI.

APRÈS :
    Le bouton « Accéder » mène au texte intégral, à défaut au DOI.

Une sélection sans critère fait aussi poser la question « pourquoi ceux-là ? ». Citer quelques éléments d'une liste parce qu'ils ont un lien vers le glossaire n'est pas un critère : supprimer.

AVANT :
    Les filtres couvrent notamment le paiement d'[APC](../../glossaire.md#apc), la [voie *open access*](../../glossaire.md#voies-open-access) et les [organisations partenaires](../../glossaire.md#organisation-partenaire).

APRÈS :
    (rien)

## Décision énoncée sans sa raison

Une décision négative nue en dit trop ou trop peu : le lecteur se demande pourquoi. Donner la raison en une proposition, ou supprimer la phrase.

AVANT :
    La collection HAL n'est pas un indice.

APRÈS :
    La collection HAL n'est pas un indice : elle double la structure HAL.

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