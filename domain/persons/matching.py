"""Règles pures de matching d'authorships à des personnes."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from domain.persons.name_matching import (
    names_compatible,
    parse_raw_author_name,
    same_person_name,
)

ORCID_MATCH_SOURCES = frozenset({"crossref", "openalex", "hal"})
"""Sources dont l'ORCID porté par une authorship est déposé par l'auteur,
donc fiable comme signal de matching personne.

- ``crossref`` : ORCID fourni par l'auteur à l'éditeur lors de la soumission.
- ``openalex`` : ``raw_orcid`` recopié par OpenAlex de la métadonnée brute de
  la source amont (cf. `_extract_openalex_orcid`) — même provenance que
  Crossref.
- ``hal`` : ORCID attaché à l'auteur dans le TEI HAL (``label_xml``).

``wos`` et ``scanr`` sont exclus : leur ORCID est dérivé (matching
algorithmique interne pour WoS, couche de dénormalisation pour ScanR), pas
déposé par l'auteur. Il reste enregistré sur ``person_identifiers`` mais n'est
pas utilisé comme signal de matching.

TODO(scanr-idref-asymetrie) : l'IdRef est matché sans restriction de source
(``decide_match_by_identifier(idref, idref_map)``), donc l'IdRef ScanR EST un
signal, alors qu'il provient du même bloc ``denormalized`` que son ORCID exclu.
Asymétrie possiblement défendable (ScanR est dans le domaine de l'autorité
française IdRef/SUDOC) mais à objectiver : mesurer le taux d'accord IdRef ScanR
vs sources fiables avant de décider de garder, ou de source-garder l'IdRef
comme l'ORCID."""

MAX_AUTHORS_CROSS_SOURCE = 50
"""Au-delà de ce seuil d'auteurs sur une publication, le matching
cross-source est désactivé. Sur les méga-papers (consortiums avec
plusieurs dizaines à plusieurs centaines d'auteurs), les positions
divergent fréquemment entre HAL/OpenAlex/WoS — on récolterait
surtout des faux conflits ou des faux matchings."""


def decide_cross_source_match(
    authorship_source: str,
    last_norm: str,
    first_norm: str,
    candidates: list[tuple[int, str, str, str]],
    *,
    total_author_count: int | None = None,
) -> int | None:
    """Décide si une authorship peut être rattachée à une ``person`` déjà
    associée à la même publication × position auteur via une autre source.

    Le pipeline ingère chaque publi par 1+ sources. Quand par exemple
    HAL a déjà rattaché l'auteur en position 3 à person 42, et qu'on
    rencontre l'authorship OpenAlex en position 3 de la même publi non
    encore rattachée, on peut transmettre le rattachement — à condition
    que le nom soit compatible (garde-fou contre les désalignements de
    position entre sources).

    Paramètres :

    - ``authorship_source`` : source de l'authorship qu'on cherche à
      rattacher. Sert à exclure les candidats de la même source (qui
      ne porteraient aucun signal nouveau).
    - ``last_norm``, ``first_norm`` : nom normalisé de l'authorship.
    - ``candidates`` : liste de tuples
      ``(person_id, last_norm, first_norm, source)`` — les authorships
      déjà rattachées à la même ``(publication_id, author_position)``,
      à fournir via prefetch (typiquement
      ``linked_index[(pub_id, position)]``).
    - ``total_author_count`` (optionnel) : nombre maximal d'auteurs
      sur la publication tous (source × source_authorships) confondus.
      Si > ``MAX_AUTHORS_CROSS_SOURCE``, le matching est court-circuité
      (``None``) — méga-paper, positions non fiables.

    Cascade :

    - Méga-paper (``total_author_count > MAX_AUTHORS_CROSS_SOURCE``)
      → ``None``.
    - Aucun candidat compatible → ``None``.
    - Candidats compatibles convergent tous vers la même ``person_id``
      → cette ``person_id``.
    - Candidats compatibles divergent (≥ 2 ``person_id`` distincts)
      → ``None`` (conflit, pas de match safe).
    """
    if total_author_count is not None and total_author_count > MAX_AUTHORS_CROSS_SOURCE:
        return None
    matched_pid: int | None = None
    for pid, ln, fn, src in candidates:
        if src == authorship_source:
            continue
        if names_compatible(last_norm, first_norm, ln, fn):
            if matched_pid is not None and matched_pid != pid:
                return None
            matched_pid = pid
    return matched_pid


@dataclass(frozen=True)
class NameFormDecision:
    """Décision résultant du lookup d'une authorship dans
    ``person_name_forms``.

    Trois actions possibles : ``match`` (rattacher à une personne
    existante), ``create`` (créer une nouvelle personne), ``skip`` (ne
    rien faire — soit ambiguïté de nom, soit création interdite par
    `allow_create`). Le ``reason`` n'est rempli que pour ``skip`` à des
    fins de logs/stats.
    """

    action: Literal["match", "create", "skip"]
    person_id: int | None = None
    reason: str = ""


