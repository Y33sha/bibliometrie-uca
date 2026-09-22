"""Ports d'accès pipeline à la table `journals`.

Des contrats étroits, un par consommateur du pipeline, tous servis par un même adapter `PgJournalGatewayQueries` (la table est mono-adapter, cf. `infrastructure/pipeline/journals.py`) :

- `JournalFindOrCreateQueries` : lookup + création + enrichissement à la création, pour `find_or_create_journal` (appelé par les normaliseurs de sources) ;
- `JournalOpenAlexEnrichmentQueries` : file des revues à typer + écriture APC / journal_type, pour l'enrichissement OpenAlex ;
- `JournalSudocQueries` : file des revues à vérifier + écriture des ISSN vérifiés, pour la vérification dans le Sudoc ;
- `JournalDoajQueries` : index ISSN + drapeau `is_in_doaj`, pour l'import du dump DOAJ.

L'édition dans l'administration et la fusion ont leur propre port, `application/ports/repositories/journal_repository.py`.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import NamedTuple, Protocol

from domain.journals.doi_namespaces import DoiNamespace
from domain.journals.issns import JournalIssn
from domain.journals.journal import JournalType, OaModel
from domain.types import JsonValue


class JournalIssnRow(NamedTuple):
    """Un ISSN valide d'une revue, pour l'index par ISSN."""

    journal_id: int
    issn: str


class JournalFindOrCreateQueries(Protocol):
    """Trouve ou crée une revue à partir des métadonnées d'une source (consommé par les normaliseurs)."""

    def add_journal_name_form(
        self,
        journal_id: int,
        form_normalized: str,
        publisher_id: int | None,
    ) -> None:
        """Ajoute une forme de nom normalisée pour une revue, si absente (idempotent). No-op si `form_normalized` est vide."""
        ...

    def find_journal_by_name_form(
        self,
        form_normalized: str,
        publisher_id: int | None,
    ) -> int | None:
        """Cherche un `journal_id` par forme de nom normalisée. En cas d'ambiguïté, privilégie les revues à ISSN électronique actif. `publisher_id` fourni : restreint aux formes de cet éditeur ou sans éditeur."""
        ...

    def find_journal_by_openalex_id(self, openalex_id: str) -> int | None: ...

    def find_journal_by_issn_any(self, issn_value: str) -> int | None:
        """Cherche une revue qui porte `issn_value`, quel que soit son statut, hors valeur mal formée. Une revue où l'ISSN est actif passe en premier."""
        ...

    def enrich_journal(
        self,
        journal_id: int,
        *,
        publisher_id: int | None = None,
        openalex_id: str | None = None,
        oa_model: OaModel | None = None,
    ) -> None:
        """Complète une revue existante avec les champs non nuls fournis, en COALESCE par champ : une valeur déjà en place est conservée."""
        ...

    def add_journal_issns(self, journal_id: int, issns: Sequence[JournalIssn]) -> None:
        """Ajoute à la revue les ISSN qu'elle ne porte pas, sans date de vérification : ils attendent la vérification Sudoc. Une ligne sans revue de même ISSN est rattachée à la revue. Un ISSN déjà porté garde ses données ; il reçoit seulement le support qui lui manque."""
        ...

    def create_journal(
        self,
        *,
        title: str,
        publisher_id: int | None,
        openalex_id: str | None,
        oa_model: OaModel | None,
    ) -> int:
        """Insère une revue et retourne son `id`. `title_normalized` est dérivé de `title`."""
        ...


class JournalOpenAlexEnrichmentQueries(Protocol):
    """Enrichit les revues depuis OpenAlex Sources : typage des revues indéterminées et écriture APC."""

    def find_journals_of_unknown_type(self, *, limit: int | None = None) -> list[tuple[int, str]]:
        """`(id, openalex_id)` des revues au `journal_type` indéterminé qui portent un `openalex_id`, à typer via OpenAlex. Le type étant stable par revue, une revue typée sort de la file. `limit` cape le run."""
        ...

    def update_journal_apc(
        self,
        journal_id: int,
        *,
        apc_amount: float | None = None,
        apc_currency: str | None = None,
    ) -> None:
        """Met à jour le montant et la devise d'APC. COALESCE : un argument `None` laisse la valeur en place."""
        ...

    def set_journal_type(self, journal_id: int, journal_type: JournalType) -> None:
        """Pose le `journal_type` d'une revue. Écriture directe, sans requalification des publications — c'est l'édition admin, elle, qui rejoue les corrections de `doc_type`."""
        ...


