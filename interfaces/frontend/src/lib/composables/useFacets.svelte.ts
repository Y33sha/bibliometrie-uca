import { api } from '$lib/api';
import type { FacetOption } from '$lib/components/FacetDropdown.svelte';

/**
 * Composable pour le chargement de facettes.
 *
 * Chaque facette est déclarée avec un type qui détermine le mapping :
 *   - simple     : { value, count }[]         → text = String(value)
 *   - label_map  : { value, count }[]         → text = labels[value] || value
 *   - labeled    : { value, label, count }[]  → text = label (transform optionnel)
 *   - boolean    : { value, count }[]         → deux options yes/no
 */

// --- Facet definition types ---

interface SimpleFacet {
	type: 'simple';
	apiKey: string;
	formatText?: (value: string) => string;
}

interface LabelMapFacet {
	type: 'label_map';
	apiKey: string;
	labels: Record<string, string>;
}

interface LabeledFacet {
	type: 'labeled';
	apiKey: string;
	transform?: (item: { value: string; label: string; count: number }) => FacetOption;
}

interface BooleanFacet {
	type: 'boolean';
	apiKey: string;
	yesLabel: string;
	noLabel: string;
}

export type FacetDef = SimpleFacet | LabelMapFacet | LabeledFacet | BooleanFacet;

interface FacetsConfig<K extends string> {
	endpoint: string;
	/** Clé de cache `api()`. Passer un getter `() => ...` pour qu'un changement
	 *  (invalidation après édition admin) recharge les facettes. */
	apiKey: string | (() => string);
	buildParams: () => URLSearchParams;
	facets: Record<K, FacetDef>;
	sourceCountsKey?: string;
	afterLoad?: (data: Record<string, unknown>, options: Record<K, FacetOption[]>) => void;
}

export function useFacets<K extends string>(config: FacetsConfig<K>) {
	const initialOptions = {} as Record<K, FacetOption[]>;
	for (const key of Object.keys(config.facets) as K[]) {
		initialOptions[key] = [];
	}
	let options: Record<K, FacetOption[]> = $state(initialOptions);
	let sourceCounts: Record<string, { yes: number; no: number }> = $state({});

	const currentKey = (): string =>
		typeof config.apiKey === 'function' ? config.apiKey() : config.apiKey;
	let lastKey: string | undefined;

	// Recharge les facettes quand la clé d'API change (invalidation après
	// édition/fusion admin). `apiKey` doit être un getter pour être suivi ;
	// la garde `lastKey` évite un double-chargement au montage.
	$effect(() => {
		const key = currentKey();
		if (lastKey !== undefined && key !== lastKey) load();
	});

	async function load() {
		lastKey = currentKey();
		const params = config.buildParams();
		const data = await api<Record<string, unknown>>(
			config.endpoint + '?' + params,
			{ key: lastKey },
		);

		const newOpts = {} as Record<K, FacetOption[]>;

		for (const [key, def] of Object.entries(config.facets) as [K, FacetDef][]) {
			const raw = data[def.apiKey];
			if (!raw) { newOpts[key] = []; continue; }

			switch (def.type) {
				case 'simple':
					newOpts[key] = (raw as { value: unknown; count: number }[]).map((item) => ({
						value: String(item.value),
						text: def.formatText ? def.formatText(String(item.value)) : String(item.value),
						count: item.count,
					}));
					break;
				case 'label_map':
					newOpts[key] = (raw as { value: string; count: number }[]).map((item) => ({
						value: String(item.value),
						text: def.labels[item.value] || String(item.value),
						count: item.count,
					}));
					break;
				case 'labeled':
					newOpts[key] = (raw as { value: unknown; label: string; count: number }[]).map((item) => {
						const base = { value: String(item.value), label: item.label, count: item.count };
						return def.transform
							? def.transform(base)
							: { value: base.value, text: base.label, count: base.count };
					});
					break;
				case 'boolean': {
					const counts = raw as Record<string, number>;
					const yesCount = counts['yes'] ?? 0;
					const noCount = counts['no'] ?? 0;
					newOpts[key] = [
						{ value: 'yes', text: def.yesLabel, count: yesCount },
						{ value: 'no', text: def.noLabel, count: noCount },
					];
					break;
				}
			}
		}

		if (config.sourceCountsKey && data[config.sourceCountsKey]) {
			sourceCounts = data[config.sourceCountsKey] as Record<string, { yes: number; no: number }>;
		}

		config.afterLoad?.(data, newOpts);
		options = newOpts;
	}

	return {
		get options() { return options; },
		get sourceCounts() { return sourceCounts; },
		load,
	};
}
