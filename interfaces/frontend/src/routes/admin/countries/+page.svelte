<script lang="ts">
	import { onMount } from 'svelte';
	import { autofocus } from '$lib/actions/focus';
	import { base } from '$app/paths';
	import { replaceState } from '$app/navigation';
	import { addresses as addressesApi, api } from '$lib/api';
	import Pagination from '$lib/components/Pagination.svelte';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import type { FacetOption } from '$lib/components/FacetDropdown.svelte';

	import type { components } from '$lib/api/schema';
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
		const qs = p.toString();
		replaceState(`${base}/admin/countries` + (qs ? '?' + qs : ''), {});
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
			batchResult = 'Erreur : ' + (e instanceof Error ? e.message : String(e));
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

<svelte:head>
	<title>Adresses — Pays — Admin</title>
</svelte:head>

<h1>Attribution des pays aux adresses</h1>

<div class="toolbar">
	<input type="search" placeholder="Rechercher dans les adresses..." bind:value={search} use:autofocus onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onSearchInput(); } }} oninput={onSearchInput} />
	<FacetDropdown label="Pays" options={countryOptions} searchable bind:selected={selectedCountry} onchange={onFilterChange} />
	<span class="toolbar-spacer"></span>
	<span class="count">{list.total.toLocaleString('fr-FR')} adresse{list.total > 1 ? 's' : ''}</span>
</div>

<div class="batch-bar">
	<select bind:value={batchCountry}>
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

<table class="addr-table">
	<thead>
		<tr>
			<th style="width:30px"><input type="checkbox" checked={allSelected} onchange={toggleAll} /></th>
			<th style="width:55%">Adresse</th>
			<th style="width:50px">Publis</th>
			<th>Pays</th>
		</tr>
	</thead>
	<tbody>
		{#each addresses as a (a.id)}
			<tr>
				<td><input type="checkbox" checked={selectedIds.has(a.id)} onchange={() => toggleSelect(a.id)} /></td>
				<td class="addr-cell">{a.raw_text}</td>
				<td class="num-cell">{a.publication_count}</td>
				<td>
					<div class="country-cell">
					{#each a.countries ?? [] as c}
						{@const found = a.found_countries.find(f => f.country_code === c)}
						<span class="country-tag" title={found ? `Trouvé par : ${methodsLabel(found.methods)}` : undefined}>
							{countryLabel(c)}
							<button class="tag-remove" onclick={() => removeCountry(a.id, c)}>×</button>
						</span>
					{/each}
					<span class="country-actions">
						{#each a.found_countries.filter(f => !a.countries?.includes(f.country_code)) as p}
							<button class="proposal-tag" title="Ajouter ce pays" onclick={() => addCountry(a.id, p.country_code)}>
								{countryLabel(p.country_code)} ?
								<span class="proposal-methods">{methodsLabel(p.methods)}</span>
							</button>
						{/each}
						<select class="add-country" onchange={(e) => { const v = (e.target as HTMLSelectElement).value; if (v) { addCountry(a.id, v); (e.target as HTMLSelectElement).value = ''; } }}>
							<option value="">+</option>
							{#each countries as c}
								<option value={c.code}>{c.name} ({c.code.toUpperCase()})</option>
							{/each}
						</select>
					</span>
					</div>
				</td>
			</tr>
		{/each}
	</tbody>
</table>

<Pagination page={list.page} pages={list.pages} onchange={(p) => { list.goToPage(p); syncUrl(); }} />

<style>
	h1 { font-size: 1.3rem; margin-bottom: 12px; }
	.toolbar input[type="search"] { width: 300px; }
	.batch-bar {
		display: flex; align-items: center; gap: 8px;
		padding: 8px 12px; margin-bottom: 10px;
		background: var(--accent-light); border-radius: 6px; font-size: 0.9rem;
	}
	.batch-bar select { padding: 5px 8px; font-size: 0.85rem; border: 1px solid var(--border); border-radius: 4px; }
	.batch-result { font-size: 0.85rem; color: var(--success); font-weight: 500; }
	.proposal-tag {
		display: inline-flex; align-items: center; gap: 4px;
		padding: 2px 8px; background: #fff8e1; color: #856404;
		border: 1px dashed #f5a623; border-radius: 3px; cursor: pointer;
		font-size: 0.78rem; font-weight: 500; white-space: nowrap;
	}
	.proposal-tag:hover { background: #ffecb3; }
	.proposal-methods { font-weight: 400; opacity: 0.8; }
	.addr-table {
		width: 100%; border-collapse: collapse; table-layout: fixed;
		background: var(--card); border: 1px solid var(--border); border-radius: 6px;
	}
	.addr-table thead th {
		background: var(--surface); padding: 8px 10px; text-align: left;
		font-size: 0.85rem; font-weight: 600; color: var(--muted);
		border-bottom: 2px solid var(--border);
	}
	.addr-table tbody tr { border-bottom: 1px solid var(--border-subtle); }
	.addr-table tbody tr:hover { background: var(--surface-hover); }
	.addr-table td { padding: 6px 10px; font-size: 0.9rem; vertical-align: middle; }
	.addr-cell { word-break: break-word; }
	.num-cell { text-align: center; color: var(--muted); font-size: 0.85rem; }
	.country-cell { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
	.country-actions { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; justify-content: flex-end; margin-left: auto; }
	.country-tag {
		display: inline-flex; align-items: center; gap: 2px;
		padding: 2px 6px; background: var(--success-light);
		border-radius: 3px; font-size: 0.78rem; color: var(--success); white-space: nowrap;
	}
	.tag-remove {
		background: none; border: none; cursor: pointer;
		color: #888; font-size: 0.8rem; padding: 0 1px; line-height: 1;
	}
	.tag-remove:hover { color: var(--danger); }
	.add-country {
		padding: 2px 4px; border: 1px solid var(--border); border-radius: 3px;
		font-size: 0.75rem; width: 32px; color: var(--muted); cursor: pointer;
	}
</style>