class JournalSudocRow(NamedTuple):
    """Une revue à vérifier dans le Sudoc : son titre, ses ISSN et les ISSN que portent ses enregistrements sans figurer parmi les siens."""

    id: int
    title: str
    issns: tuple[JournalIssn, ...]
    document_issns: tuple[str, ...] = ()
    journal_type: JournalType = JournalType.UNKNOWN


class JournalTitleRow(NamedTuple):
    """Une revue et son titre."""

    id: int
    title: str


class JournalTitleTypeRow(NamedTuple):
    """Une revue, son titre et son type."""

    id: int
    title: str
    journal_type: JournalType


class JournalSudocQueries(Protocol):
    """Vérification des ISSN des revues dans le Sudoc."""

    def find_journals_to_check_in_sudoc(self, also: Sequence[int] = ()) -> list[JournalSudocRow]:
        """Revues dont un ISSN n'est pas vérifié dans le Sudoc, revues dont un enregistrement porte un ISSN valide absent de leurs ISSN et encore jamais vérifié, et revues `also`."""
        ...

    def find_titles_of_journals_with_issn(self) -> list[JournalTitleTypeRow]:
        """Les revues qui portent un ISSN actif, avec leur titre et leur type."""
        ...

    def record_sudoc_check(
        self,
        journal_id: int,
        *,
        issns: Sequence[JournalIssn],
        released: Sequence[JournalIssn],
        checked_at: datetime,
        title: str | None = None,
    ) -> None:
        """Écrit les ISSN vérifiés d'une revue, datés de `checked_at`. `released` : ISSN d'une autre publication, retirés de la revue et gardés sans revue. Un `title` devient le titre de la revue, et une de ses formes de nom."""
        ...


class JournalMergeGroup(NamedTuple):
    """Revues en double. La cible de la fusion vient en premier."""

    key: str
    """Ce que les revues partagent : ISSN-L ou titre normalisé."""
    journal_ids: tuple[int, ...]


class JournalSummary(NamedTuple):
    """Ce que le journal du pipeline dit d'une revue."""

    id: int
    title: str
    publisher: str | None
    issns: tuple[str, ...]
    """ISSN actifs."""


class JournalIssnGroup(NamedTuple):
    """Revues où le même ISSN est actif. La cible de la fusion vient en premier."""

    issn: str
    journals: tuple[JournalTitleRow, ...]


class JournalMergeCandidate(NamedTuple):
    """Une revue candidate à une fusion, avec ce qui départage la cible."""

    id: int
    title: str
    issns: frozenset[str]
    """ISSN actifs."""
    pub_count: int


class JournalPublicationPair(NamedTuple):
    """Deux revues que des enregistrements d'une même publication portent."""

    first: JournalMergeCandidate
    second: JournalMergeCandidate
    publications: int
    """Nombre de publications communes."""


class JournalMergeQueries(Protocol):
    """Fusion des revues séparées à tort."""

    def find_journals_sharing_issnl(self) -> list[JournalMergeGroup]:
        """Groupes de revues vérifiées dans le Sudoc qui partagent leur ISSN-L. La revue qui porte le plus de publications vient en premier, puis la plus petite par identifiant."""
        ...

    def find_journals_sharing_active_issn(self) -> list[JournalIssnGroup]:
        """Groupes de revues vérifiées dans le Sudoc où le même ISSN est actif, dans le même ordre."""
        ...

    def find_journals_sharing_an_inactive_issn(self) -> list[JournalMergeGroup]:
        """Paires de revues vérifiées dans le Sudoc dont l'une porte, inactif, un ISSN actif dans l'autre. La revue dont le premier document est le plus tardif vient en premier, puis celle qui porte le plus de publications."""
        ...

    def find_same_title_duplicates(self) -> list[JournalMergeGroup]:
        """Paires de revues seules à porter leur titre normalisé, dont au moins une sans ISSN, et dont les enregistrements partagent un préfixe DOI. La revue qui porte le plus de publications vient en premier, puis celle qui a un ISSN."""
        ...

    def find_journals_sharing_a_publication(self) -> list[JournalPublicationPair]:
        """Paires de revues que les enregistrements d'une même publication portent. Les paires qui partagent le plus de publications viennent en premier."""
        ...

    def describe_journals(self, journal_ids: Sequence[int]) -> dict[int, JournalSummary]:
        """Titre, éditeur et ISSN de chaque revue, pour la journalisation des fusions."""
        ...


