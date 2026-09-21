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
from domain.journals.journal import JournalType, OaModel
from domain.types import JsonValue


class JournalIssnRow(NamedTuple):
    """Une revue indexable par ISSN : son `id` et ses trois formes d'ISSN (au moins une non-nulle)."""

    id: int
    issn: str | None
    eissn: str | None
    issnl: str | None


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
        """Cherche un `journal_id` par forme de nom normalisée. En cas d'ambiguïté, privilégie les revues à eISSN. `publisher_id` fourni : restreint aux formes de cet éditeur ou sans éditeur."""
        ...

    def find_journal_by_openalex_id(self, openalex_id: str) -> int | None: ...

    def find_journal_by_issn_any(self, issn_value: str) -> int | None:
        """Cherche une revue dont l'un des trois champs ISSN (`issn`, `eissn`, `issnl`) ou l'un des ISSN rejetés vaut `issn_value`. Une revue qui porte l'ISSN dans ses trois champs passe en premier."""
        ...

    def enrich_journal(
        self,
        journal_id: int,
        *,
        issn: str | None = None,
        eissn: str | None = None,
        publisher_id: int | None = None,
        openalex_id: str | None = None,
        oa_model: OaModel | None = None,
    ) -> None:
        """Complète une revue existante avec les champs non nuls fournis, en COALESCE par champ : une valeur déjà en place est conservée.

        Un ISSN que la revue porte déjà dans `issn` ou `eissn`, ou qu'elle a rejeté, n'est pas réécrit dans une colonne. Un ISSN nouveau remet la revue à vérifier dans le Sudoc.
        """
        ...

    def add_rejected_issns(self, journal_id: int, values: Sequence[str]) -> None:
        """Ajoute des ISSN invalides à `rejected_issns` de la revue, sans doublon. Une valeur nouvelle remet la revue à vérifier dans le Sudoc."""
        ...

    def create_journal(
        self,
        *,
        title: str,
        issn: str | None,
        eissn: str | None,
        issnl: str | None,
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
    """Une revue à vérifier dans le Sudoc : son titre, ses trois formes d'ISSN, ses ISSN rejetés et les ISSN que portent ses enregistrements sans figurer parmi les précédents."""

    id: int
    title: str
    issn: str | None
    eissn: str | None
    issnl: str | None
    rejected_issns: tuple[str, ...]
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
        """Revues jamais vérifiées dans le Sudoc (`sudoc_checked_at` nul) qui portent au moins un ISSN, valide ou rejeté, revues dont un enregistrement porte un ISSN absent de leurs ISSN, et revues `also`."""
        ...

    def find_titles_of_journals_with_issn(self) -> list[JournalTitleTypeRow]:
        """Les revues qui portent un ISSN dans `issn`, `eissn` ou `issnl`, avec leur titre et leur type."""
        ...

    def record_sudoc_check(
        self,
        journal_id: int,
        *,
        issn: str | None,
        eissn: str | None,
        issnl: str | None,
        rejected_issns: Sequence[str],
        checked_at: datetime,
        title: str | None = None,
    ) -> None:
        """Écrit les ISSN vérifiés d'une revue et la date de vérification. Un `title` remplace le titre de la revue, dont il devient aussi une forme de nom."""
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
    issn: str | None
    eissn: str | None


class JournalIssnGroup(NamedTuple):
    """Revues qui portent le même ISSN dans `issn` ou `eissn`. La cible de la fusion vient en premier."""

    issn: str
    journals: tuple[JournalTitleRow, ...]


class JournalMergeCandidate(NamedTuple):
    """Une revue candidate à une fusion, avec ce qui départage la cible."""

    id: int
    title: str
    issns: frozenset[str]
    """Valeurs des colonnes `issn`, `eissn` et `issnl`."""
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

    def find_journals_sharing_column_issn(self) -> list[JournalIssnGroup]:
        """Groupes de revues vérifiées dans le Sudoc qui portent le même ISSN dans `issn` ou `eissn`, dans le même ordre."""
        ...

    def find_journals_sharing_a_rejected_issn(self) -> list[JournalMergeGroup]:
        """Paires de revues vérifiées dans le Sudoc dont l'une porte parmi ses ISSN rejetés un ISSN que l'autre porte dans ses colonnes. La revue dont le premier document est le plus tardif vient en premier, puis celle qui porte le plus de publications."""
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
    """Titre d'une revue, et présence d'un ISSN dans `issn`, `eissn` ou `issnl`."""

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
        """Les revues portant au moins un ISSN — matière de l'index ISSN → revue à l'import du dump DOAJ."""
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
