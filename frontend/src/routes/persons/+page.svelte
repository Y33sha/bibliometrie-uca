<script lang="ts">
	import { onMount } from "svelte";
	import { page } from "$app/stores";
	import { base } from "$app/paths";
	import { titleCase } from "$lib/utils";
	import FacetDropdown from "$lib/components/FacetDropdown.svelte";
	import Pagination from "$lib/components/Pagination.svelte";
	import { usePaginatedFetch } from "$lib/composables/usePaginatedFetch.svelte";
	import { useFacets } from "$lib/composables/useFacets.svelte";
	import { useUrlFilters } from "$lib/composables/useUrlFilters.svelte";

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

	// --- Filter state ---
	let search = $state("");
	let selectedDepts: string[] = $state([]);
	let selectedRoles: string[] = $state([]);
	let selectedOrcid: string[] = $state([]);
	let selectedIdhal: string[] = $state([]);
	let selectedRh: string[] = $state(["yes"]);
	let currentSort = $state("name");

	function toggleSortName() {
		currentSort = currentSort === "name" ? "-name" : "name";
		dir.page = 1; syncUrl(); dir.load();
	}

	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		if (selectedDepts.length)
			params.set("department", selectedDepts.join(","));
		if (selectedRoles.length) params.set("role", selectedRoles.join(","));
		if (selectedOrcid.length === 1)
			params.set("has_orcid", selectedOrcid[0]);
		if (selectedIdhal.length === 1)
			params.set("has_idhal", selectedIdhal[0]);
		if (selectedRh.length === 1) params.set("has_rh", selectedRh[0]);
		return params;
	}

	// --- Composables ---
	const dir = usePaginatedFetch<Person>({
		endpoint: "/api/persons/directory",
		itemsKey: "persons",
		perPage: 50,
		apiKey: "persons-dir-list",
		buildParams() {
			const params = buildFilterParams();
			const q = search.trim();
			if (q) params.set("search", q);
			params.set("sort", currentSort);
			return params;
		},
	});

	const facets = useFacets({
		endpoint: "/api/persons/facets",
		apiKey: "persons-dir-facets",
		buildParams: buildFilterParams,
		facets: {
			depts: { type: "simple", apiKey: "departments" },
			roles: { type: "simple", apiKey: "roles" },
			orcid: {
				type: "boolean",
				apiKey: "orcid",
				yesLabel: "Avec ORCID",
				noLabel: "Sans ORCID",
			},
			idhal: {
				type: "boolean",
				apiKey: "idhal",
				yesLabel: "Avec idHAL",
				noLabel: "Sans idHAL",
			},
			rh: {
				type: "boolean",
				apiKey: "rh",
				yesLabel: "Oui",
				noLabel: "Non",
			},
		},
	});

	const url = useUrlFilters({
		basePath: "/persons",
		debounceMs: 300,
		filters: {
			selectedDepts: { type: "string_array", urlKey: "department" },
			selectedRoles: { type: "string_array", urlKey: "role" },
			selectedOrcid: { type: "string_array", urlKey: "has_orcid" },
			selectedIdhal: { type: "string_array", urlKey: "has_idhal" },
			hasRh: { type: "single", urlKey: "has_rh", defaultValue: "yes" },
			search: { type: "single", urlKey: "search" },
			currentSort: { type: "single", urlKey: "sort", defaultValue: "name" },
			currentPage: { type: "page", urlKey: "page" },
		},
	});

	// --- Handlers ---
	function syncUrl() {
		url.syncUrl(() => ({
			selectedDepts,
			selectedRoles,
			selectedOrcid,
			selectedIdhal,
			hasRh: selectedRh.length === 1 ? selectedRh[0] : "all",
			search,
			currentSort,
			currentPage: dir.page,
		}));
	}

	function onFilterChange() {
		dir.page = 1;
		syncUrl();
		dir.load();
		facets.load();
	}

	const onSearchInput = url.debouncedSearch(() => {
		dir.page = 1;
		syncUrl();
		dir.load();
	});

	onMount(async () => {
		const urlParams = $page.url.searchParams;
		const restored = url.restoreFromUrl(urlParams);
		if (restored.selectedDepts)
			selectedDepts = restored.selectedDepts as string[];
		if (restored.selectedRoles)
			selectedRoles = restored.selectedRoles as string[];
		if (restored.selectedOrcid)
			selectedOrcid = restored.selectedOrcid as string[];
		if (restored.selectedIdhal)
			selectedIdhal = restored.selectedIdhal as string[];
		if (restored.hasRh != null) {
			const rh = restored.hasRh as string;
			selectedRh = rh === "all" ? [] : [rh];
		}
		if (restored.search) search = restored.search as string;
		if (restored.currentSort) currentSort = restored.currentSort as string;
		if (restored.currentPage) dir.page = restored.currentPage as number;

		await facets.load();
		dir.load();
	});
