"""Règles de politique de création de personnes.

Module pensé pour s'étendre aux autres invariants de création
(``should_create_source_person`` unifié HAL/ScanR/theses, etc.).
À terme, regroupable avec ``merge.py`` selon la décision de
granularité « merge + dedup + create » du chantier
``regles-metier-domain``.
"""


def should_create_source_person(*, source: str, strong_id_value: object) -> bool:
    """Indique si une ligne ``source_persons`` doit être créée pour une
    authorship donnée.

    Invariant : on ne crée ``source_persons`` que pour les auteurs ayant
    un identifiant fort attaché. Sans identifiant fort, l'authorship
    reste exploitable via ``raw_author_name + author_position`` dans
    ``source_authorships``, mais on ne tente pas de la résoudre vers
    une entité auteur stable côté source.

    Signaux par source (ce qu'on considère « fort ») :

    - **HAL** : ``hal_person_id`` (entier > 0). Compte HAL identifié,
      créé par l'auteur ou un curateur. Un ``hal_person_id <= 0`` est
      une sentinelle interne ("auteur non identifié" côté HAL) qu'on
      rejette explicitement — ces signatures sont traitées comme les
      sources sans identifiant.
    - **ScanR** : ``idref`` (PPN SUDOC, identifiant national stable).
    - **theses** : ``ppn`` (PPN SUDOC, idem ScanR).

    Les autres sources (OpenAlex, WoS, Crossref) ne créent pas de
    ``source_persons`` du tout aujourd'hui — leurs entités auteur
    propres sont algorithmiques et trop bruitées pour servir de pivot
    stable. Cette fonction n'est donc appelée que par les normalizers
    HAL/ScanR/theses.
    """
    if source == "hal":
        return isinstance(strong_id_value, int) and strong_id_value > 0
    return bool(strong_id_value)


def allow_person_creation(source: str, roles: list[str]) -> bool:
    """Indique si la cascade de matching peut créer une personne pour
    cette authorship, à défaut d'avoir trouvé un match.

    Le matching à une personne existante reste **toujours autorisé** —
    cette règle ne pilote que la décision « match introuvable, faut-il
    créer une nouvelle fiche ? ».

    Règle : pour les sources qui exposent les rôles d'encadrement de
    thèse (theses.fr aujourd'hui), seules les authorships dont les
    rôles incluent ``author`` autorisent la création. Les directeurs,
    rapporteurs, présidents et membres de jury n'ont pas vocation à
    apparaître dans ``persons`` juste parce qu'ils ont supervisé une
    thèse — ils seront créés via leurs propres publications (HAL,
    OpenAlex, etc.).

    Note : distincte de la règle ``OUT_OF_SCOPE_DOC_TYPES`` (cf.
    ``domain.publications.scope``) qui exclut entièrement memoir et
    peer_review du pipeline persons (ni matching ni création). Ici on
    discute du cas inverse : matching autorisé, création interdite.
    """
    return not (source == "theses" and "author" not in roles)
