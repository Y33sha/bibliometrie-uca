<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { api } from '$lib/api';
	import { sanitizeTitle } from '$lib/utils';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import type { FacetOption } from '$lib/components/FacetDropdown.svelte';
	import Pagination from '$lib/components/Pagination.svelte';

	/* ── Types ── */

	interface PersonStats {
		total_persons: number;
		linked_persons: number;
		linked_authors: number;
		departments: number;
	}

	interface LinkedAuthor {
		id: number;
		source: string;
		full_name: string;
		orcid?: string;
		idhal?: string;
	}

	interface PersonIdentifier {
		id: number;
		id_type: string;
		id_value: string;
		source: string;
		rejected: boolean;
	}

	interface Person {
		id: number;
		first_name: string;
		last_name: string;
		department_name?: string;
		role_title?: string;
		start_date?: string;
		end_date?: string;
		has_rh?: boolean;
		linked_authors?: LinkedAuthor[];
		identifiers?: PersonIdentifier[];
	}

	interface PersonListResponse {
		total: number;
		page: number;
		pages: number;
		persons: Person[];
	}

	interface Candidate {
		id: number;
		source: string;
		full_name: string;
		orcid?: string;
		idhal?: string;
		openalex_id?: string;
		pub_count: number;
		uca_pub_count: number;
		person_id: number | null;
	}

	interface Signature {
		source: string;
		raw_affiliation: string;
	}

	interface Publication {
		pub_year: number | null;
		title: string;
		doi?: string;
		is_uca?: boolean;
	}

	interface AuthorDetails {
		signatures: Signature[];
		publications: Publication[];
	}

	/* ── State ── */

	let stats: PersonStats | null = $state(null);

	let search = $state('');
	let selectedDepts: string[] = $state([]);
	let selectedRoles: string[] = $state([]);
	let selectedLinked: string[] = $state([]);
	let selectedOrcid: string[] = $state([]);
	let selectedIdhal: string[] = $state([]);
	let selectedRh: string[] = $state([]);

	let deptOptions: FacetOption[] = $state([]);
	let roleOptions: FacetOption[] = $state([]);
	let linkedOptions: FacetOption[] = $state([
		{ value: 'yes', text: 'Rattachées' },
		{ value: 'no', text: 'Non rattachées' }
	]);
	let orcidOptions: FacetOption[] = $state([
		{ value: 'yes', text: 'Avec ORCID' },
		{ value: 'no', text: 'Sans ORCID' }
	]);
	let idhalOptions: FacetOption[] = $state([
		{ value: 'yes', text: 'Avec idHAL' },
		{ value: 'no', text: 'Sans idHAL' }
	]);
	let rhOptions: FacetOption[] = $state([
		{ value: 'yes', text: 'Oui' },
		{ value: 'no', text: 'Non' }
	]);

	let currentPage = $state(1);
	let totalPages = $state(0);
	let totalCount = $state(0);
	let persons: Person[] = $state([]);
	let loading = $state(false);

	let searchTimeout: ReturnType<typeof setTimeout> | null = null;

	/* Expanded candidates per person id */
	let expandedPersons: Record<number, Candidate[] | 'loading'> = $state({});

	/* Expanded author details keyed by "source-authorId" */
	let expandedDetails: Record<string, AuthorDetails | 'loading'> = $state({});

	/* Identifier add form state: personId → { open, id_type, id_value, error } */
	let idForms: Record<number, { id_type: string; id_value: string; error: string }> = $state({});

	/* Expanded linked authors (collapsed by default) */
	let expandedAuthors: Record<number, boolean> = $state({});

	/* Merge search state */
	interface MergeSearch { query: string; results: { id: number; first_name: string; last_name: string; department_name: string | null; has_rh: boolean }[]; loading: boolean }
	let mergeSearches: Record<number, MergeSearch> = $state({});
	let mergeTimers: Record<number, ReturnType<typeof setTimeout>> = {};

	/* ── Derived ── */

	const unlinkedCount = $derived(
		stats ? stats.total_persons - stats.linked_persons : 0
	);

	/* ── Data loading ── */

	async function loadStats() {
		stats = await api<PersonStats>('/api/persons/stats');
	}

	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		if (selectedDepts.length) params.set('department', selectedDepts.join(','));
		if (selectedRoles.length) params.set('role', selectedRoles.join(','));
		if (selectedLinked.length === 1) params.set('linked', selectedLinked[0]);
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
			linked: { yes: number; no: number } | null;
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
		if (data.linked) {
			linkedOptions = [
				{ value: 'yes', text: 'Rattachées', count: data.linked.yes },
				{ value: 'no', text: 'Non rattachées', count: data.linked.no }
			];
		}
	}

	async function loadTable() {
		loading = true;
		const params = new URLSearchParams({
			page: String(currentPage),
			per_page: '50'
		});
		if (search) params.set('search', search);
		if (selectedDepts.length === 1) params.set('department', selectedDepts[0]);
		if (selectedRoles.length === 1) params.set('role', selectedRoles[0]);
		if (selectedLinked.length === 1) params.set('linked', selectedLinked[0]);
		if (selectedOrcid.length === 1) params.set('has_orcid', selectedOrcid[0]);
		if (selectedIdhal.length === 1) params.set('has_idhal', selectedIdhal[0]);
		if (selectedRh.length === 1) params.set('has_rh', selectedRh[0]);

		const data = await api<PersonListResponse>('/api/persons?' + params);
		persons = data.persons;
		totalCount = data.total;
		totalPages = data.pages;
		currentPage = data.page;
		loading = false;
		updateUrl();
	}

	/* ── URL state ── */

	function updateUrl() {
		const url = new URL(window.location.href);
		const setOrDel = (key: string, val: string) => {
			if (val) url.searchParams.set(key, val);
			else url.searchParams.delete(key);
		};
		setOrDel('p', currentPage > 1 ? String(currentPage) : '');
		setOrDel('search', search);
		setOrDel('dept', selectedDepts.length === 1 ? selectedDepts[0] : '');
		setOrDel('role', selectedRoles.length === 1 ? selectedRoles[0] : '');
		setOrDel('linked', selectedLinked.length === 1 ? selectedLinked[0] : '');
		setOrDel('orcid', selectedOrcid.length === 1 ? selectedOrcid[0] : '');
		setOrDel('idhal', selectedIdhal.length === 1 ? selectedIdhal[0] : '');
		setOrDel('rh', selectedRh.length === 1 ? selectedRh[0] : '');
		history.replaceState(null, '', url);
	}

	function readUrlFilters() {
		const p = new URLSearchParams(window.location.search);
		if (p.get('p')) currentPage = Math.max(1, parseInt(p.get('p')!, 10) || 1);
		if (p.get('search')) search = p.get('search')!;
		if (p.get('dept')) selectedDepts = [p.get('dept')!];
		if (p.get('role')) selectedRoles = [p.get('role')!];
		if (p.get('linked')) selectedLinked = [p.get('linked')!];
		if (p.get('orcid')) selectedOrcid = [p.get('orcid')!];
		if (p.get('idhal')) selectedIdhal = [p.get('idhal')!];
		if (p.get('rh')) selectedRh = [p.get('rh')!];
	}

	/* ── Event handlers ── */

	function handleSearch() {
		if (searchTimeout) clearTimeout(searchTimeout);
		searchTimeout = setTimeout(() => {
			currentPage = 1;
			loadTable();
		}, 400);
	}

	function handleFilterChange() {
		currentPage = 1;
		loadTable();
		loadFacets();
	}

	function handlePageChange(p: number) {
		currentPage = p;
		loadTable();
		window.scrollTo(0, 0);
	}

	/* ── Candidates expand/collapse ── */

	async function toggleCandidates(personId: number) {
		if (personId in expandedPersons) {
			const next = { ...expandedPersons };
			delete next[personId];
			expandedPersons = next;
			return;
		}
		expandedPersons = { ...expandedPersons, [personId]: 'loading' };
		const candidates = await api<Candidate[]>(`/api/persons/${personId}/candidates`);
		expandedPersons = { ...expandedPersons, [personId]: candidates };
	}

	/* ── Author detail expand/collapse ── */

	function detailKey(source: string, authorId: number): string {
		return `${source}-${authorId}`;
	}

	async function toggleAuthorDetail(source: string, authorId: number) {
		const key = detailKey(source, authorId);
		if (key in expandedDetails) {
			const next = { ...expandedDetails };
			delete next[key];
			expandedDetails = next;
			return;
		}
		expandedDetails = { ...expandedDetails, [key]: 'loading' };
		const details = await api<AuthorDetails>(`/api/authors/${source}/${authorId}/details`);
		expandedDetails = { ...expandedDetails, [key]: details };
	}

	/* ── Link / Unlink ── */

	async function linkAuthor(personId: number, source: string, authorId: number) {
		await fetch(`${base}/api/persons/${personId}/link`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ author_id: authorId, source })
		});
		loadStats();
		await refreshPersonRow(personId);
	}

	async function unlinkAuthor(personId: number, source: string, authorId: number) {
		await fetch(`${base}/api/persons/${personId}/link/${source}/${authorId}`, {
			method: 'DELETE'
		});
		loadStats();
		await refreshPersonRow(personId);
	}

	async function refreshPersonRow(personId: number) {
		const updated = await api<Person>(`/api/persons/${personId}`);
		persons = persons.map((p) => (p.id === personId ? updated : p));

		/* If candidates panel is open, refresh it so "Rattacher" buttons update */
		if (personId in expandedPersons && expandedPersons[personId] !== 'loading') {
			const candidates = await api<Candidate[]>(`/api/persons/${personId}/candidates`);
			expandedPersons = { ...expandedPersons, [personId]: candidates };
		}
	}

	/* ── Identifiers ── */

	function toggleIdForm(personId: number) {
		if (personId in idForms) {
			const next = { ...idForms };
			delete next[personId];
			idForms = next;
		} else {
			idForms = { ...idForms, [personId]: { id_type: 'orcid', id_value: '', error: '' } };
		}
	}

	async function addIdentifier(personId: number) {
		const form = idForms[personId];
		if (!form || !form.id_value.trim()) return;

		const resp = await fetch(`${base}/api/persons/${personId}/identifier`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ id_type: form.id_type, id_value: form.id_value.trim() })
		});

		if (!resp.ok) {
			const err = await resp.json().catch(() => ({ detail: 'Erreur inconnue' }));
			idForms = { ...idForms, [personId]: { ...form, error: err.detail || `Erreur ${resp.status}` } };
			return;
		}

		// Fermer le formulaire et rafraîchir la ligne
		const next = { ...idForms };
		delete next[personId];
		idForms = next;
		await loadTable();
	}

	async function removeIdentifier(personId: number, idType: string, idValue: string) {
		await fetch(`${base}/api/persons/${personId}/identifier/${idType}/${encodeURIComponent(idValue)}`, {
			method: 'DELETE'
		});
		await loadTable();
	}

	async function toggleRejectIdentifier(identId: number) {
		await fetch(`${base}/api/person-identifiers/${identId}/reject`, { method: 'PATCH' });
		await loadTable();
	}

	/* ── Merge ── */

	function openMergeSearch(personId: number) {
		// Close all other merge searches
		for (const id of Object.keys(mergeTimers)) {
			clearTimeout(mergeTimers[Number(id)]);
		}
		mergeSearches = { [personId]: { query: '', results: [], loading: false } };
	}

	function closeMergeSearch(personId: number) {
		const next = { ...mergeSearches };
		delete next[personId];
		mergeSearches = next;
		if (mergeTimers[personId]) clearTimeout(mergeTimers[personId]);
	}

	function handleMergeSearchInput(personId: number, query: string) {
		mergeSearches = { ...mergeSearches, [personId]: { ...mergeSearches[personId], query } };
		if (mergeTimers[personId]) clearTimeout(mergeTimers[personId]);
		if (query.trim().length < 2) {
			mergeSearches = { ...mergeSearches, [personId]: { ...mergeSearches[personId], results: [], loading: false } };
			return;
		}
		mergeTimers[personId] = setTimeout(async () => {
			mergeSearches = { ...mergeSearches, [personId]: { ...mergeSearches[personId], loading: true } };
			const results = await api<MergeSearch['results']>(`/api/persons/search?q=${encodeURIComponent(query.trim())}`);
			// Exclude self from results
			mergeSearches = { ...mergeSearches, [personId]: { ...mergeSearches[personId], results: results.filter(r => r.id !== personId), loading: false } };
		}, 300);
	}

	async function mergeInto(targetId: number, sourceId: number) {
		await fetch(`${base}/api/persons/${targetId}/merge`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ source_id: sourceId })
		});
		closeMergeSearch(targetId);
		loadStats();
		loadTable();
	}

	/* ── Helpers ── */

	function formatPeriod(p: Person): string {
		const parts: string[] = [];
		if (p.start_date) parts.push(p.start_date.substring(0, 10));
		if (p.start_date || p.end_date) {
			parts.push('\u2192');
			parts.push(p.end_date ? p.end_date.substring(0, 10) : '\u2026');
		}
		return parts.join(' ');
	}

	function isAlreadyLinked(candidate: Candidate): boolean {
		return candidate.person_id !== null;
	}

	function candidateIds(c: Candidate): string[] {
		const ids: string[] = [];
		if (c.orcid) ids.push('ORCID: ' + c.orcid);
		if (c.idhal) ids.push('idHAL: ' + c.idhal);
		if (c.openalex_id) ids.push('OA: ' + c.openalex_id);
		return ids;
	}

	/* ── Lifecycle ── */

	onMount(() => {
		readUrlFilters();
		loadStats();
		loadFacets();
		loadTable();
	});