</script>

<svelte:head>
	<title>Personnes — Bibliométrie UCA</title>
</svelte:head>

<div class="toolbar toolbar-card toolbar-sticky">
	<input
		type="text"
		placeholder="Rechercher par nom..."
		bind:value={search}
		oninput={onSearchInput}
	/>
	<FacetDropdown
		label="Département"
		options={facets.options.depts}
		searchable
		bind:selected={selectedDepts}
		onchange={onFilterChange}
	/>
	<FacetDropdown
		label="Rôle"
		options={facets.options.roles}
		searchable
		bind:selected={selectedRoles}
		onchange={onFilterChange}
	/>
	<FacetDropdown
		label="ORCID"
		options={facets.options.orcid}
		bind:selected={selectedOrcid}
		onchange={onFilterChange}
	/>
	<FacetDropdown
		label="idHAL"
		options={facets.options.idhal}
		bind:selected={selectedIdhal}
		onchange={onFilterChange}
	/>
	<FacetDropdown
		label="Base RH"
		options={facets.options.rh}
		bind:selected={selectedRh}
		onchange={onFilterChange}
	/>
	<span class="count">{dir.total} personne{dir.total > 1 ? "s" : ""}</span>
</div>

<table>
	<thead>
		<tr>
			<th class="sortable" class:active={currentSort === 'name' || currentSort === '-name'} onclick={toggleSortName}>Nom {currentSort === 'name' ? '▲' : currentSort === '-name' ? '▼' : ''}</th>
			<th>Rôle</th>
			<th>Département</th>
			<th>ORCID</th>
			<th>idHAL</th>
		</tr>
	</thead>
	<tbody>
		{#if dir.items.length === 0}
			<tr
				><td colspan="5" class="no-results">Aucune personne trouvée</td
				></tr
			>
		{:else}
			{#each dir.items as p (p.id)}
				<tr>
					<td>
						<a href="{base}/persons/{p.id}" class="person-name">
							<span class="person-last"
								>{titleCase(p.last_name)}</span
							>
							{titleCase(p.first_name)}
						</a>
						{#if p.has_rh}<span class="rh-check" title="Base RH"
								>&#x2713;</span
							>{/if}
					</td>
					<td>
						{#if p.role_title}
							<span class="role-tag">{p.role_title}</span>
						{/if}
					</td>
					<td>{p.department_name || ""}</td>
					<td>
						{#each p.orcids || [] as oid}
							<a
								href="https://orcid.org/{oid.value ?? oid}"
								target="_blank"
								rel="noopener"
								class="id-badge"
								class:id-confirmed={oid.confirmed}
								>{oid.value ?? oid}</a
							>
						{/each}
					</td>
					<td>
						{#each p.idhals || [] as idh}
							<a
								href="https://hal.science/search/index/?q=%2A&authIdHal_s={idh.value ??
									idh}"
								target="_blank"
								rel="noopener"
								class="id-badge"
								class:id-confirmed={idh.confirmed}
								>{idh.value ?? idh}</a
							>
						{/each}
					</td>
				</tr>
			{/each}
		{/if}
	</tbody>
</table>

<Pagination
	page={dir.page}
	pages={dir.pages}
	onchange={(p) => {
		dir.goToPage(p);
		syncUrl();
	}}
/>

<style>
	h2 {
		font-size: 1.2rem;
		font-weight: 600;
		margin: 0 0 14px;
	}
	.toolbar input[type="text"] {
		width: 240px;
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
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.3px;
		border-bottom: 1px solid var(--border);
		white-space: nowrap;
	}
	thead th.sortable { cursor: pointer; user-select: none; }
	thead th.sortable:hover { color: var(--accent); }
	thead th.sortable.active { color: var(--accent); }
	tbody tr {
		border-bottom: 1px solid #f0efec;
	}
	tbody tr:last-child {
		border-bottom: none;
	}
	tbody tr:hover {
		background: #fafaf8;
	}
	td {
		padding: 10px 12px;
		font-size: 0.95rem;
		vertical-align: middle;
	}
	td a {
		color: var(--accent);
		text-decoration: none;
	}
	td a:hover {
		text-decoration: underline;
	}
	td a.id-badge:hover {
		text-decoration: none;
	}
	.person-name {
		font-weight: 500;
	}
	.person-last {
		font-weight: 600;
	}
</style>
