import { describe, it, expect, vi, beforeEach } from 'vitest';

// Le composable importe `api` depuis `$lib/api` ; on le remplace par un mock
// configurable que chaque test renseigne via `apiResponse`.
let apiResponse: Record<string, unknown> = {};
const apiSpy = vi.fn(async (..._args: unknown[]) => apiResponse);
vi.mock('$lib/api', () => ({ api: (...args: unknown[]) => apiSpy(...args) }));

const { useFacets } = await import('./useFacets.svelte');

describe('useFacets', () => {
	beforeEach(() => {
		apiSpy.mockClear();
		apiResponse = {};
	});

	it('appelle l\'endpoint avec les params buildés et la clé', async () => {
		apiResponse = { years: [] };
		const f = useFacets({
			endpoint: '/api/publications/facets',
			apiKey: 'pub-facets',
			buildParams: () => new URLSearchParams('year=2024'),
			facets: { years: { type: 'simple', apiKey: 'years' } },
		});
		await f.load();
		expect(apiSpy).toHaveBeenCalledOnce();
		const [url, opts] = apiSpy.mock.calls[0];
		expect(url).toBe('/api/publications/facets?year=2024');
		expect(opts).toEqual({ key: 'pub-facets' });
	});

	it('mappe le type "simple" : value/count → text = value', async () => {
		apiResponse = { years: [{ value: 2024, count: 12 }, { value: 2023, count: 8 }] };
		const f = useFacets({
			endpoint: '/x',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
			facets: { years: { type: 'simple', apiKey: 'years' } },
		});
		await f.load();
		expect(f.options.years).toEqual([
			{ value: '2024', text: '2024', count: 12 },
			{ value: '2023', text: '2023', count: 8 },
		]);
	});

	it('mappe le type "simple" avec formatText', async () => {
		apiResponse = { years: [{ value: 2024, count: 1 }] };
		const f = useFacets({
			endpoint: '/x',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
			facets: {
				years: { type: 'simple', apiKey: 'years', formatText: (v) => `Année ${v}` },
			},
		});
		await f.load();
		expect(f.options.years[0].text).toBe('Année 2024');
	});

	it('mappe le type "label_map"', async () => {
		apiResponse = {
			doc_types: [{ value: 'thesis', count: 50 }, { value: 'unknown_type', count: 3 }],
		};
		const f = useFacets({
			endpoint: '/x',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
			facets: {
				status: {
					type: 'label_map',
					apiKey: 'doc_types',
					labels: { thesis: 'Soutenues' },
				},
			},
		});
		await f.load();
		expect(f.options.status).toEqual([
			{ value: 'thesis', text: 'Soutenues', count: 50 },
			// Fallback à la valeur brute quand la clé est absente du label_map.
			{ value: 'unknown_type', text: 'unknown_type', count: 3 },
		]);
	});

	it('mappe le type "labeled" (avec label inclus dans la réponse)', async () => {
		apiResponse = { labs: [{ value: 42, label: 'Mon Labo', count: 100 }] };
		const f = useFacets({
			endpoint: '/x',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
			facets: { labs: { type: 'labeled', apiKey: 'labs' } },
		});
		await f.load();
		expect(f.options.labs).toEqual([{ value: '42', text: 'Mon Labo', count: 100 }]);
	});

	it('mappe le type "labeled" avec transform', async () => {
		apiResponse = { countries: [{ value: 'fr', label: 'France', count: 1000 }] };
		const f = useFacets({
			endpoint: '/x',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
			facets: {
				countries: {
					type: 'labeled',
					apiKey: 'countries',
					transform: (item) => ({ value: item.value, text: item.label.toUpperCase(), count: item.count }),
				},
			},
		});
		await f.load();
		expect(f.options.countries).toEqual([{ value: 'fr', text: 'FRANCE', count: 1000 }]);
	});

	it('mappe le type "boolean" en yes/no avec labels', async () => {
		apiResponse = { has_apc: { yes: 25, no: 100 } };
		const f = useFacets({
			endpoint: '/x',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
			facets: {
				apc: {
					type: 'boolean',
					apiKey: 'has_apc',
					yesLabel: 'Avec APC',
					noLabel: 'Sans APC',
				},
			},
		});
		await f.load();
		expect(f.options.apc).toEqual([
			{ value: 'yes', text: 'Avec APC', count: 25 },
			{ value: 'no', text: 'Sans APC', count: 100 },
		]);
	});

	it('boolean : 0 par défaut si yes/no absents', async () => {
		apiResponse = { has_apc: {} };
		const f = useFacets({
			endpoint: '/x',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
			facets: {
				apc: {
					type: 'boolean',
					apiKey: 'has_apc',
					yesLabel: 'Y',
					noLabel: 'N',
				},
			},
		});
		await f.load();
		expect(f.options.apc).toEqual([
			{ value: 'yes', text: 'Y', count: 0 },
			{ value: 'no', text: 'N', count: 0 },
		]);
	});

	it('renvoie [] pour une facette dont la réponse est falsy', async () => {
		apiResponse = { years: null };
		const f = useFacets({
			endpoint: '/x',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
			facets: { years: { type: 'simple', apiKey: 'years' } },
		});
		await f.load();
		expect(f.options.years).toEqual([]);
	});

	it('peuple sourceCounts depuis la clé déclarée', async () => {
		apiResponse = {
			source_counts: { hal: { yes: 100, no: 50 }, oa: { yes: 80, no: 70 } },
		};
		const f = useFacets({
			endpoint: '/x',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
			facets: {},
			sourceCountsKey: 'source_counts',
		});
		await f.load();
		expect(f.sourceCounts).toEqual({
			hal: { yes: 100, no: 50 },
			oa: { yes: 80, no: 70 },
		});
	});

	it('appelle afterLoad avec les données brutes et les options mappées', async () => {
		apiResponse = { years: [{ value: 2024, count: 1 }], extra: 'metadata' };
		const afterLoad = vi.fn();
		const f = useFacets({
			endpoint: '/x',
			apiKey: 'k',
			buildParams: () => new URLSearchParams(),
			facets: { years: { type: 'simple', apiKey: 'years' } },
			afterLoad,
		});
		await f.load();
		expect(afterLoad).toHaveBeenCalledOnce();
		const [data, options] = afterLoad.mock.calls[0];
		expect(data.extra).toBe('metadata');
		expect(options.years).toHaveLength(1);
	});
});