</script>

<svelte:head>
	<title>Admin - Personnes - Bibliom&eacute;trie UCA</title>
</svelte:head>

<!-- Stats row -->
{#if stats}
	<div class="stats-row">
		<div class="stat-card">
			<div class="value">{stats.total_persons}</div>
			<div class="label">Personnes</div>
		</div>
		<div class="stat-card hl-success">
			<div class="value value-success">{stats.linked_persons}</div>
			<div class="label">Rattach&eacute;es</div>
		</div>
		<div class="stat-card hl-warning">
			<div class="value value-warning">{unlinkedCount}</div>
			<div class="label">Non rattach&eacute;es</div>
		</div>
		<div class="stat-card">
			<div class="value">{stats.linked_authors}</div>
			<div class="label">Auteurs li&eacute;s</div>
		</div>
		<div class="stat-card">
			<div class="value">{stats.departments}</div>
			<div class="label">D&eacute;partements</div>
		</div>
	</div>
{/if}

<!-- Toolbar -->
<div class="toolbar">
	<input
		type="text"
		placeholder="Rechercher (nom, email, d&eacute;partement)…"
		bind:value={search}
		oninput={handleSearch}
	/>
	<FacetDropdown label="Département" options={deptOptions} searchable bind:selected={selectedDepts} onchange={handleFilterChange} />
	<FacetDropdown label="Rôle" options={roleOptions} searchable bind:selected={selectedRoles} onchange={handleFilterChange} />
	<FacetDropdown label="Rattachement" options={linkedOptions} bind:selected={selectedLinked} onchange={handleFilterChange} />
	<FacetDropdown label="ORCID" options={orcidOptions} bind:selected={selectedOrcid} onchange={handleFilterChange} />
	<FacetDropdown label="idHAL" options={idhalOptions} bind:selected={selectedIdhal} onchange={handleFilterChange} />
	<FacetDropdown label="Base RH" options={rhOptions} bind:selected={selectedRh} onchange={handleFilterChange} />
	<span class="count">{totalCount} personnes</span>
</div>

<!-- Table -->
{#if persons.length === 0 && !loading}
	<div class="empty">Aucune personne trouv&eacute;e.</div>
{:else}
	<table class="data-table">
		<thead>
			<tr>
				<th></th>
				<th>Nom</th>
				<th>Pr&eacute;nom</th>
				<th>D&eacute;partement</th>
				<th>R&ocirc;le</th>
				<th>P&eacute;riode</th>
				<th>Auteur(s) li&eacute;s</th>
			</tr>
		</thead>
		<tbody>
			{#each persons as p (p.id)}
				{@const linked = p.linked_authors ?? []}
				{@const expanded = p.id in expandedPersons}
				{@const candidatesData = expandedPersons[p.id]}
				<!-- Main row -->
				<tr>
					<td>
						<button
							class="btn-expand"
							title="Chercher des auteurs candidats"
							onclick={() => toggleCandidates(p.id)}
						>
							{expanded ? '\u25BC' : '\u25B6'}
						</button>
					</td>
					<td>
						<strong>{p.last_name}</strong>
						{#if p.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
					</td>
					<td>{p.first_name}</td>
					<td>{p.department_name ?? ''}</td>
					<td>
						{#if p.role_title}
							<span class="tag tag-role">{p.role_title}</span>
						{/if}
					</td>
					<td class="period-cell">{formatPeriod(p)}</td>
					<td>
						<!-- Identifiers -->
						{#if p.identifiers?.length}
							<div class="identifiers-row">
								{#each p.identifiers as ident}
									<span class="identifier-tag" class:rejected={ident.rejected}>
										<span class="tag tag-id" title="{ident.id_type} ({ident.source}){ident.rejected ? ' — rejeté' : ''}">
											{ident.id_type === 'orcid' ? 'ORCID' : ident.id_type === 'idhal' ? 'idHAL' : ident.id_type}: {ident.id_value}
										</span>
										<button
											class="btn-reject"
											title={ident.rejected ? 'Restaurer' : 'Rejeter cet identifiant'}
											onclick={() => toggleRejectIdentifier(ident.id)}
										>{ident.rejected ? '↩' : '⊘'}</button>
										<button
											class="btn-unlink"
											title="Supprimer définitivement"
											onclick={() => removeIdentifier(p.id, ident.id_type, ident.id_value)}
										>&times;</button>
									</span>
								{/each}
							</div>
						{/if}
						<!-- Linked authors -->
						{#if linked.length}
							<button class="btn-toggle-authors" onclick={() => { expandedAuthors = { ...expandedAuthors, [p.id]: !expandedAuthors[p.id] }; }}>
								{linked.length} auteur{linked.length > 1 ? 's' : ''} lié{linked.length > 1 ? 's' : ''}
								<span class="toggle-arrow">{expandedAuthors[p.id] ? '\u25BE' : '\u25B8'}</span>
							</button>
							{#if expandedAuthors[p.id]}
								<div class="linked-authors-list">
									{#each linked as a}
										<span class="linked-author">
											<span class="tag tag-source">{a.source}</span>
											<span class="tag tag-linked">{a.full_name}</span>
											{#if a.orcid}
												<span class="tag tag-id" title="ORCID">{a.orcid}</span>
											{/if}
											{#if a.idhal}
												<span class="tag tag-id" title="idHAL">{a.idhal}</span>
											{/if}
											<button
												class="btn-unlink"
												title="Détacher"
												onclick={() => unlinkAuthor(p.id, a.source, a.id)}
											>&times;</button>
										</span>
									{/each}
								</div>
							{/if}
						{:else if !p.identifiers?.length}
							<span class="tag tag-unlinked">non rattachée</span>
						{/if}
						<!-- Merge search -->
						{#if p.id in mergeSearches}
							{@const ms = mergeSearches[p.id]}
							<div class="merge-search">
								<div class="merge-input-row">
									<input
										type="text"
										placeholder="Nom de la personne à absorber…"
										value={ms.query}
										oninput={(e) => handleMergeSearchInput(p.id, (e.target as HTMLInputElement).value)}
									/>
									<button class="btn" onclick={() => closeMergeSearch(p.id)}>&times;</button>
								</div>
								{#if ms.loading}
									<div class="merge-results"><span class="loading-text">Recherche…</span></div>
								{:else if ms.results.length}
									<div class="merge-results">
										{#each ms.results as r}
											<button class="merge-result" onclick={() => mergeInto(p.id, r.id)}>
												<strong>{r.last_name}</strong> {r.first_name}
												{#if r.department_name}<span class="merge-dept">{r.department_name}</span>{/if}
												{#if r.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
											</button>
										{/each}
									</div>
								{:else if ms.query.trim().length >= 2}
									<div class="merge-results"><span class="loading-text">Aucun résultat</span></div>
								{/if}
							</div>
						{:else}
							<button class="btn btn-merge" onclick={() => openMergeSearch(p.id)}>Fusionner avec…</button>
						{/if}
						<!-- Add identifier button / form -->
						{#if p.id in idForms}
							{@const form = idForms[p.id]}
							<div class="id-form">
								<select
									value={form.id_type}
									onchange={(e) => {
										idForms = { ...idForms, [p.id]: { ...form, id_type: (e.target as HTMLSelectElement).value, error: '' } };
									}}
								>
									<option value="orcid">ORCID</option>
									<option value="idhal">idHAL</option>
								</select>
								<input
									type="text"
									placeholder={form.id_type === 'orcid' ? '0000-0000-0000-0000' : 'identifiant-hal'}
									value={form.id_value}
									oninput={(e) => {
										idForms = { ...idForms, [p.id]: { ...form, id_value: (e.target as HTMLInputElement).value, error: '' } };
									}}
									onkeydown={(e) => { if (e.key === 'Enter') addIdentifier(p.id); }}
								/>
								<button class="btn btn-link" onclick={() => addIdentifier(p.id)}>OK</button>
								<button class="btn" onclick={() => toggleIdForm(p.id)}>&times;</button>
								{#if form.error}
									<span class="id-error">{form.error}</span>
								{/if}
							</div>
						{:else}
							<button
								class="btn btn-add-id"
								title="Ajouter un identifiant"
								onclick={() => toggleIdForm(p.id)}
							>+ Identifiant</button>
						{/if}
					</td>
				</tr>
				<!-- Candidates row -->
				{#if expanded}
					<tr class="candidates-row">
						<td colspan="7">
							{#if candidatesData === 'loading'}
								<div class="loading-text">Recherche d'auteurs candidats…</div>
							{:else if candidatesData && candidatesData.length === 0}
								<div class="candidates-panel">
									<h4>Auteurs candidats</h4>
									<div class="loading-text">Aucun auteur trouv&eacute; avec un nom similaire.</div>
								</div>
							{:else if candidatesData}
								<div class="candidates-panel">
									<h4>Auteurs candidats ({candidatesData.length})</h4>
									{#each candidatesData as c}
										{@const dKey = detailKey(c.source, c.id)}
										{@const detailData = expandedDetails[dKey]}
										{@const detailOpen = dKey in expandedDetails}
										<div class="candidate-card">
											<div class="candidate-header">
												<div class="info">
													<span class="tag tag-source">{c.source}</span>
													<span class="name">{c.full_name}</span>
													{#if candidateIds(c).length}
														<span class="meta">{candidateIds(c).join(' \u00b7 ')}</span>
													{/if}
													<div class="meta">
														{c.pub_count} publis
														{#if c.uca_pub_count > 0}
															dont <strong>{c.uca_pub_count} UCA</strong>
														{/if}
													</div>
												</div>
												<button
													class="btn-detail"
													onclick={() => toggleAuthorDetail(c.source, c.id)}
												>
													signatures &amp; publis {detailOpen ? '\u25BE' : '\u25B8'}
												</button>
												{#if isAlreadyLinked(c)}
													<span class="tag tag-linked tag-small">d&eacute;j&agrave; li&eacute; (personne #{c.person_id})</span>
												{:else}
													<button
														class="btn btn-link"
														onclick={() => linkAuthor(p.id, c.source, c.id)}
													>Rattacher</button>
												{/if}
											</div>
											<!-- Author detail sub-panel -->
											{#if detailOpen}
												<div class="author-detail">
													{#if detailData === 'loading'}
														<span class="loading-text">Chargement…</span>
													{:else if detailData}
														{#if detailData.publications.length}
															<h5>Publications r&eacute;centes ({detailData.publications.length})</h5>
															<ul class="pub-list">
																{#each detailData.publications as pub}
																	<li>
																		<span class="pub-year">{pub.pub_year ?? '?'}</span>
																		{#if pub.is_uca}
																			<span class="pub-uca">UCA</span>
																		{/if}
																		<span class="pub-title">{@html sanitizeTitle(pub.title)}</span>
																		{#if pub.doi}
																			<a
																				href="https://doi.org/{pub.doi}"
																				target="_blank"
																				rel="noopener noreferrer"
																				class="pub-doi"
																			>DOI</a>
																		{/if}
																	</li>
																{/each}
															</ul>
														{/if}
													{/if}
												</div>
											{/if}
										</div>
									{/each}
								</div>
							{/if}
						</td>
					</tr>
				{/if}
			{/each}
		</tbody>
	</table>

	<Pagination page={currentPage} pages={totalPages} onchange={handlePageChange} />
{/if}

<style>
	/* ── Local CSS variables ── */
	:root {
		--success: #2a7d4f;
		--success-light: #e6f4ec;
		--danger: #c0392b;
		--danger-light: #fbeaea;
		--warning: #d4a017;
		--warning-light: #fef8e8;
		--accent-light: #e8f0f8;
		--text-muted: #777;
	}

	/* ── Stats row ── */
	.stats-row {
		display: flex;
		gap: 10px;
		margin-bottom: 20px;
		flex-wrap: wrap;
	}
	.stat-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 12px 18px;
		text-align: center;
		flex: 1;
		min-width: 120px;
	}
	.stat-card .value {
		font-size: 22px;
		font-weight: 700;
		line-height: 1.2;
	}
	.stat-card .label {
		font-size: 11px;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}
	.stat-card.hl-success {
		border-left: 3px solid var(--success);
	}
	.stat-card.hl-warning {
		border-left: 3px solid var(--warning);
	}
	.value-success {
		color: var(--success);
	}
	.value-warning {
		color: var(--warning);
	}

	/* ── Toolbar ── */
	.toolbar {
		display: flex;
		gap: 8px;
		margin-bottom: 16px;
		align-items: center;
		flex-wrap: wrap;
	}
	.toolbar input {
		padding: 6px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 13px;
		background: white;
		font-family: inherit;
		width: 250px;
	}
	.count {
		margin-left: auto;
		color: var(--text-muted);
		font-size: 12px;
	}

	/* ── Table ── */
	.data-table {
		width: 100%;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: visible;
	}
	.data-table th {
		text-align: left;
		padding: 8px 10px;
		font-size: 11px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		color: var(--text-muted);
		border-bottom: 2px solid var(--border);
		background: #fafaf8;
	}
	.data-table td {
		padding: 7px 10px;
		font-size: 13px;
		border-bottom: 1px solid #f0efec;
		vertical-align: top;
	}
	.data-table tr:hover td {
		background: #fafaf8;
	}
	.period-cell {
		font-size: 12px;
		color: var(--text-muted);
	}

	/* ── Tags ── */
	.tag {
		display: inline-block;
		font-size: 11px;
		padding: 1px 7px;
		border-radius: 10px;
		font-weight: 500;
		margin: 1px 2px;
	}
	.tag-linked {
		background: var(--success-light);
		color: var(--success);
	}
	.tag-unlinked {
		background: var(--warning-light);
		color: #8a6d10;
	}
	.tag-role {
		background: #eee;
		color: #555;
	}
	.tag-id {
		background: var(--accent-light);
		color: var(--accent);
		font-family: 'SF Mono', SFMono-Regular, Consolas, 'Liberation Mono', Menlo, monospace;
		font-size: 10px;
	}
	.tag-source {
		background: #eee;
		color: #555;
		font-size: 10px;
	}
	.tag-small {
		font-size: 10px;
	}

	/* ── Linked authors toggle ── */
	.btn-toggle-authors {
		background: none;
		border: none;
		cursor: pointer;
		font-size: 11px;
		color: var(--accent);
		padding: 2px 4px;
		font-family: inherit;
		font-weight: 500;
	}
	.btn-toggle-authors:hover { text-decoration: underline; }
	.toggle-arrow { font-size: 10px; margin-left: 2px; }
	.linked-authors-list {
		margin-top: 4px;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.linked-author {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		margin: 1px 0;
	}

	/* ── Merge search ── */
	.btn-merge {
		padding: 2px 8px;
		border: 1px dashed var(--border);
		border-radius: 4px;
		background: none;
		font-size: 11px;
		cursor: pointer;
		color: var(--text-muted);
		margin-top: 4px;
		font-family: inherit;
	}
	.btn-merge:hover {
		background: var(--warning-light);
		border-style: solid;
		color: var(--warning);
		border-color: var(--warning);
	}
	.merge-search {
		margin-top: 4px;
		position: relative;
	}
	.merge-input-row {
		display: flex;
		gap: 4px;
		align-items: center;
	}
	.merge-input-row input {
		padding: 3px 6px;
		border: 1px solid var(--warning);
		border-radius: 3px;
		font-size: 12px;
		font-family: inherit;
		width: 220px;
	}
	.merge-results {
		position: absolute;
		top: 100%;
		left: 0;
		z-index: 10;
		background: white;
		border: 1px solid var(--border);
		border-radius: 4px;
		box-shadow: 0 4px 12px rgba(0,0,0,0.1);
		min-width: 280px;
		max-height: 200px;
		overflow-y: auto;
		padding: 4px 0;
	}
	.merge-result {
		display: block;
		width: 100%;
		text-align: left;
		padding: 6px 10px;
		border: none;
		background: none;
		cursor: pointer;
		font-size: 12px;
		font-family: inherit;
	}
	.merge-result:hover { background: var(--warning-light); }
	.merge-dept {
		font-size: 11px;
		color: var(--text-muted);
		margin-left: 6px;
	}

	/* ── Buttons ── */
	.btn-expand {
		background: none;
		border: none;
		cursor: pointer;
		font-size: 14px;
		padding: 2px 6px;
		color: var(--accent);
		font-family: inherit;
	}
	.btn {
		padding: 4px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: white;
		font-size: 12px;
		cursor: pointer;
		font-family: inherit;
	}
	.btn:hover {
		background: var(--accent-light);
	}
	.btn-link {
		border-color: var(--success);
		color: var(--success);
	}
	.btn-link:hover {
		background: var(--success);
		color: white;
	}
	.btn-unlink {
		border: 1px solid var(--danger);
		color: var(--danger);
		font-size: 10px;
		background: none;
		border-radius: 4px;
		cursor: pointer;
		padding: 1px 5px;
		font-family: inherit;
	}
	.btn-unlink:hover {
		background: var(--danger);
		color: white;
	}
	.btn-detail {
		background: none;
		border: none;
		cursor: pointer;
		font-size: 11px;
		color: var(--accent);
		padding: 2px 4px;
		text-decoration: underline;
		font-family: inherit;
	}

	/* ── Candidates panel ── */
	.candidates-row {
		background: #f5f7fa;
	}
	.candidates-row td {
		padding: 10px 20px;
	}
	.candidates-row:hover td {
		background: #f5f7fa;
	}
	.candidates-panel {
		font-size: 12px;
	}
	.candidates-panel h4 {
		margin: 0 0 8px;
		font-size: 13px;
		color: var(--accent);
	}
	.candidate-card {
		display: flex;
		flex-direction: column;
		align-items: stretch;
		padding: 6px 10px;
		margin: 4px 0;
		background: white;
		border: 1px solid var(--border);
		border-radius: 4px;
	}
	.candidate-header {
		display: flex;
		align-items: center;
		gap: 10px;
	}
	.candidate-card .info {
		flex: 1;
	}
	.candidate-card .name {
		font-weight: 600;
	}
	.candidate-card .meta {
		color: var(--text-muted);
		font-size: 11px;
	}

	/* ── Author detail sub-panel ── */
	.author-detail {
		margin-top: 6px;
		padding: 8px 10px;
		background: #f8f9fb;
		border: 1px solid #e8eaed;
		border-radius: 4px;
		font-size: 12px;
	}
	.author-detail h5 {
		margin: 0 0 4px;
		font-size: 11px;
		color: var(--accent);
		text-transform: uppercase;
		letter-spacing: 0.3px;
	}

	/* ── Publications ── */
	.pub-list {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.pub-list li {
		padding: 3px 0;
		border-bottom: 1px solid #f0efec;
	}
	.pub-list li:last-child {
		border-bottom: none;
	}
	.pub-year {
		font-size: 10px;
		color: var(--text-muted);
		font-weight: 600;
		margin-right: 4px;
	}
	.pub-title {
		color: #333;
	}
	.pub-uca {
		color: var(--success);
		font-size: 10px;
		font-weight: 600;
	}
	.pub-doi {
		font-size: 10px;
		color: var(--accent);
		text-decoration: none;
		margin-left: 4px;
	}
	.pub-doi:hover {
		text-decoration: underline;
	}

	/* ── Identifiers ── */
	.identifiers-row {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin-bottom: 4px;
	}
	.identifier-tag {
		display: inline-flex;
		align-items: center;
		gap: 2px;
	}
	.identifier-tag.rejected {
		opacity: 0.45;
		text-decoration: line-through;
	}
	.btn-reject {
		background: none;
		border: none;
		cursor: pointer;
		font-size: 12px;
		padding: 0 2px;
		color: var(--text-muted);
		font-family: inherit;
	}
	.btn-reject:hover { color: #c0392b; }
	.btn-add-id {
		padding: 2px 8px;
		border: 1px dashed var(--border);
		border-radius: 4px;
		background: none;
		font-size: 11px;
		cursor: pointer;
		color: var(--accent);
		margin-top: 4px;
		font-family: inherit;
	}
	.btn-add-id:hover {
		background: var(--accent-light);
		border-style: solid;
	}
	.id-form {
		display: flex;
		align-items: center;
		gap: 4px;
		margin-top: 4px;
		flex-wrap: wrap;
	}
	.id-form select,
	.id-form input {
		padding: 3px 6px;
		border: 1px solid var(--border);
		border-radius: 3px;
		font-size: 12px;
		font-family: inherit;
	}
	.id-form select {
		width: 80px;
	}
	.id-form input {
		width: 180px;
	}
	.id-error {
		font-size: 11px;
		color: var(--danger);
	}

	/* ── RH checkmark ── */
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

	/* ── Misc ── */
	.loading-text {
		color: var(--text-muted);
	}
	.empty {
		text-align: center;
		padding: 40px;
		color: var(--text-muted);
	}
</style>
