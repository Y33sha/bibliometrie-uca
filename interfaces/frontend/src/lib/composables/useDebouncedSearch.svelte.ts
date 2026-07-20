/**
 * Composable pour une recherche à saisie avec debounce.
 *
 * Encapsule le pattern récurrent : champ de recherche → délai → fetch →
 * affichage de résultats, avec annulation des requêtes en vol quand
 * l'utilisateur continue de taper.
 *
 * Usage minimal :
 *   const search = useDebouncedSearch<Person>({
 *     search: (q) => api(`/api/persons/search?search=${encodeURIComponent(q)}`),
 *     minLength: 2,
 *   });
 *
 *   // Dans un input :
 *   oninput={(e) => search.setQuery((e.target as HTMLInputElement).value)}
 *
 *   // Dans le template :
 *   {#if search.loading}...
 *   {#each search.results as r (r.id)}...
 *
 *   // Pour nettoyer à la fermeture d'un formulaire :
 *   search.clear();
 *
 * Les requêtes concurrentes sont gérées par `api()` lui-même (option `key`)
 * si on passe un `apiKey`. Sinon on se contente d'ignorer les résultats
 * obsolètes via un compteur interne.
 */

interface DebouncedSearchOptions<R> {
	/** Fonction de recherche — retourne une promesse avec les résultats. */
	search: (query: string) => Promise<R[]>;
	/** Longueur minimale avant de déclencher la recherche. Défaut : 2. */
	minLength?: number;
	/** Délai de debounce en ms. Défaut : 300. */
	delay?: number;
	/** Transformateur optionnel des résultats (filtrage, tri, etc.). */
	transform?: (results: R[]) => R[];
}

export function useDebouncedSearch<R>(opts: DebouncedSearchOptions<R>) {
	const minLength = opts.minLength ?? 2;
	const delay = opts.delay ?? 300;

	let query = $state('');
	let results: R[] = $state([]);
	let loading = $state(false);
	let timer: ReturnType<typeof setTimeout> | null = null;
	// Compteur pour ignorer les réponses obsolètes (course fenêtrée).
	let seq = 0;

	function setQuery(q: string) {
		query = q;
		if (timer) clearTimeout(timer);
		if (q.trim().length < minLength) {
			results = [];
			loading = false;
			return;
		}
		loading = true;
		const mySeq = ++seq;
		timer = setTimeout(async () => {
			try {
				const raw = await opts.search(q.trim());
				if (mySeq !== seq) return; // un nouveau input est arrivé entre-temps
				results = opts.transform ? opts.transform(raw) : raw;
			} finally {
				if (mySeq === seq) loading = false;
			}
		}, delay);
	}

	function clear() {
		if (timer) clearTimeout(timer);
		query = '';
		results = [];
		loading = false;
		seq++;
	}

	return {
		get query() { return query; },
		get results() { return results; },
		get loading() { return loading; },
		setQuery,
		clear,
	};
}
