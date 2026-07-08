"""Suggestion de pays par adresse via un automate Aho-Corasick inversé.

Pour les adresses sans pays, on cherche dans le pool des adresses *avec* pays
celles dont le `normalized_text` contient la cible comme sous-chaîne, et on
retient le ou les pays les plus fréquents parmi elles.

Au lieu d'une recherche trigram par cible (une requête SQL par adresse, lente),
on **inverse la boucle** : les cibles deviennent les motifs d'un automate
Aho-Corasick, le pool devient les textes. Un seul passage sur le pool ressort,
pour chaque adresse-pool, toutes les cibles qu'elle contient — coût indépendant
du nombre de cibles. L'automate est construit par batch de cibles pour borner
la mémoire ; le pool est rescanné à chaque batch.

L'orchestrateur `run` alimente `addresses.suggested_countries` (confirmation manuelle attendue) ;
il ne dépend que du port `CountryQueries` et de l'automate ci-dessous. Il commite par batch : la
progression est ainsi durable si le run est interrompu, et le WAL borné (le stock complet se traite
en ~1-2 min, en plusieurs batches).
"""

import logging
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence

import ahocorasick
from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.countries import CountryQueries

BATCH_SIZE = 50000


class CountrySuggester:
    """Suggère un pays par cible (match sous-chaîne) via un automate sur un batch de cibles.

    `targets` : `(address_id, normalized_text)` des adresses sans pays à suggérer.
    Plusieurs adresses peuvent partager le même `normalized_text` (dédoublonnage
    par md5(raw_text), pas par texte normalisé) : chaque motif porte la liste des
    ids concernés.
    """

    def __init__(self, targets: list[tuple[int, str]]) -> None:
        by_text: dict[str, list[int]] = defaultdict(list)
        for target_id, normalized_text in targets:
            if normalized_text:
                by_text[normalized_text].append(target_id)
        self._automaton = ahocorasick.Automaton()
        for normalized_text, ids in by_text.items():
            self._automaton.add_word(normalized_text, ids)
        self._empty = not by_text
        if not self._empty:
            self._automaton.make_automaton()

    def suggest(self, pool: Iterable[tuple[str, Sequence[str] | None]]) -> dict[int, list[str]]:
        """Balaie le pool `(normalized_text, countries)` et rend `{target_id: [pays]}`.

        Par cible matchée : le ou les pays les plus fréquents (ex-aequo triés)
        parmi les adresses-pool qui la contiennent comme sous-chaîne. Une adresse
        sans aucun match est absente du résultat (le caller lui pose un array vide).
        Chaque adresse-pool ne compte qu'une fois par cible, quelles que soient
        les positions du match.
        """
        counts: dict[int, Counter[str]] = defaultdict(Counter)
        if not self._empty:
            for normalized_text, countries in pool:
                if not normalized_text or not countries:
                    continue
                codes = [c.strip() for c in countries if c and c.strip()]
                if not codes:
                    continue
                matched: set[int] = set()
                for _end, ids in self._automaton.iter(normalized_text):
                    matched.update(ids)
                for target_id in matched:
                    counts[target_id].update(codes)

        result: dict[int, list[str]] = {}
        for target_id, counter in counts.items():
            top = max(counter.values())
            result[target_id] = sorted({code for code, n in counter.items() if n == top})
        return result


def run(
    conn: Connection,
    queries: CountryQueries,
    logger: logging.Logger,
    *,
    retry_empty: bool = False,
    batch_size: int = BATCH_SIZE,
) -> PhaseMetrics:
    """Suggère un pays pour les adresses sans pays, dans `addresses.suggested_countries`.

    `retry_empty` (mode `full`) : traite les nouvelles **+ les vides** (échecs précédents `= []`),
    pour réessayer au cas où le pool aurait grossi, sans recalculer les suggestions positives (qui
    changent rarement et coûtent cher). Sinon (incrémental) : seulement les nouvelles
    (`suggested_countries IS NULL`). `seen` = adresses traitées, `new` = adresses avec suggestion.
    """
    counts = queries.count_suggest_eligible(conn)
    total = counts.eligible + (counts.empty_attempted if retry_empty else 0)
    mode = "retry-vides" if retry_empty else "incrémental"
    logger.info(
        "%d adresses à traiter (mode %s, batch_size=%d) — %d déjà avec suggestion, "
        "%d déjà tentées sans match, %d trop courtes",
        total,
        mode,
        batch_size,
        counts.has_suggestion,
        counts.empty_attempted,
        counts.too_short,
    )
    if total == 0:
        logger.info("Rien à faire.")
        return PhaseMetrics()

    logger.info("Chargement du pool (adresses avec pays)...")
    pool = queries.load_country_pool(conn)
    logger.info("  %d adresses dans le pool", len(pool))

    processed = 0
    found = 0
    after_id = 0
    t0 = time.time()
    while True:
        targets = queries.fetch_suggest_targets_chunk(
            conn, after_id=after_id, limit=batch_size, retry_empty=retry_empty
        )
        if not targets:
            break
        after_id = targets[-1][0]  # tranche triée par id

        suggestions = CountrySuggester(targets).suggest(pool)
        rows = [(addr_id, suggestions.get(addr_id, [])) for addr_id, _ in targets]
        queries.write_countries(conn, rows, target_column="suggested_countries")
        conn.commit()

        processed += len(targets)
        found += sum(1 for _, sug in rows if sug)
        elapsed = time.time() - t0
        rate = processed / elapsed if elapsed > 0 else 0
        remaining = (total - processed) / rate if rate > 0 else 0
        logger.info(
            "  %d/%d traités (%d avec suggestion, %.0fs, ~%.0fs restantes)",
            processed,
            total,
            found,
            elapsed,
            remaining,
        )

    elapsed = time.time() - t0
    logger.info("Terminé : %d traitées, %d avec suggestion, en %.0fs", processed, found, elapsed)
    return PhaseMetrics(seen=processed, new=found)
