import { facetDefs, type ListFilter } from '#lib/filterRegistry.js';
import { useFacets } from '#lib/composables/useFacets.svelte.js';

/** Endpoint des décomptes des filtres des publications. Sa facette d'entité est `${PUBLICATION_FACETS_ENDPOINT}/entities`. */
export const PUBLICATION_FACETS_ENDPOINT = '/api/publications/facets';

/** Décomptes des filtres des publications sous les filtres actifs. L'option « Aucun labo » précède les laboratoires. */
export function usePublicationFacets(config: {
	filters: ListFilter[];
	apiKey: () => string;
	buildParams: () => URLSearchParams;
}) {
	return useFacets({
		endpoint: PUBLICATION_FACETS_ENDPOINT,
		apiKey: config.apiKey,
		buildParams: config.buildParams,
		sourceCountsKey: 'source_counts',
		facets: facetDefs(config.filters),
		afterLoad(data, options) {
			options.labs = [
				{ value: 'none', text: '— Aucun labo —', count: (data.no_lab_count as number) ?? 0 },
				...options.labs,
			];
		},
	});
}
