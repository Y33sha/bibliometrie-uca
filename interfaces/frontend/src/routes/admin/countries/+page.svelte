<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { replaceState } from '$app/navigation';
	import { addresses as addressesApi, api } from '$lib/api';
	import Pagination from '$lib/components/Pagination.svelte';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import type { FacetOption } from '$lib/components/FacetDropdown.svelte';

	import type { components } from '$lib/api/schema';
	type Address = components['schemas']['AddressForCountryAttribution'];
	type Country = components['schemas']['CountryOut'];

	let addresses: Address[] = $state([]);
	let countries: Country[] = $state([]);
	let countryMap: Record<string, string> = $state({});
	let total = $state(0);
	let page = $state(1);
	let pages = $state(1);
	let loading = $state(false);

	let search = $state('');
	let selectedHasCountry: string[] = $state([]);
	let selectedCountry: string[] = $state([]);
	let debounceTimer: ReturnType<typeof setTimeout>;

	// Batch
	let selectedIds: Set<number> = $state(new Set());
	let batchCountry = $state('');
	const allSelected = $derived(addresses.length > 0 && addresses.every(a => selectedIds.has(a.id)));

	const hasCountryOptions: FacetOption[] = [
		{ value: 'yes', text: 'Avec pays' },
		{ value: 'no', text: 'Sans pays' },
	];
	let countryFacets: { code: string; count: number }[] = $state([]);
	const countryOptions = $derived.by(() => {
		if (countryFacets.length > 0) {
			const xx = countryFacets.find(f => f.code === 'xx');
			const rest = countryFacets.filter(f => f.code !== 'xx');
			const sorted = [...(xx ? [xx] : []), ...rest];
			return sorted.map(f => ({
				value: f.code,
				text: `${countryMap[f.code] || f.code.toUpperCase()} (${f.code.toUpperCase()})`,
				count: f.count
			}));
		}
		return countries.map(c => ({ value: c.code, text: `${c.name} (${c.code.toUpperCase()})` }));
	});

	async function loadCountries() {
		countries = await api<Country[]>('/api/countries');
		countryMap = Object.fromEntries(countries.map(c => [c.code, c.name]));
	}

	async function loadAddresses() {
		loading = true;
		const params = new URLSearchParams({ page: String(page), per_page: '50' });
		if (search.trim()) params.set('search', search.trim());
		if (selectedHasCountry.length === 1) params.set('has_country', selectedHasCountry[0]);
		if (selectedCountry.length === 1) params.set('country_code', selectedCountry[0]);
		if (suggestMode) params.set('suggest', 'true');
		if (selectedSugCountry.length === 1) params.set('suggested_country', selectedSugCountry[0]);
		const data = await api<{ total: number; page: number; pages: number; addresses: Address[]; suggestion_facets?: { code: string; count: number }[]; country_facets?: { code: string; count: number }[] }>(
			'/api/addresses/countries?' + params, { key: 'countries-addr-list' }
		);
		addresses = data.addresses;
		total = data.total;
		pages = data.pages;
		page = data.page;
		if (data.country_facets) {
			countryFacets = data.country_facets;
		}
		if (data.suggestion_facets) {
			sugFacetOptions = data.suggestion_facets.map(f => ({
				value: f.code,
				text: countryLabel(f.code),
				count: f.count,
			}));
		}
		loading = false;
	}

	function syncUrl() {
		const p = new URLSearchParams();
		if (page > 1) p.set('page', String(page));
		if (search.trim()) p.set('search', search.trim());
		if (selectedCountry.length === 1) p.set('country', selectedCountry[0]);
		if (selectedHasCountry.length === 1) p.set('has_country', selectedHasCountry[0]);
		if (selectedSugCountry.length === 1) p.set('sug_country', selectedSugCountry[0]);
		const qs = p.toString();
		replaceState(`${base}/admin/countries` + (qs ? '?' + qs : ''), {});
	}

	function onFilterChange() {
		page = 1;
		selectedIds = new Set();
		// Synchroniser le select pays avec la facette pays suggéré
		if (selectedSugCountry.length === 1) {
			batchCountry = selectedSugCountry[0];
		}
		syncUrl();
		loadAddresses();
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
		if (selectedHasCountry.includes('no') || suggestMode) {
			loadAddresses();
		} else {
			addr.countries = newList;
			addresses = [...addresses];
		}
	}

	async function removeCountry(addrId: number, code: string) {
		const addr = addresses.find(a => a.id === addrId);
		if (!addr) return;
		const newList = (addr.countries || []).filter(c => c !== code);
		await addressesApi.setCountry(addrId, { countries: newList.length ? newList : null });
		addr.countries = newList.length ? newList : null;
		addresses = [...addresses];
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

	// Suggestions
	let suggestMode = $state(false);
	let sugFacetOptions: FacetOption[] = $state([]);
	let selectedSugCountry: string[] = $state([]);

	// Vrai ssi au moins un filtre est actif. Garde l'« Ajouter à tout le filtre »
	// (mêmes conditions que le body construit dans batchAddCountry) : sans filtre,
	// l'action viserait toutes les adresses — le backend la refuse (400), on
	// masque le bouton côté UI. Aligné sur le garde-fou serveur.
	const hasActiveFilter = $derived(
		search.trim() !== '' ||
			selectedHasCountry.length === 1 ||
			selectedCountry.length === 1 ||
			selectedSugCountry.length === 1,
	);

	function toggleSuggest() {
		suggestMode = !suggestMode;
		selectedSugCountry = [];
		sugFacetOptions = [];
		if (suggestMode) {
			selectedHasCountry = ['no'];
			selectedCountry = [];
		} else {
			selectedHasCountry = [];
		}
		page = 1;
		loadAddresses();
	}

	async function acceptSuggestion(addrId: number, code: string) {
		await addCountry(addrId, code);
	}

	async function batchAddCountry(applyToAll = false) {
		if (!batchCountry) return;
		batchApplying = true;
		batchResult = '';
		const body: Record<string, unknown> = { country_code: batchCountry };
		if (applyToAll) {
			if (search.trim()) body.search = search.trim();
			if (selectedHasCountry.length === 1) body.has_country = selectedHasCountry[0];
			if (selectedCountry.length === 1) body.country_code = selectedCountry[0];
			if (selectedSugCountry.length === 1) body.suggested_country = selectedSugCountry[0];
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
		loadAddresses();
		setTimeout(() => { batchResult = ''; }, 3000);
	}

	onMount(() => {
		const params = new URLSearchParams(window.location.search);
		if (params.get('page')) page = parseInt(params.get('page')!) || 1;
		if (params.get('search')) search = params.get('search')!;
		if (params.get('country')) selectedCountry = [params.get('country')!];
		if (params.get('has_country')) selectedHasCountry = [params.get('has_country')!];
		if (params.get('sug_country')) selectedSugCountry = [params.get('sug_country')!];
		loadCountries();
		loadAddresses();
	});
</script>

<svelte:head>
	<title>Adresses — Pays — Admin</title>
</svelte:head>

<h1>Attribution des pays aux adresses</h1>

<div class="toolbar">
	<input type="text" placeholder="Rechercher dans les adresses..." bind:value={search} oninput={onSearchInput} />
	<button class="btn-suggest" class:active={suggestMode} onclick={toggleSuggest}>
		{suggestMode ? 'Suggestions actives' : 'Activer suggestions'}
	</button>
	{#if !suggestMode}
		<FacetDropdown label="Pays" options={hasCountryOptions} bind:selected={selectedHasCountry} onchange={onFilterChange} />
		<FacetDropdown label="Filtrer pays" options={countryOptions} searchable bind:selected={selectedCountry} onchange={onFilterChange} />
	{:else if sugFacetOptions.length > 0}
		<FacetDropdown label="Pays suggéré" options={sugFacetOptions} bind:selected={selectedSugCountry} onchange={onFilterChange} />
	{/if}
	<span class="toolbar-spacer"></span>
	<span class="count">{total.toLocaleString('fr-FR')} adresse{total > 1 ? 's' : ''}</span>
</div>

<div class="batch-bar">
	<select bind:value={batchCountry}>
		<option value="">— Choisir un pays à ajouter —</option>
		{#each countries as c}
			<option value={c.code}>{c.name} ({c.code.toUpperCase()})</option>
		{/each}
	</select>
	{#if selectedIds.size > 0 && batchCountry}
		<button class="btn-primary" onclick={() => batchAddCountry(false)} disabled={batchApplying}>
			Ajouter aux {selectedIds.size} sélectionnée{selectedIds.size > 1 ? 's' : ''}
		</button>
	{/if}
	{#if batchCountry && hasActiveFilter}
		<button class="btn-secondary" onclick={() => batchAddCountry(true)} disabled={batchApplying}>
			Ajouter à tout le filtre ({total.toLocaleString('fr-FR')})
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
			<th>Adresse</th>
			<th style="width:50px">Publis</th>
			<th style="width:250px">Pays</th>
		</tr>
	</thead>
	<tbody>
		{#each addresses as a (a.id)}
			<tr>
				<td><input type="checkbox" checked={selectedIds.has(a.id)} onchange={() => toggleSelect(a.id)} /></td>
				<td class="addr-cell">{a.raw_text}</td>
				<td class="num-cell">{a.pub_count}</td>
				<td class="country-cell">
					{#if a.countries}
						{#each a.countries as c}
							<span class="country-tag">
								{countryLabel(c)}
								<button class="tag-remove" onclick={() => removeCountry(a.id, c)}>×</button>
							</span>
						{/each}
					{:else if suggestMode && a.suggested_countries && a.suggested_countries.length > 0}
						{#each a.suggested_countries as s}
							<button class="sug-tag" onclick={() => acceptSuggestion(a.id, s.code)}
								title="{s.count} adresse{s.count > 1 ? 's' : ''} similaire{s.count > 1 ? 's' : ''} avec ce pays">
								{countryLabel(s.code)} ?
							</button>
						{/each}
					{/if}
					<select class="add-country" onchange={(e) => { const v = (e.target as HTMLSelectElement).value; if (v) { addCountry(a.id, v); (e.target as HTMLSelectElement).value = ''; } }}>
						<option value="">+</option>
						{#each countries as c}
							<option value={c.code}>{c.name} ({c.code.toUpperCase()})</option>
						{/each}
					</select>
				</td>
			</tr>
		{/each}
	</tbody>
</table>

<Pagination {page} {pages} onchange={(p) => { page = p; syncUrl(); loadAddresses(); }} />

<style>
	h1 { font-size: 1.3rem; margin-bottom: 12px; }
	.toolbar input[type="text"] { width: 300px; }
	.batch-bar {
		display: flex; align-items: center; gap: 8px;
		padding: 8px 12px; margin-bottom: 10px;
		background: #e8f0f8; border-radius: 6px; font-size: 0.9rem;
	}
	.batch-bar select { padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px; }
	.btn-secondary:disabled { opacity: 0.5; cursor: default; }
	.btn-secondary {
		padding: 4px 12px; background: #f0f0f0; color: var(--text);
		border: 1px solid var(--border); border-radius: 4px; cursor: pointer; font-size: 0.85rem;
	}
	.btn-secondary:hover { background: #e0e0e0; }
	.batch-result { font-size: 0.85rem; color: #2e7d32; font-weight: 500; }
	.btn-suggest {
		padding: 4px 12px; background: #f0f0f0; color: var(--text);
		border: 1px solid var(--border); border-radius: 4px; cursor: pointer;
		font-size: 0.85rem; font-weight: 500;
	}
	.btn-suggest:hover { background: #e0e0e0; }
	.btn-suggest.active {
		background: #fff3cd; border-color: #f5a623; color: #856404;
	}
	.sug-tag {
		display: inline-flex; align-items: center; gap: 2px;
		padding: 2px 8px; background: #fff8e1; color: #856404;
		border: 1px dashed #f5a623; border-radius: 3px; cursor: pointer;
		font-size: 0.78rem; font-weight: 500;
	}
	.sug-tag:hover { background: #ffecb3; }
	.addr-table {
		width: 100%; border-collapse: collapse;
		background: var(--card); border: 1px solid var(--border); border-radius: 6px;
	}
	.addr-table thead th {
		background: #f5f4f1; padding: 8px 10px; text-align: left;
		font-size: 0.85rem; font-weight: 600; color: var(--muted);
		border-bottom: 2px solid var(--border);
	}
	.addr-table tbody tr { border-bottom: 1px solid #f0efec; }
	.addr-table tbody tr:hover { background: #fafaf8; }
	.addr-table td { padding: 6px 10px; font-size: 0.9rem; vertical-align: middle; }
	.addr-cell { max-width: 500px; word-break: break-word; }
	.num-cell { text-align: center; color: var(--muted); font-size: 0.85rem; }
	.country-cell { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
	.country-tag {
		display: inline-flex; align-items: center; gap: 2px;
		padding: 2px 6px; background: #e8f5e9;
		border-radius: 3px; font-size: 0.78rem; color: #2e7d32; white-space: nowrap;
	}
	.tag-remove {
		background: none; border: none; cursor: pointer;
		color: #888; font-size: 0.8rem; padding: 0 1px; line-height: 1;
	}
	.tag-remove:hover { color: #c0392b; }
	.add-country {
		padding: 2px 4px; border: 1px solid var(--border); border-radius: 3px;
		font-size: 0.75rem; width: 32px; color: var(--muted); cursor: pointer;
	}
</style>
