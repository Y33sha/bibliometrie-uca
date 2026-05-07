"""Règles de politique de création de personnes.

Module pensé pour s'étendre aux autres invariants de création
(``should_create_source_person`` unifié HAL/ScanR/theses, etc.).
À terme, regroupable avec ``merge.py`` selon la décision de
granularité « merge + dedup + create » du chantier
``regles-metier-domain``.
"""


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
