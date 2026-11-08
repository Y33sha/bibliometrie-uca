<script lang="ts">
	import TableScroll from '#lib/components/TableScroll.svelte';
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import ActiveFilterBar from '#lib/components/ActiveFilterBar.svelte';
	import ListToolbar from '#lib/components/ListToolbar.svelte';
	import FilterLayout from '#lib/components/filters/FilterLayout.svelte';
	import FilterPanel from '#lib/components/filters/FilterPanel.svelte';
	import FilterPanelToggle from '#lib/components/filters/FilterPanelToggle.svelte';
	import { columnLabels } from '#lib/labels.js';
	import Pagination from '#lib/components/Pagination.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { useFacets } from '#lib/composables/useFacets.svelte.js';
	import { useFilteredList } from '#lib/composables/useFilteredList.svelte.js';
	import { facetDefs } from '#lib/filterRegistry.js';
	import { PARTNER_FILTER_GROUPS, PARTNER_FILTERS } from '#lib/partnerFilters.js';
	import { rorFullUrl } from '#lib/utils.js';
	import type { components } from '#lib/api/schema.js';

	type Partner = components['schemas']['StructurePartner'];

	// Organisations partenaires d'une structure : ROR des auteurs de ses publications, les plus fréquents en tête.
	let { labId }: { labId: number } = $props();

	// svelte-ignore state_referenced_locally
	const endpoint = `/api/structures/${labId}/partners`;

	const list = useFilteredList<Partner, ReturnType<typeof useFacets>>({
		filters: PARTNER_FILTERS,
		endpoint,
		itemsKey: 'partners',
		perPage: 50,
		apiKey: () => `lab-${labId}-partners`,
		defaultSort: 'publications_desc',
		urlSync: () => false,
		basePath: () => `/structures/${labId}`,
		facets: (buildParams) =>
			useFacets({
				endpoint: `${endpoint}/facets`,
				apiKey: () => `lab-${labId}-partners-facets`,
				buildParams,
				facets: facetDefs(PARTNER_FILTERS),
			}),
	});

	const typeLabels = $derived(new Map((list.facets.options.types ?? []).map((o) => [o.value, o.text])));

	onMount(list.restore);
</script>

<ListToolbar list={list.listing} one="organisation partenaire" many="organisations partenaires" countBelow>
	{#snippet leading()}
		<FilterPanelToggle bind:open={list.panel.open} active={list.activeCount} />
	{/snippet}
	{#snippet activeFilters()}
		<ActiveFilterBar filters={PARTNER_FILTERS} bind:values={list.values} options={list.facets.options} onchange={list.onFilterChange} />
	{/snippet}
</ListToolbar>

<FilterLayout bind:open={list.panel.open}>
	{#snippet panel()}
		<FilterPanel filters={PARTNER_FILTERS} groups={PARTNER_FILTER_GROUPS} bind:values={list.values} options={list.facets.options} presenceCounts={{}} loaded={list.facets.loaded} entityEndpoint={`${endpoint}/facets`} buildParams={list.filterParams} panel={list.panel} onchange={list.onFilterChange} />
	{/snippet}

	<TableScroll>
		<table class="data-table">
			<thead>
				<tr>
					<th>Organisation</th>
					<th>{columnLabels.country}</th>
					<th>{columnLabels.type}</th>
					<th class="num">Copublications</th>
				</tr>
			</thead>
			<tbody>
				{#each list.listing.items as p (p.ror_id)}
					<tr>
						<td><a href={rorFullUrl(p.ror_id)} target="_blank" rel="noopener">{p.name ?? p.ror_id}</a></td>
						<td>{p.country_name ?? p.country_code ?? ''}</td>
						<td class="muted">{p.types.map((t) => typeLabels.get(t) ?? t).join(', ')}</td>
						<td class="num">
							<a href={resolve(`structures/${labId}?tab=publications&partner_ror=${p.ror_id}`)}>{p.publications.toLocaleString('fr-FR')}</a>
						</td>
					</tr>
				{/each}
				{#if list.listing.items.length === 0}
					<TableStatusRow loading={list.listing.loading} error={list.listing.error} colspan={4} emptyText="Aucune organisation partenaire ne correspond aux filtres." />
				{/if}
			</tbody>
		</table>
	</TableScroll>

	<Pagination page={list.listing.page} pages={list.listing.pages} onchange={list.goToPage} />
</FilterLayout>
