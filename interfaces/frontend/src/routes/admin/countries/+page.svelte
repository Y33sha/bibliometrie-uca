<script lang="ts">
	import TableScroll from '#lib/components/TableScroll.svelte';
	import { onMount } from 'svelte';
	import PageHeader from '#lib/components/PageHeader.svelte';
	import ResultCount from '#lib/components/ResultCount.svelte';
	import { resolve } from '$app/paths';
	import { replaceQuery } from '#lib/url.js';
	import { stickyHeight } from '#lib/actions/stickyHeight.js';
	import { addresses as addressesApi, api, errorMessage } from '#lib/api/index.js';
	import Pagination from '#lib/components/Pagination.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import FacetDropdown from '#lib/components/FacetDropdown.svelte';
	import { columnLabels, filterLabels } from '#lib/labels.js';
	import type { FacetOption } from '#lib/components/FacetDropdown.svelte';

	import type { components } from '#lib/api/schema.js';
	type Address = components['schemas']['AddressForCountryAttribution'];
	type Country = components['schemas']['CountryOut'];
	type Method = components['schemas']['CountryDetectionMethod'];
	type Facet = { value: string; count: number };
	type AddressesResponse = { country_facets?: Facet[]; without_country?: number };

	const METHOD_LABELS: Record<Method, string> = {
		manual: 'saisie',
		country_name: 'nom de pays',
		source_openalex: 'OpenAlex',
		institution: 'institution',
		city: 'ville',
		source_scanr: 'ScanR',
	};

	function methodsLabel(methods: Method[]): string {
		return methods.map(m => METHOD_LABELS[m]).join(', ');
	}

	let countries: Country[] = $state([]);
	let countryMap: Record<string, string> = $state({});
	const list = usePaginatedFetch<Address, AddressesResponse>({
		endpoint: '/api/addresses/countries',
		itemsKey: 'addresses',
		apiKey: 'countries-addr-list',
		buildParams() {
			const params = new URLSearchParams();
			if (search.trim()) params.set('search', search.trim());
			if (withoutCountry) params.set('has_country', 'false');
			else if (selectedCountry.length === 1) params.set('country_code', selectedCountry[0]);
			return params;
		},
	});
	const addresses = $derived(list.items);

	let search = $state('');
	let selectedCountry: string[] = $state([]);
	// Option « Aucun » de la facette Pays : adresses sans pays retenu.
	const NONE = 'none';
	const withoutCountry = $derived(selectedCountry.length === 1 && selectedCountry[0] === NONE);
	let debounceTimer: ReturnType<typeof setTimeout>;

	// Batch
	let selectedIds: Set<number> = $state(new Set());
	let batchCountry = $state('');
	const allSelected = $derived(addresses.length > 0 && addresses.every(a => selectedIds.has(a.id)));

	// Code du référentiel marquant l'absence de pays : la facette le place juste après « Aucun », c'est l'arbitrage le plus fréquent et le seul qui ne se cherche pas par son nom.
	const NO_COUNTRY_CODE = 'xx';
	let countryFacets: { value: string; count: number }[] = $state([]);
	let withoutCountryCount: number | undefined = $state(undefined);
	const countryOptions = $derived.by((): FacetOption[] => {
		const none: FacetOption = { value: NONE, text: 'Aucun', count: withoutCountryCount };
		if (countryFacets.length > 0) {
			const noCountry = countryFacets.find(f => f.value === NO_COUNTRY_CODE);
			const rest = countryFacets.filter(f => f.value !== NO_COUNTRY_CODE);
			const sorted = [...(noCountry ? [noCountry] : []), ...rest];
			return [
				none,
				...sorted.map(f => ({
					value: f.value,
					text: `${countryMap[f.value] || f.value.toUpperCase()} (${f.value.toUpperCase()})`,
					count: f.count,
				})),
			];
		}
		return [none, ...countries.map(c => ({ value: c.code, text: `${c.name} (${c.code.toUpperCase()})` }))];
	});

	async function loadCountries() {
		countries = await api<Country[]>('/api/countries');
		countryMap = Object.fromEntries(countries.map(c => [c.code, c.name]));
	}

	// Les facettes arrivent avec la page d'adresses ; une réponse qui n'en porte pas garde les précédentes.
	$effect(() => {
		const data = list.data;
		if (data?.country_facets) countryFacets = data.country_facets;
		if (data?.without_country != null) withoutCountryCount = data.without_country;
	});

	function syncUrl() {
		const p = new URLSearchParams();
		if (list.page > 1) p.set('page', String(list.page));
		if (search.trim()) p.set('search', search.trim());
		if (selectedCountry.length === 1) p.set('country', selectedCountry[0]);
		void replaceQuery(resolve('admin/countries'), p);
	}

	function onFilterChange() {
		list.page = 1;
		selectedIds = new Set();
		syncUrl();
		list.load();
	}

	function onSearchInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(onFilterChange, 400);
	}

	function countryLabel(code: string): string {
		return `${countryMap[code] || code} (${code.toUpperCase()})`;
	}

	async function addCountry(addrId: number, code: string) {
		const addr = addresses.find(a => a.id === addrId);
		if (!addr || !code) return;
		const newList = [...new Set([...(addr.countries || []), code])].sort();
		await addressesApi.setCountry(addrId, { countries: newList });
		if (withoutCountry) {
			list.load();
		} else {
			addr.countries = newList;
			list.items = [...addresses];
		}
	}

	async function removeCountry(addrId: number, code: string) {
		const addr = addresses.find(a => a.id === addrId);
		if (!addr) return;
		const newList = (addr.countries || []).filter(c => c !== code);
		await addressesApi.setCountry(addrId, { countries: newList.length ? newList : null });
		addr.countries = newList.length ? newList : null;
		list.items = [...addresses];
	}

	function toggleSelect(id: number) {
		const s = new Set(selectedIds);
		if (s.has(id)) s.delete(id); else s.add(id);
		selectedIds = s;
	}

	function toggleAll() {
		selectedIds = allSelected ? new Set() : new Set(addresses.map(a => a.id));
	}

	let batchApplying = $state(false);
	let batchResult = $state('');

	// Vrai ssi au moins un filtre est actif. Garde l'« Ajouter à tout le filtre » (mêmes conditions que le body construit dans batchAddCountry) : sans filtre, l'action viserait toutes les adresses — le backend la refuse (422), on masque le bouton côté UI. Aligné sur le garde-fou serveur.
	const hasActiveFilter = $derived(
		search.trim() !== '' || selectedCountry.length === 1,
	);

	async function batchAddCountry(applyToAll = false) {
		if (!batchCountry) return;
		batchApplying = true;
		batchResult = '';
		const body: Record<string, unknown> = { country_code: batchCountry };
		if (applyToAll) {
			if (search.trim()) body.search = search.trim();
			if (withoutCountry) body.has_country = false;
			else if (selectedCountry.length === 1) body.country_code_filter = selectedCountry[0];
		} else {
			body.address_ids = [...selectedIds];
		}
		// try/finally pour ne jamais laisser `batchApplying = true` sticky en cas d'erreur HTTP — sinon le bouton reste disabled à vie après une 504/500.
		try {
			const data = await addressesApi.batchSetCountry(body);
			batchResult = `${data.updated} adresse${data.updated > 1 ? 's' : ''} mise${data.updated > 1 ? 's' : ''} à jour`;
			selectedIds = new Set();
		} catch (e) {
			batchResult = 'Erreur : ' + errorMessage(e);
		} finally {
			batchApplying = false;
		}
		list.load();
		setTimeout(() => { batchResult = ''; }, 3000);
	}

	onMount(() => {
		const params = new URLSearchParams(window.location.search);
		if (params.get('page')) list.page = parseInt(params.get('page')!) || 1;
		if (params.get('search')) search = params.get('search')!;
		if (params.get('country')) selectedCountry = [params.get('country')!];
		loadCountries();
		list.load();
	});
