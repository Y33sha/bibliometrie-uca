<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import { api } from '$lib/api';
	import { titleCase } from '$lib/utils';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import type { FacetOption } from '$lib/components/FacetDropdown.svelte';

	interface Person {
		id: number;
		last_name: string;
		first_name: string;
		role_title: string | null;
		department_name: string | null;
		has_rh: boolean;
		orcids: string[];
		idhals: string[];
	}

	interface DirectoryResponse {
		total: number;
		page: number;
		pages: number;
		per_page: number;
		persons: Person[];
	}

	let persons: Person[] = $state([]);
	let total = $state(0);
	let currentPage = $state(1);
	let totalPages = $state(1);
	const perPage = 50;

	let search = $state('');
	let debounceTimer: ReturnType<typeof setTimeout>;

	let deptOptions: FacetOption[] = $state([]);
	let roleOptions: FacetOption[] = $state([]);
	let orcidOptions: FacetOption[] = $state([]);
	let idhalOptions: FacetOption[] = $state([]);
	let rhOptions: FacetOption[] = $state([]);
	let selectedDepts: string[] = $state([]);
	let selectedRoles: string[] = $state([]);
	let selectedOrcid: string[] = $state([]);
	let selectedIdhal: string[] = $state([]);
	let selectedRh: string[] = $state(['yes']);

	function syncUrl() {
		const p = new URLSearchParams();
		if (selectedDepts.length) p.set('department', selectedDepts.join(','));
		if (selectedRoles.length) p.set('role', selectedRoles.join(','));
		if (selectedOrcid.length === 1) p.set('has_orcid', selectedOrcid[0]);
		if (selectedIdhal.length === 1) p.set('has_idhal', selectedIdhal[0]);
		if (selectedRh.length === 1) p.set('has_rh', selectedRh[0]);
		if (search.trim()) p.set('search', search.trim());
		if (currentPage > 1) p.set('page', String(currentPage));
		const qs = p.toString();
		history.replaceState(history.state, '', base + '/persons' + (qs ? '?' + qs : ''));
	}

	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		if (selectedDepts.length) params.set('department', selectedDepts.join(','));
		if (selectedRoles.length) params.set('role', selectedRoles.join(','));
		if (selectedOrcid.length === 1) params.set('has_orcid', selectedOrcid[0]);
		if (selectedIdhal.length === 1) params.set('has_idhal', selectedIdhal[0]);
		if (selectedRh.length === 1) params.set('has_rh', selectedRh[0]);
		return params;
	}

	async function loadFacets() {
		const params = buildFilterParams();
		const data = await api<{
			departments: { value: string; count: number }[];
			roles: { value: string; count: number }[];
			orcid: { yes: number; no: number };
			idhal: { yes: number; no: number };
			rh: { yes: number; no: number };
		}>('/api/persons/facets?' + params);
		deptOptions = data.departments.map((d) => ({
			value: d.value, text: d.value, count: d.count
		}));
		roleOptions = data.roles.map((r) => ({
			value: r.value, text: r.value, count: r.count
		}));
		orcidOptions = [
			{ value: 'yes', text: 'Avec ORCID', count: data.orcid.yes },
			{ value: 'no', text: 'Sans ORCID', count: data.orcid.no }
		];
		idhalOptions = [
			{ value: 'yes', text: 'Avec idHAL', count: data.idhal.yes },
			{ value: 'no', text: 'Sans idHAL', count: data.idhal.no }
		];
		rhOptions = [
			{ value: 'yes', text: 'Oui', count: data.rh.yes },
			{ value: 'no', text: 'Non', count: data.rh.no }
		];
	}

	async function loadData() {
		const params = buildFilterParams();
		params.set('page', String(currentPage));
		params.set('per_page', String(perPage));
		const q = search.trim();
		if (q) params.set('search', q);

		const data = await api<DirectoryResponse>('/api/persons/directory?' + params);
		total = data.total;
		totalPages = data.pages;
		currentPage = data.page;
		persons = data.persons;
	}

	function onFilterChange() {
		currentPage = 1;
		syncUrl();
		loadData();
		loadFacets();
	}

	function onSearchInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => {
			currentPage = 1;
			syncUrl();
			loadData();
		}, 300);
	}

	onMount(async () => {
		const urlParams = $page.url.searchParams;
		if (urlParams.get('department')) selectedDepts = urlParams.get('department')!.split(',');
		if (urlParams.get('role')) selectedRoles = urlParams.get('role')!.split(',');
		if (urlParams.get('has_orcid')) selectedOrcid = [urlParams.get('has_orcid')!];
		if (urlParams.get('has_idhal')) selectedIdhal = [urlParams.get('has_idhal')!];
		if (urlParams.has('has_rh')) selectedRh = [urlParams.get('has_rh')!];
		if (urlParams.get('search')) search = urlParams.get('search')!;
		if (urlParams.get('page')) currentPage = Number(urlParams.get('page')) || 1;

		await loadFacets();
		loadData();
	});
