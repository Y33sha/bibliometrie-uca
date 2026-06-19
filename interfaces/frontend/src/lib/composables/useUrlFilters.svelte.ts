import { goto } from '$app/navigation';
import { base } from '$app/paths';

/**
 * Composable pour la synchronisation des filtres avec l'URL.
 *
 * Gère :
 * - Sérialisation de l'état filtres → URLSearchParams → replaceState
 * - Restauration de l'état depuis les URLSearchParams au montage
 * - Debounce pour la recherche texte
 *
 * Le composable ne possède PAS l'état des filtres — il fournit des utilitaires
 * pour le sérialiser/désérialiser. Chaque page garde ses propres variables $state.
 */

// --- Filter definition types ---

interface StringArrayFilter {
	type: 'string_array';
	urlKey: string;
}

interface SingleValueFilter {
	type: 'single';
	urlKey: string;
	defaultValue?: string;
}

interface SourceStatesFilter {
	type: 'source_states';
	urlKey: string;
}

interface PageFilter {
	type: 'page';
	urlKey: string;
}

type FilterDef = StringArrayFilter | SingleValueFilter | SourceStatesFilter | PageFilter;

interface UrlFiltersConfig {
	/** Chemin de la page propriétaire. Accepte un getter `() => ...` quand il
	 *  dérive d'un prop/route réactif (ex. `/persons/${personId}`) : il est alors
	 *  relu à chaque `syncUrl` au lieu d'être capturé au montage. */
	basePath: string | (() => string);
	filters: Record<string, FilterDef>;
	debounceMs?: number;
	/**
	 * Source des params URL actuellement présents. Utilisé pour préserver les
	 * keys non gérées par cette instance lors d'un `syncUrl` (additivité, cf.
	 * cas où plusieurs `useUrlFilters` cohabitent sur une même page).
	 * Par défaut lit `window.location.search`.
	 */
	getCurrentParams?: () => URLSearchParams;
}

export function useUrlFilters(config: UrlFiltersConfig) {
	let debounceTimer: ReturnType<typeof setTimeout>;

	const managedKeys = new Set<string>(
		Object.values(config.filters).map((def) => def.urlKey),
	);

	function readCurrentParams(): URLSearchParams {
		if (config.getCurrentParams) return config.getCurrentParams();
		if (typeof window !== 'undefined') return new URLSearchParams(window.location.search);
		return new URLSearchParams();
	}

	function syncUrl(getState: () => Record<string, unknown>) {
		const state = getState();
		const p = new URLSearchParams();

		// Préserve les keys de l'URL courante qui ne sont pas gérées par
		// cette instance (permet la cohabitation de plusieurs `useUrlFilters`
		// ou la coexistence avec d'autres écritures URL).
		for (const [k, v] of readCurrentParams()) {
			if (!managedKeys.has(k)) p.append(k, v);
		}

		for (const [key, def] of Object.entries(config.filters)) {
			const val = state[key];
			switch (def.type) {
				case 'string_array':
					if (Array.isArray(val) && val.length) p.set(def.urlKey, val.join(','));
					break;
				case 'single':
					if (val != null && val !== '' && val !== (def.defaultValue ?? ''))
						p.set(def.urlKey, String(val));
					break;
				case 'source_states': {
					if (val && typeof val === 'object') {
						const sf = Object.entries(val as Record<string, string>)
							.filter(([, v]) => v === 'yes' || v === 'no')
							.map(([k, v]) => `${k}_${v}`)
							.join(',');
						if (sf) p.set(def.urlKey, sf);
					}
					break;
				}
				case 'page':
					if (typeof val === 'number' && val > 1) p.set(def.urlKey, String(val));
					break;
			}
		}

		const qs = p.toString();
		const targetPath =
			base + (typeof config.basePath === 'function' ? config.basePath() : config.basePath);
		// Garde anti-navigation parasite : `syncUrl` est parfois appelé après un
		// chargement async (cf. `onMount` des pages qui `await` puis `syncUrl()`).
		// Si l'utilisateur a changé de route entre-temps, le `goto` ci-dessous —
		// qui cible `basePath` en dur — le ramènerait sur cette page. On ne
		// synchronise donc l'URL que si on est encore sur la page propriétaire.
		if (typeof window !== 'undefined' && window.location.pathname !== targetPath) return;
		// `goto({ replaceState: true })` plutôt que le `replaceState` bas niveau
		// de `$app/navigation` : `replaceState` ne mettait pas correctement à
		// jour l'entrée d'historique du navigateur, et au back, le navigateur
		// ramenait à l'URL d'origine (pré-modifications) tandis que le
		// composant restauré depuis bfcache gardait son `$state` JS d'avant la
		// navigation — désynchro URL bar ↔ UI. `goto` synchronise history,
		// store `$page` et bfcache. `noScroll` + `keepFocus` évitent les sauts
		// quand on coche/décoche un filtre.
		void goto(targetPath + (qs ? '?' + qs : ''), {
			replaceState: true,
			noScroll: true,
			keepFocus: true,
		});
	}

	function restoreFromUrl(urlParams: URLSearchParams): Record<string, unknown> {
		const result: Record<string, unknown> = {};

		for (const [key, def] of Object.entries(config.filters)) {
			const raw = urlParams.get(def.urlKey);
			if (raw == null) continue;

			switch (def.type) {
				case 'string_array':
					result[key] = raw.split(',');
					break;
				case 'single':
					result[key] = raw;
					break;
				case 'source_states': {
					const states: Record<string, string> = {};
					for (const v of raw.split(',')) {
						const m = v.match(/^(\w+)_(yes|no)$/);
						if (m) states[m[1]] = m[2];
					}
					result[key] = states;
					break;
				}
				case 'page':
					result[key] = Number(raw) || 1;
					break;
			}
		}

		return result;
	}

	function debouncedSearch(onTrigger: () => void): () => void {
		return () => {
			clearTimeout(debounceTimer);
			debounceTimer = setTimeout(onTrigger, config.debounceMs ?? 400);
		};
	}

	return { syncUrl, restoreFromUrl, debouncedSearch };
}