</script>

<PageHeader title="Pays" hidden />

<div class="toolbar">
	<input type="search" placeholder="Rechercher dans les adresses" bind:value={search} onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onSearchInput(); } }} oninput={onSearchInput} />
	<FacetDropdown label={filterLabels.countries} options={countryOptions} searchable bind:selected={selectedCountry} onchange={onFilterChange} />
	<span class="toolbar-spacer"></span>
	<ResultCount {list} one="adresse" many="adresses" />
</div>

<div class="batch-bar" use:stickyHeight={{ variable: '--batch-bar-height' }}>
	<select class="select" aria-label="Pays à ajouter" bind:value={batchCountry}>
		<option value="">— Choisir un pays à ajouter —</option>
		{#each countries as c}
			<option value={c.code}>{c.name} ({c.code.toUpperCase()})</option>
		{/each}
	</select>
	{#if selectedIds.size > 0 && batchCountry}
		<button class="btn btn-primary" onclick={() => batchAddCountry(false)} disabled={batchApplying}>
			Ajouter aux {selectedIds.size} sélectionnée{selectedIds.size > 1 ? 's' : ''}
		</button>
	{/if}
	{#if batchCountry && hasActiveFilter}
		<button class="btn" onclick={() => batchAddCountry(true)} disabled={batchApplying}>
			Ajouter à tout le filtre ({list.total.toLocaleString('fr-FR')})
		</button>
	{/if}
	{#if batchResult}
		<span class="batch-result">{batchResult}</span>
	{/if}
</div>

<TableScroll>
	<table class="data-table addr-table">
		<thead>
			<tr>
				<th style="width:30px"><input type="checkbox" aria-label="Tout sélectionner" checked={allSelected} onchange={toggleAll} /></th>
				<th style="width:55%">{columnLabels.address}</th>
				<th style="width:110px">{columnLabels.publications}</th>
				<th>{columnLabels.country}</th>
			</tr>
		</thead>
		<tbody>
			{#each addresses as a (a.id)}
				<tr>
					<td><input type="checkbox" aria-label="Sélectionner l'adresse" checked={selectedIds.has(a.id)} onchange={() => toggleSelect(a.id)} /></td>
					<td class="addr-cell">{a.raw_text}</td>
					<td class="num-cell">{a.publication_count}</td>
					<td>
						<div class="country-cell">
						{#each a.countries ?? [] as c}
							{@const found = a.found_countries.find(f => f.country_code === c)}
							<span class="country-tag" title={found ? `Trouvé par : ${methodsLabel(found.methods)}` : undefined}>
								{countryLabel(c)}
								<button class="tag-remove" aria-label="Retirer {countryLabel(c)}" title="Retirer {countryLabel(c)}" onclick={() => removeCountry(a.id, c)}>×</button>
							</span>
						{/each}
						<span class="country-actions">
							{#each a.found_countries.filter(f => !a.countries?.includes(f.country_code)) as p}
								<button class="proposal-tag" title="Ajouter ce pays" onclick={() => addCountry(a.id, p.country_code)}>
									{countryLabel(p.country_code)} ?
									<span class="proposal-methods">{methodsLabel(p.methods)}</span>
								</button>
							{/each}
							<select class="select add-country" aria-label="Ajouter un pays" onchange={(e) => { const v = (e.target as HTMLSelectElement).value; if (v) { addCountry(a.id, v); (e.target as HTMLSelectElement).value = ''; } }}>
								<option value="">+ Pays</option>
								{#each countries as c}
									<option value={c.code}>{c.name} ({c.code.toUpperCase()})</option>
								{/each}
							</select>
						</span>
						</div>
					</td>
				</tr>
			{/each}
			{#if addresses.length === 0}
				<TableStatusRow loading={list.loading} error={list.error} colspan={4} emptyText="Aucune adresse trouvée." />
			{/if}
		</tbody>
	</table>
</TableScroll>

<Pagination page={list.page} pages={list.pages} onchange={(p) => { list.goToPage(p); syncUrl(); }} />

<style>
	.toolbar input[type="search"] { width: 300px; }
	.batch-bar {
		display: flex; align-items: center; gap: 8px;
		padding: 8px 12px; margin-bottom: 10px;
		background: var(--accent-light); border-radius: var(--radius); font-size: var(--fs-md);
	}
	.batch-result { font-size: var(--fs-sm); color: var(--success); font-weight: 500; }
	.proposal-tag {
		display: inline-flex; align-items: center; gap: 4px;
		padding: 2px 8px; background: var(--warning-light); color: var(--warning-text);
		border: 1px dashed var(--warning); border-radius: var(--radius); cursor: pointer;
		font-size: var(--fs-sm); font-weight: 500; white-space: nowrap;
	}
	.proposal-tag:hover { background: color-mix(in srgb, var(--warning) 25%, white); }
	.proposal-methods { font-weight: 400; opacity: 0.8; }
	.addr-table { table-layout: fixed; min-width: 640px; }
	.addr-table td { font-size: var(--fs-md); vertical-align: middle; }
	.addr-cell { word-break: break-word; }
	.num-cell { text-align: center; color: var(--muted); font-size: var(--fs-sm); }
	.country-cell { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
	.country-actions { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; justify-content: flex-end; margin-left: auto; }
	.country-tag {
		display: inline-flex; align-items: center; gap: 2px;
		padding: 2px 6px; background: var(--success-light);
		border-radius: var(--radius); font-size: var(--fs-sm); color: var(--success); white-space: nowrap;
	}
	.tag-remove {
		background: none; border: none; cursor: pointer;
		color: var(--muted); font-size: var(--fs-sm); padding: 0 1px; line-height: 1;
	}
	.tag-remove:hover { color: var(--danger); }
	.add-country { width: 7rem; height: 26px; font-size: var(--fs-sm); color: var(--muted); }
</style>