</script>

<svelte:head>
	<title>Personnes — Bibliométrie UCA</title>
</svelte:head>

<h2>Personnes UCA</h2>
<p class="subtitle">Enseignants-chercheurs de l'Université Clermont Auvergne</p>

<div class="toolbar">
	<input type="text" placeholder="Rechercher par nom..." bind:value={search} oninput={onSearchInput} />
	<FacetDropdown label="Département" options={deptOptions} searchable bind:selected={selectedDepts} onchange={onFilterChange} />
	<FacetDropdown label="Rôle" options={roleOptions} searchable bind:selected={selectedRoles} onchange={onFilterChange} />
	<FacetDropdown label="ORCID" options={orcidOptions} bind:selected={selectedOrcid} onchange={onFilterChange} />
	<FacetDropdown label="idHAL" options={idhalOptions} bind:selected={selectedIdhal} onchange={onFilterChange} />
	<FacetDropdown label="Base RH" options={rhOptions} bind:selected={selectedRh} onchange={onFilterChange} />
	<span class="count">{total} personne{total > 1 ? 's' : ''}</span>
</div>

<table>
	<thead>
		<tr>
			<th>Nom</th>
			<th>Rôle</th>
			<th>Département</th>
			<th>ORCID</th>
			<th>idHAL</th>
		</tr>
	</thead>
	<tbody>
		{#if persons.length === 0}
			<tr><td colspan="5" class="no-results">Aucune personne trouvée</td></tr>
		{:else}
			{#each persons as p (p.id)}
				<tr>
					<td>
						<a href="{base}/persons/{p.id}" class="person-name">
							<span class="person-last">{titleCase(p.last_name)}</span>
							{titleCase(p.first_name)}
						</a>
						{#if p.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
					</td>
					<td>
						{#if p.role_title}
							<span class="role-tag">{p.role_title}</span>
						{/if}
					</td>
					<td>{p.department_name || ''}</td>
					<td>
						{#each p.orcids || [] as oid}
							<a href="https://orcid.org/{oid}" target="_blank" rel="noopener" class="id-badge">{oid}</a>
						{/each}
					</td>
					<td>
						{#each p.idhals || [] as idh}
							<a href="https://hal.science/search/index/?q=%2A&authIdHal_s={idh}" target="_blank" rel="noopener" class="id-badge">{idh}</a>
						{/each}
					</td>
				</tr>
			{/each}
		{/if}
	</tbody>
</table>

<Pagination page={currentPage} pages={totalPages} onchange={(p) => { currentPage = p; syncUrl(); loadData(); }} />

<style>
	h2 { font-size: 17px; font-weight: 600; margin: 0 0 14px; }
	.subtitle { font-size: 13px; color: var(--muted); margin: -10px 0 16px; }

	.toolbar {
		display: flex;
		gap: 8px;
		align-items: center;
		flex-wrap: wrap;
		margin-bottom: 12px;
		padding: 10px 14px;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
	}
	.toolbar input[type='text'] {
		padding: 6px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 13px;
		width: 240px;
	}
	.count {
		margin-left: auto;
		font-size: 12px;
		color: var(--muted);
		white-space: nowrap;
	}

	table {
		width: 100%;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
	}
	thead th {
		background: #f5f4f1;
		padding: 9px 12px;
		text-align: left;
		font-size: 12px;
		font-weight: 600;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.3px;
		border-bottom: 1px solid var(--border);
		white-space: nowrap;
	}
	tbody tr { border-bottom: 1px solid #f0efec; }
	tbody tr:last-child { border-bottom: none; }
	tbody tr:hover { background: #fafaf8; }
	td {
		padding: 10px 12px;
		font-size: 13px;
		vertical-align: middle;
	}
	td a { color: var(--accent); text-decoration: none; }
	td a:hover { text-decoration: underline; }

	.person-name { font-weight: 500; }
	.person-last { font-weight: 600; }
	.role-tag {
		display: inline-block;
		padding: 2px 7px;
		background: #f0efec;
		border-radius: 3px;
		font-size: 11px;
		color: var(--muted);
		white-space: nowrap;
	}
	.id-badge {
		display: inline-block;
		padding: 2px 7px;
		background: #e8f0f8;
		border-radius: 3px;
		font-size: 11px;
		color: var(--accent);
		text-decoration: none;
		white-space: nowrap;
	}
	.id-badge:hover { background: #d4e4f3; text-decoration: none; }
	.no-results { text-align: center; padding: 40px; color: var(--muted); }
	.rh-check {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 15px;
		height: 15px;
		border-radius: 50%;
		background: var(--accent, #3b82f6);
		color: white;
		font-size: 10px;
		font-weight: 700;
		margin-left: 4px;
		vertical-align: middle;
		line-height: 1;
	}
</style>