def decide_name_form_outcome(
    person_ids: list[int] | None,
    allow_create: bool,
    rejected_person_ids: frozenset[int] = frozenset(),
) -> NameFormDecision:
    """Arbitre la décision de matching après lookup dans
    ``person_name_forms``.

    ``rejected_person_ids`` : personnes déjà rejetées pour la publication
    de l'authorship traitée (store ``rejected_authorships``). Elles sont
    **éliminées** de la liste des candidats avant arbitrage : une paire
    ``(publication, personne)`` rejetée ne doit jamais être recréée par le
    matching. L'élimination peut désambiguïser — si 2 personnes partagent
    la forme de nom mais qu'une est rejetée, il ne reste qu'une candidate
    et l'``ambiguous_name_form`` devient un ``match`` univoque.

    Cascade (sur les candidats restants après élimination) :

    - 1 candidat → ``match`` (rattachement direct).
    - N candidats → ``skip`` avec ``reason="ambiguous_name_form"``
      (homonymes en BDD, on laisse le traitement manuel trancher).
    - 0 candidat alors que la forme était connue (tous rejetés) → ``skip``
      ``ambiguous_name_form`` : on laisse orphelin, on ne crée pas.
    - 0 ``person_ids`` en entrée (forme inconnue) + ``allow_create`` →
      ``create``.
    - Forme inconnue + pas ``allow_create`` → ``skip`` avec
      ``reason="creation_not_allowed"`` (typiquement les rôles
      non-auteur des thèses, cf.
      ``domain.persons.creation.allow_person_creation``).
    """
    if person_ids is None:
        if allow_create:
            return NameFormDecision(action="create")
        return NameFormDecision(action="skip", reason="creation_not_allowed")
    candidates = [pid for pid in person_ids if pid not in rejected_person_ids]
    if len(candidates) == 1:
        return NameFormDecision(action="match", person_id=candidates[0])
    return NameFormDecision(action="skip", reason="ambiguous_name_form")


@dataclass(frozen=True)
class IdentifierMatch:
    """Résultat de la résolution d'un identifiant vers une personne, corroborée par le nom.

    - ``person_id`` : la personne si l'identifiant résout **et** que son nom est
      compatible avec la signature ; ``None`` sinon.
    - ``rejection`` : ``(person_id, target_name)`` quand l'identifiant résolvait vers
      une personne mais que son nom est jugé incompatible avec la signature — le match
      est refusé, et l'info sert à journaliser le rejet (identifiant + les deux formes).
    """

    person_id: int | None = None
    rejection: tuple[int, str] | None = None


def decide_match_by_identifier(
    value: str | None,
    identifier_map: Mapping[str, tuple[int, str, str]],
    signature: str,
    signature_form: str | None,
    name_form_status: Mapping[tuple[str, int], str],
) -> IdentifierMatch:
    """Résout un identifiant (IdRef, ORCID…) vers une ``person_id``, corroboré par le nom.

    ``identifier_map`` est typiquement
    ``{idref: (person_id, last_name_normalized, first_name_normalized)}`` prefetché
    via une query du type ``fetch_idref_to_person_map`` / ``fetch_orcid_to_person_map``,
    déjà filtré sur les statuts non-``rejected``. La fonction est générique : elle
    marche pour n'importe quel id_type indexé sur ``person_identifiers``.

    Corroboration par le nom, du verdict humain au test heuristique :

    1. Le statut du couple ``(signature_form, person_id)`` dans ``person_name_forms``
       (``name_form_status``) tranche en priorité — ``confirmed`` corrobore le match
       sans test (la forme appartient à la personne, y compris un changement de nom),
       ``rejected`` le refuse sans test.
    2. À défaut de verdict (``pending`` ou forme inconnue), on teste la compatibilité
       via ``same_person_name`` : un identifiant porté par une signature étrangère
       (corruption éparse : un ORCID recopié sur le mauvais co-auteur) ou par un
       homonyme de patronyme est refusé, mais une **variante de graphie du propriétaire
       lui-même** (« abdelmouhcine » pour « abdel mouhcine ») corrobore et se rattache —
       ce qui évite de la rejeter puis d'en créer un doublon au canal nominal. Une
       signature trop pauvre (réduite au nom de famille) reste compatible (sous-ensemble
       de tokens) et n'est donc pas refusée.

    Un refus est matérialisé dans ``rejection`` pour journalisation.
    """
    if not value:
        return IdentifierMatch()
    target = identifier_map.get(value)
    if target is None:
        return IdentifierMatch()
    person_id, target_ln, target_fn = target

    verdict = name_form_status.get((signature_form, person_id)) if signature_form else None
    if verdict == "confirmed":
        return IdentifierMatch(person_id=person_id)
    if verdict == "rejected":
        return IdentifierMatch(rejection=(person_id, f"{target_fn} {target_ln}".strip()))

    sig_last, sig_first = parse_raw_author_name(signature)
    if same_person_name(sig_last, sig_first, target_ln, target_fn):
        return IdentifierMatch(person_id=person_id)
    return IdentifierMatch(rejection=(person_id, f"{target_fn} {target_ln}".strip()))


