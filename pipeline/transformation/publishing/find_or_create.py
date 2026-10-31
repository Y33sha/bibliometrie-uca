"""Recherche et création des conteneurs d'un enregistrement source et de son éditeur : revue, monographie, éditeur.

Les normaliseurs des sources appellent ces fonctions pour chaque enregistrement source.
"""

import logging
from collections.abc import Sequence
from typing import NamedTuple

from domain.monographs.matching import choose_monograph
from domain.normalize import normalize_text, to_plain_text
from domain.publications.identifiers import ISBN, issn_rejection_reason
from domain.publishers.names import publisher_name_key
from domain.serials.containers import SeriesDescription, VolumeDescription
from domain.serials.issns import IssnStatus, SerialIssn, received_issns
from domain.serials.serial import OaModel
from pipeline.transformation.publishing.containers import ContainerStores
from pipeline.transformation.publishing.monographs.store import MonographStore
from pipeline.transformation.publishing.publishers.store import PublisherStore
from pipeline.transformation.publishing.serials.store import SerialStore

logger = logging.getLogger(__name__)


def find_or_create_publisher(
    name: str | None,
    *,
    openalex_id: str | None = None,
    repo: PublisherStore,
) -> int | None:
    """Trouve ou crée un éditeur. Renvoie son id, ou `None` si le nom est vide.

    Recherche par `openalex_id`, puis par la clé de nom (`publisher_name_key`) parmi les formes de nom. Sans correspondance, l'éditeur est créé avec sa forme de nom.
    """
    if not name:
        return None

    # 1. Par openalex_id
    if openalex_id:
        publisher_id = repo.find_publisher_by_openalex_id(openalex_id)
        if publisher_id:
            name_key = publisher_name_key(to_plain_text(name))
            if name_key:
                repo.add_publisher_name_form(publisher_id, name_key)
            return publisher_id

    # 2-3. Par forme de nom, ou création, puis attribution de l'`openalex_id` à l'éditeur trouvé ou créé.
    matched = match_or_create_publisher(name, repo=repo)
    if matched is None:
        return None
    publisher_id, _ = matched
    if openalex_id:
        repo.set_publisher_openalex_id_if_missing(publisher_id, openalex_id)
    return publisher_id


def match_or_create_publisher(name: str, *, repo: PublisherStore) -> tuple[int, bool] | None:
    """Trouve par sa clé de nom, ou crée, l'éditeur désigné par `name`. Renvoie `(id, created)`, ou `None` si le nom est vide une fois normalisé.

    Le nom affiché, le nom normalisé et la clé dérivent tous du nom mis à plat (cf. `find_or_create_serial`).
    """
    name = to_plain_text(name)
    name_normalized = normalize_text(name)
    name_key = publisher_name_key(name)
    if not name_normalized or not name_key:
        return None
    return repo.match_or_create_by_name_form(name, name_normalized, name_key)


def find_or_create_serial(
    title: str | None,
    *,
    issns: Sequence[SerialIssn] = (),
    publisher_id: int | None = None,
    openalex_id: str | None = None,
    oa_model: OaModel | None = None,
    repo: SerialStore,
) -> int | None:
    """Trouve ou crée une revue. Renvoie son id, ou `None` si le titre est vide.

    Recherche par `openalex_id`, puis par chacun des ISSN valides, puis par titre normalisé parmi les formes de nom. Sans correspondance, la revue est créée.

    La revue trouvée reçoit les métadonnées et les ISSN qui lui manquent. Le titre reçu devient une forme de nom, pour les recherches par titre suivantes. Un ISSN invalide est journalisé et gardé au statut `malformed`. L'éditeur de la revue se calcule d'après ses publications.

    Args:
        publisher_id: éditeur de l'enregistrement source ; restreint la recherche par titre.
    """
    if not title:
        return None

    # La clé de comparaison et le titre affiché dérivent du texte brut : un titre reçu avec des entités (`Wood &amp; Fire Safety`) retrouve la même revue que reçu en clair.
    title = to_plain_text(title)
    title_normalized = normalize_text(title)
    issns = received_issns(issns)
    for row in issns:
        if row.status is IssnStatus.MALFORMED:
            # Ligne de détail : le terminal la masque, le journal la garde.
            logger.warning(
                "ISSN mal formé (revue %r) : %r — %s, valeur gardée telle que reçue",
                title,
                row.issn,
                issn_rejection_reason(row.issn),
                extra={"detail": True},
            )

    def _match_and_enrich(serial_id: int, *, with_openalex: bool = True) -> int:
        """Enrichit la revue trouvée et enregistre son titre comme forme de nom, pour les recherches par titre suivantes. Renvoie son id."""
        repo.enrich_serial(
            serial_id,
            openalex_id=openalex_id if with_openalex else None,
            oa_model=oa_model if with_openalex else None,
        )
        repo.add_serial_issns(serial_id, issns)
        repo.add_serial_name_form(serial_id, title_normalized, publisher_id)
        return serial_id

    def _find_or_create() -> int:
        # 1. Par openalex_id
        if openalex_id:
            jid = repo.find_serial_by_openalex_id(openalex_id)
            if jid:
                # La revue trouvée a déjà cet `openalex_id` et son modèle open access.
                return _match_and_enrich(jid, with_openalex=False)
            # `openalex_id` inconnu : la recherche continue, pour le rattacher à une revue existante.

        # 2. Par chacun des ISSN valides, parmi les ISSN des revues
        for row in issns:
            if row.status is IssnStatus.MALFORMED:
                continue
            jid = repo.find_serial_by_issn_any(row.issn)
            if jid:
                return _match_and_enrich(jid)

        # 3. Par forme de nom, priorité aux revues à ISSN électronique actif. Un titre vide une fois normalisé (alphabet non latin, symboles) ne désigne aucune revue.
        jid = (
            repo.find_serial_by_name_form(title_normalized, publisher_id)
            if title_normalized
            else None
        )
        if jid:
            repo.enrich_serial(jid, openalex_id=openalex_id, oa_model=oa_model)
            repo.add_serial_issns(jid, issns)
            return jid

        # 4. Création, avec la forme de nom
        created = repo.create_serial(title=title, openalex_id=openalex_id, oa_model=oa_model)
        repo.add_serial_issns(created, issns)
        repo.add_serial_name_form(created, title_normalized, publisher_id)
        return created

    return _find_or_create()


