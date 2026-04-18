import { replaceState } from '$app/navigation';
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
	basePath: string;
	filters: Record<string, FilterDef>;
	debounceMs?: number;
}

export function useUrlFilters(config: UrlFiltersConfig) {
	let debounceTimer: ReturnType<typeof setTimeout>;

	function syncUrl(getState: () => Record<string, unknown>) {
		const state = getState();
		const p = new URLSearchParams();

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
		replaceState(base + config.basePath + (qs ? '?' + qs : ''), {});
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
