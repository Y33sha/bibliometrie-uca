<script lang="ts">
	import { onMount } from 'svelte';
	import { api } from '#lib/api/index.js';
	import { columnLabels } from '#lib/labels.js';
	import { formatCount } from '#lib/plural.js';
	import { formatNumber, formatPercent } from '#lib/utils.js';
	import { structureLabel } from '#lib/structureLabels.js';
	import ListStatus from '#lib/components/ListStatus.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import AddressPublications from '#lib/components/AddressPublications.svelte';
	import PublicationCountButton from '#lib/components/PublicationCountButton.svelte';
	import YearShareBarChart from '#lib/components/charts/YearShareBarChart.svelte';
	import ChartLegend from '#lib/components/charts/ChartLegend.svelte';
	import { cssColor } from '#lib/components/charts/cssVar.js';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import type { components } from '#lib/api/schema.js';

	type Address = components['schemas']['ScopedAddressOut'];
	type AddressSummary = components['schemas']['ScopedAddressSummary'];
	type AddressPublication = components['schemas']['AddressPublicationItem'];
	type AddressPublicationsResponse = components['schemas']['AddressPublicationsResponse'];

	// Adresses brutes des publications d'un périmètre (une personne, les membres d'un laboratoire) : publications avec adresse par année, part de la structure choisie dans la légende, tableau des adresses.
	let {
		endpoint,
		scope,
		preferredStructureId = null,
		apiKey,
	}: {
		/** Route de l'entité, complétée par `/addresses` et `/address-summary`. */
		endpoint: string;
		/** Paramètre du périmètre pour les publications d'une adresse : `{ person_id }` ou `{ lab_id }`. */
		scope: Record<string, string>;
		/** Structure choisie d'office si elle figure dans les adresses ; à défaut, la plus fréquente. */
		preferredStructureId?: number | null;
		apiKey: string;
	} = $props();

	let summary = $state<AddressSummary | null>(null);
	const addresses = usePaginatedFetch<Address>({
		endpoint: () => `${endpoint}/addresses`,
		itemsKey: 'addresses',
		apiKey: () => `${apiKey}-addresses`,
		buildParams: () => new URLSearchParams(),
		pageParam: null,
	});

	const years = $derived(summary?.years ?? []);
	const totals = $derived(years.map((y) => y.publications_with_address));
	const structures = $derived(summary?.structures ?? []);
	let selectedLabel = $state<string | null>(null);
	const selected = $derived(structures.find((s) => structureLabel(s) === selectedLabel) ?? null);
	const partColor = $derived(cssColor('accent-mid'));
	const legend = $derived(
		structures.map((s) => {
			const label = structureLabel(s);
			return { label, color: label === selectedLabel ? partColor : cssColor('text-faint') };
		})
	);
	// Part de la structure choisie, toutes années confondues.
	const selectedShare = $derived.by(() => {
		if (!selected) return '';
		const part = selected.publications.reduce((a, b) => a + b, 0);
		const total = totals.reduce((a, b) => a + b, 0);
		return `${formatCount(part, 'publication')} sur ${formatNumber(total)} (${formatPercent(total ? part / total : 0)})`;
	});
	function selectStructure(label: string) {
		selectedLabel = selectedLabel === label ? null : label;
	}

	let expandedAddrId = $state<number | null>(null);
	let publications = $state<AddressPublication[]>([]);
	let publicationsLoading = $state(false);

	async function togglePublications(addrId: number) {
		if (expandedAddrId === addrId) {
			expandedAddrId = null;
			return;
		}
		expandedAddrId = addrId;
		publications = [];
		publicationsLoading = true;
		const params = new URLSearchParams({ ...scope, limit: '500' });
		const data = await api<AddressPublicationsResponse>(`/api/addresses/${addrId}/publications?${params}`, {
			key: `${apiKey}-address-publications`,
		});
		publications = data.publications;
		publicationsLoading = false;
	}

	onMount(async () => {
		addresses.load();
		summary = await api<AddressSummary>(`${endpoint}/address-summary`, { key: `${apiKey}-address-summary` });
		const initial = summary.structures.find((s) => s.id === preferredStructureId) ?? summary.structures[0];
		selectedLabel = initial ? structureLabel(initial) : null;
	});
</script>

<div class="overview">
	<h2>Publications avec adresse, par année</h2>
	{#if years.length}
		<YearShareBarChart
			years={years.map((y) => y.year)}
			{totals}
			totalLabel="publication avec adresse"
			part={selected ? { label: structureLabel(selected), values: selected.publications } : null}
			{partColor}
		/>
	{/if}
	{#if structures.length}
		{#if selected}
			<p class="share"><strong>{structureLabel(selected)}</strong> : {selectedShare}</p>
		{/if}
		<ChartLegend items={legend} centered selected={selectedLabel} onselect={selectStructure} />
	{:else if summary}
		<p class="empty">Aucune structure reconnue.</p>
	{/if}
</div>
<ListStatus list={addresses} emptyText="Aucune adresse">
	<table class="data-table">
		<thead>
			<tr>
				<th>{columnLabels.address}</th>
				<th style="width:160px">Structures</th>
				<th style="width:120px">Publications</th>
			</tr>
		</thead>
		<tbody>
			{#each addresses.items as a (a.id)}
				<tr>
					<td class="addr-cell">{a.raw_text}</td>
					<td>
						{#if a.structures?.length}
							{#each a.structures as s (s.id)}
								<span class="tag tag-accent">{structureLabel(s)}</span>
							{/each}
						{/if}
					</td>
					<td>
						<PublicationCountButton count={a.publication_count} expanded={expandedAddrId === a.id} onclick={() => togglePublications(a.id)} />
					</td>
				</tr>
				{#if expandedAddrId === a.id}
					<tr>
						<td colspan="3" class="addr-publications">
							<AddressPublications {publications} loading={publicationsLoading} />
						</td>
					</tr>
				{/if}
			{/each}
		</tbody>
	</table>
	<Pagination page={addresses.page} pages={addresses.pages} onchange={(p) => { addresses.page = p; expandedAddrId = null; addresses.load(); }} />
</ListStatus>

<style>
	.overview {
		max-width: 720px;
		margin: 0 auto 16px;
	}
	.overview h2 { font-size: var(--fs-base); font-weight: 600; margin: 0 0 8px; }
	.empty { font-size: var(--fs-sm); color: var(--text-secondary); margin: 4px 0 0; text-align: center; }
	.share { font-size: var(--fs-md); margin: 8px 0 0; text-align: center; }
	.addr-cell { font-size: var(--fs-sm); color: var(--muted); word-break: break-all; }
	.addr-publications { padding: 0 12px 12px 24px; }
</style>