def _isbns(values: Sequence[str]) -> list[str]:
    """Renvoie les ISBN-13 valides de `values`, dans l'ordre, sans doublon."""
    found: list[str] = []
    for value in values:
        isbn = ISBN.try_parse(value)
        if isbn is not None and isbn.value not in found:
            found.append(isbn.value)
    return found


def find_or_create_monograph(
    title: str | None,
    *,
    isbns: Sequence[str] = (),
    eisbns: Sequence[str] = (),
    proceedings: bool,
    year: int | None = None,
    publisher_id: int | None = None,
    serial_id: int | None = None,
    repo: MonographStore,
) -> int | None:
    """Trouve ou crée une monographie. Renvoie son id, ou `None` sans ISBN connu ni titre, ou si plusieurs volumes de ce titre sont candidats.

    Recherche par ISBN, papier ou électronique, puis par titre normalisé. `choose_monograph` choisit parmi les monographies de ce titre, selon l'éditeur et les ISBN. La monographie trouvée reçoit les champs qui lui manquent.

    Args:
        serial_id: collection, quand un ISSN la désigne.
    """
    paper = _isbns(isbns)
    electronic = [isbn for isbn in _isbns(eisbns) if isbn not in paper]
    isbn = paper[0] if paper else None
    eisbn = electronic[0] if electronic else None

    def enrich(monograph_id: int) -> int:
        repo.enrich_monograph(
            monograph_id,
            proceedings=proceedings,
            year=year,
            isbn=isbn,
            eisbn=eisbn,
            publisher_id=publisher_id,
            serial_id=serial_id,
        )
        return monograph_id

    for value in (*paper, *electronic):
        if (found := repo.find_monograph_by_isbn(value)) is not None:
            return enrich(found)

    title = to_plain_text(title) if title else ""
    title_normalized = normalize_text(title)
    if not title_normalized:
        return None
    choice = choose_monograph(
        repo.find_monographs_by_title(title_normalized),
        publisher_id=publisher_id,
        has_isbn=bool(isbn or eisbn),
    )
    if choice.monograph_id is not None:
        return enrich(choice.monograph_id)
    if not choice.create:
        return None
    return repo.create_monograph(
        title=title,
        title_normalized=title_normalized,
        proceedings=proceedings,
        year=year,
        isbn=isbn,
        eisbn=eisbn,
        publisher_id=publisher_id,
        serial_id=serial_id,
    )


class Containers(NamedTuple):
    """Entrée de `serials` et monographie d'un enregistrement source."""

    serial_id: int | None
    monograph_id: int | None


def _find_series(
    series: SeriesDescription, publisher_id: int | None, stores: ContainerStores
) -> int | None:
    """Renvoie l'entrée de `serials` d'une série. Une série sans titre est seulement cherchée par ses ISSN valides."""
    if series.title:
        return find_or_create_serial(
            series.title,
            issns=series.issns,
            publisher_id=publisher_id,
            openalex_id=series.openalex_id,
            oa_model=series.oa_model,
            repo=stores.serials,
        )
    for row in series.issns:
        if row.status is not IssnStatus.MALFORMED and (
            serial_id := stores.serials.find_serial_by_issn_any(row.issn)
        ):
            return serial_id
    return None


def find_or_create_containers(
    series: SeriesDescription | None,
    volume: VolumeDescription | None,
    *,
    publisher_id: int | None,
    stores: ContainerStores,
) -> Containers:
    """Trouve ou crée les conteneurs d'un enregistrement source, séparés par `determine_container_type`.

    L'enregistrement source reçoit sa série comme entrée de `serials`, et son volume comme monographie reliée à cette série. La série d'un volume a toujours un ISSN. L'étape de rattachement de `publishing` reconnaît les séries sans ISSN.
    """
    serial_id = _find_series(series, publisher_id, stores) if series else None
    if volume is None:
        return Containers(serial_id, None)
    monograph_id = find_or_create_monograph(
        volume.title,
        isbns=volume.isbns,
        eisbns=volume.eisbns,
        proceedings=volume.proceedings,
        year=volume.year,
        publisher_id=publisher_id,
        serial_id=serial_id,
        repo=stores.monographs,
    )
    return Containers(serial_id, monograph_id)