def form_matches_person(
    form: str,
    last_name: str,
    first_name: str,
    confirmed_forms: Iterable[str] = (),
) -> bool:
    """La forme de nom ``form`` désigne-t-elle la personne ?

    Vrai si ``form`` est compatible (``names_compatible``, comparaison par tokens) avec le
    nom-prénom de la personne, ou avec l'une de ses formes de nom **confirmées** (un nom
    validé par un humain que le nom-prénom canonique ne recouvre pas, changement de nom
    inclus).

    Sert à arbitrer un conflit d'attribution d'identifiant : la forme majoritaire des
    signatures portant une valeur (le *consensus*, agrégat ordre-indépendant fourni par le
    caller) est confrontée au propriétaire actuel et au candidat en conflit — l'identifiant
    se transfère vers le candidat si, et seulement si, le consensus le désigne, lui et pas
    le propriétaire.
    """
    if names_compatible(form, "", last_name, first_name):
        return True
    return any(names_compatible(form, "", cf, "") for cf in confirmed_forms)


@dataclass(frozen=True)
class PersonMatchDecision:
    """Décision de la cascade de matching unifiée.

    ``reason`` identifie le signal qui a tranché (``"orcid"`` /
    ``"hal_person_id"`` / ``"idref"`` / ``"cross_source"`` /
    ``"single_name"`` pour les ``match`` ; ``"new"`` pour ``create`` ;
    ``"ambiguous_name_form"`` / ``"creation_not_allowed"`` pour ``skip``).
    Utilisable côté logs et stats par le caller.
    """

    action: Literal["match", "create", "skip"]
    person_id: int | None = None
    reason: str = ""


def decide_person_match(
    *,
    orcid_match: int | None,
    hal_match: int | None,
    idref_match: int | None,
    cross_source_match: int | None,
    name_form_outcome: NameFormDecision,
    rejected_person_ids: frozenset[int] = frozenset(),
) -> PersonMatchDecision:
    """Cascade unifiée de matching personne, du signal le plus fiable au moins fiable.

    Hiérarchie par fiabilité de provenance :

    1. **ORCID déposé par l'auteur** (``orcid_match``) — ORCID issu d'une
       source à dépôt auteur (``ORCID_MATCH_SOURCES``), borné côté caller.
    2. **`hal_person_id`** (``hal_match``) — compte HAL de l'auteur,
       attaché à la signature dans le TEI HAL.
    3. **IdRef** (``idref_match``).
    4. **Cross-source** (``cross_source_match``) — match par
       ``(publication_id, author_position)`` avec une authorship d'une
       autre source et nom compatible. En dernier recours parmi les
       signaux non-nominaux : inopérant au bootstrap (suppose des
       matchings préexistants), il vient donc après les identifiants.
    5. **`person_name_forms`** (``name_form_outcome``) — délègue au
       résultat de ``decide_name_form_outcome`` (match / create / skip
       selon ambiguïté et politique de création).

    ``rejected_person_ids`` : personnes déjà rejetées pour la publication
    de l'authorship (store ``rejected_authorships``). Un match d'identifiant
    ou cross-source pointant vers une personne rejetée est **annulé** — la
    cascade retombe au signal suivant, et faute de mieux laisse l'authorship
    orpheline plutôt que de recréer le lien rejeté. Le tiroir name form est
    déjà gardé en amont : ``name_form_outcome`` doit être calculé avec le
    même ``rejected_person_ids`` (cf. ``decide_name_form_outcome``).

    Pure, testable sans BDD : les paramètres sont précalculés par le
    caller via prefetch.
    """
    if orcid_match is not None and orcid_match not in rejected_person_ids:
        return PersonMatchDecision(action="match", person_id=orcid_match, reason="orcid")
    if hal_match is not None and hal_match not in rejected_person_ids:
        return PersonMatchDecision(action="match", person_id=hal_match, reason="hal_person_id")
    if idref_match is not None and idref_match not in rejected_person_ids:
        return PersonMatchDecision(action="match", person_id=idref_match, reason="idref")
    if cross_source_match is not None and cross_source_match not in rejected_person_ids:
        return PersonMatchDecision(
            action="match", person_id=cross_source_match, reason="cross_source"
        )
    if name_form_outcome.action == "match":
        return PersonMatchDecision(
            action="match",
            person_id=name_form_outcome.person_id,
            reason="single_name",
        )
    if name_form_outcome.action == "create":
        return PersonMatchDecision(action="create", reason="new")
    return PersonMatchDecision(action="skip", reason=name_form_outcome.reason)