class JournalRecordTypes(NamedTuple):
    """Les documents d'une revue : `(source, type brut)` de chacun."""

    journal_id: int
    records: tuple[tuple[str, str | None], ...]


class JournalTitleIssnRow(NamedTuple):
    """Titre d'une revue, et présence d'un ISSN actif."""

    id: int
    title: str
    has_issn: bool


class JournalProceedingsTypingQueries(Protocol):
    """Typage en recueil d'actes."""

    def find_record_types_of_unknown_journals(self) -> list[JournalRecordTypes]:
        """Les revues de type `unknown` qui ont au moins un document, avec le type brut de chaque document."""
        ...

    def find_titles_of_non_proceedings_journals(self) -> list[JournalTitleIssnRow]:
        """Les revues d'un autre type que `proceedings`, avec leur titre et la présence d'un ISSN."""
        ...

    def describe_journals(self, journal_ids: Sequence[int]) -> dict[int, JournalSummary]:
        """Titre, éditeur et ISSN de chaque revue, pour la journalisation."""
        ...

    def set_journal_type(self, journal_id: int, journal_type: JournalType) -> None:
        """Pose le `journal_type` d'une revue."""
        ...


class DoiJournalRow(NamedTuple):
    """Un DOI et la revue que lui donne sa source, avec le type de cette revue."""

    doi: str
    journal_id: int
    journal_type: JournalType


class JournalDoiNamespaceQueries(Protocol):
    """Calcul des espaces de noms DOI des revues."""

    def find_doi_journal_pairs(self) -> list[DoiJournalRow]:
        """Le couple (DOI, revue) de chaque enregistrement. Une revue posée par son espace de noms est exclue : elle ne témoigne pas pour lui."""
        ...

    def store_doi_namespaces(self, namespaces: Sequence[DoiNamespace]) -> None:
        """Vide `journal_doi_namespaces`, puis y écrit `namespaces`."""
        ...


class JournalCleanupQueries(Protocol):
    """Suppression des revues vides."""

    def delete_empty_journals(self) -> list[JournalSummary]:
        """Supprime les revues sans enregistrement, sans publication, sans monographie et sans paiement APC, et les rend."""
        ...


class JournalDoajQueries(Protocol):
    """Import du dump DOAJ : index ISSN des revues et pose du drapeau `is_in_doaj`."""

    def find_journal_issn_index(self) -> list[JournalIssnRow]:
        """Les ISSN valides des revues, quel que soit leur statut : matière de l'index ISSN → revue à l'import du dump DOAJ."""
        ...

    def update_journal_doaj(
        self,
        journal_id: int,
        *,
        payload: Mapping[str, JsonValue] | None,
        imported_at: datetime,
        is_in_doaj: bool,
    ) -> None:
        """Pose `doaj_payload`, `doaj_imported_at` et `is_in_doaj` en bloc.

        Utilisé par l'import du dump DOAJ pour les revues matchées (`is_in_doaj=True` + payload). Le cas « absente du dump » est traité en bloc par `reset_is_in_doaj` (FALSE global avant re-pose).
        """
        ...

    def reset_is_in_doaj(self) -> int:
        """Efface le drapeau `is_in_doaj` de toutes les revues qui le portent, le dump DOAJ faisant autorité — l'import le re-pose ensuite sur les revues matchées. Retourne le nombre de drapeaux effacés."""
        ...

    def doaj_last_import_at(self) -> datetime | None:
        """Date du dernier import DOAJ (`max(doaj_imported_at)`), `None` si jamais importé. Commande la staleness du téléchargement du dump."""
        ...
