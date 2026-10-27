<script lang="ts">
	import TableScroll from '#lib/components/TableScroll.svelte';
	import { onMount } from 'svelte';
	import ResultCount from '#lib/components/ResultCount.svelte';
	import { resolve } from '$app/paths';
	import FacetDropdown from '#lib/components/FacetDropdown.svelte';
	import { columnLabels, filterLabels } from '#lib/labels.js';
	import type { FacetOption } from '#lib/components/FacetDropdown.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { rorFullUrl } from '#lib/utils.js';
	import type { components } from '#lib/api/schema.js';

	type Partner = components['schemas']['StructurePartner'];
	type PartnersResponse = components['schemas']['StructurePartnersResponse'];
	type PartnerFacetOption = components['schemas']['PartnerFacetOption'];

	// Organisations partenaires d'une structure : ROR des auteurs de ses publications, les plus fréquents en tête.
	let { labId }: { labId: number } = $props();

	let selectedYears: string[] = $state([]);
	let selectedCountries: string[] = $state([]);
	let selectedTypes: string[] = $state([]);

	const partners = usePaginatedFetch<Partner, PartnersResponse>({
		endpoint: () => `/api/structures/${labId}/partners`,
		itemsKey: 'partners',
		perPage: 50,
		apiKey: () => `lab-${labId}-partners`,
		buildParams() {
			const params = new URLSearchParams();
			if (selectedYears.length) params.set('year', selectedYears.join(','));
			if (selectedCountries.length) params.set('country', selectedCountries.join(','));
			if (selectedTypes.length) params.set('type', selectedTypes.join(','));
			return params;
		},
		pageParam: null,
	});

	function facetOptions(options: PartnerFacetOption[] | undefined): FacetOption[] {
		return (options ?? []).map((o) => ({ value: o.value, text: o.label, count: o.count }));
	}

	const typeLabels = $derived(new Map((partners.data?.types ?? []).map((o) => [o.value, o.label])));

	function onFilterChange() {
		partners.page = 1;
		partners.load();
	}

	onMount(() => partners.load());
</script>

<div class="toolbar toolbar-card">
	<FacetDropdown label={filterLabels.years} options={facetOptions(partners.data?.years)} searchable bind:selected={selectedYears} onchange={onFilterChange} />
	<FacetDropdown label={filterLabels.countries} options={facetOptions(partners.data?.countries)} searchable bind:selected={selectedCountries} onchange={onFilterChange} />
	<FacetDropdown label={filterLabels.types} options={facetOptions(partners.data?.types)} bind:selected={selectedTypes} onchange={onFilterChange} />
	<ResultCount list={partners} one="organisation partenaire" many="organisations partenaires" />
</div>

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
			{#each partners.items as p (p.ror_id)}
				<tr>
					<td><a href={rorFullUrl(p.ror_id)} target="_blank" rel="noopener">{p.name ?? p.ror_id}</a></td>
					<td>{p.country_name ?? p.country_code ?? ''}</td>
					<td class="muted">{p.types.map((t) => typeLabels.get(t) ?? t).join(', ')}</td>
					<td class="num">
						<a href={resolve(`structures/${labId}?tab=publications&partner_ror=${p.ror_id}`)}>{p.publications.toLocaleString('fr-FR')}</a>
					</td>
				</tr>
			{/each}
			{#if partners.items.length === 0}
				<TableStatusRow loading={partners.loading} error={partners.error} colspan={4} emptyText="Aucune organisation partenaire ne correspond aux filtres." />
			{/if}
		</tbody>
	</table>
</TableScroll>

<Pagination
	page={partners.page}
	pages={partners.pages}
	onchange={(p) => {
		partners.page = p;
		partners.load();
	}}
/>

<style>
	.muted { color: var(--muted); }
</style>
