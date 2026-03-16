<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { titleCase, formatDate, sanitizeTitle } from '$lib/utils';
	import { typeLabels, docTypeLabelsMap, oaLabelsMap } from '$lib/labels';
	import Pagination from '$lib/components/Pagination.svelte';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import SourceFilterToggle from '$lib/components/SourceFilterToggle.svelte';
	import type { FacetOption } from '$lib/components/FacetDropdown.svelte';

	const personId = $derived($page.params.id);
	let canGoBack = $state(false);
	const validTabs = ['publications', 'identities', 'addresses'] as const;
	type Tab = (typeof validTabs)[number];

	// --- Types ---
	interface Person {
		id: number;
		last_name: string;
		first_name: string;
		role_title: string | null;
		department_name: string | null;
		start_date: string | null;
		end_date: string | null;
	}
	interface Identifier {
		id_type: string;
		id_value: string;
		source: string;
		status: 'pending' | 'confirmed' | 'rejected';
	}
	interface Author {
		id: number;
		source: string;
		full_name: string;
		orcid: string | null;
		idhal: string | null;
		hal_person_id: number | null;
		openalex_id: string | null;
		uca_pub_count: number;
	}
	interface ProfileResponse {
		person: Person;
		identifiers: Identifier[];
		authors: Author[];
	}
	interface Address {
		id: number;
		raw_text: string;
		structures: { id: number; acronym: string | null; name: string }[] | null;
	}
	interface Publication {
		id: number;
		title: string;
		pub_year: number | null;
		doi: string | null;
		doc_type: string | null;
		oa_status: string | null;
		journal: string | null;
		hal_id: string | null;
		openalex_id: string | null;
		wos_id: string | null;
		labs: string | null;
		is_corresponding: boolean | null;
		authorship_id: number | null;
	}
	interface PubResponse {
		total: number;
		page: number;
		pages: number;
		publications: Publication[];
	}

	// --- State ---
	let profile: Person | null = $state(null);
	let identifiers: Identifier[] = $state([]);
	let authors: Author[] = $state([]);
	let error = $state(false);
	let isAdmin = $state(false);

	const activeTab: Tab = $derived(
		(() => {
			const t = $page.url.searchParams.get('tab') as Tab | null;
			return t && validTabs.includes(t) ? t : 'publications';
		})()
	);

	// Publications tab
	let publications: Publication[] = $state([]);
	let pubTotal = $state(0);
	let pubPage = $state(1);
	let pubPages = $state(1);
	const pubPerPage = 50;

	// Facet state
	let selectedYears: string[] = $state([]);
	let selectedDocTypes: string[] = $state([]);
	let selectedOa: string[] = $state([]);
	let selectedCorr: string[] = $state([]);
	let sourceStates: Record<string, string> = $state({});
	let yearOptions: FacetOption[] = $state([]);
	let docTypeOptions: FacetOption[] = $state([]);
	let oaOptions: FacetOption[] = $state([]);
	let corrOptions: FacetOption[] = $state([]);

	// Addresses tab
	let addresses: Address[] = $state([]);
	let addrTotal = $state(0);
	let addrPage = $state(1);
	let addrPages = $state(1);
	let addrLoaded = $state(false);

	const displayName = $derived(
		profile
			? `${titleCase(profile.first_name)} ${titleCase(profile.last_name)}`
			: ''
	);

	const allOrcids = $derived(() => {
		const map = new Map<string, boolean>();
		identifiers.filter((i) => i.id_type === 'orcid' && i.status !== 'rejected').forEach((i) => {
			map.set(i.id_value, map.get(i.id_value) || i.status === 'confirmed');
		});
		return Array.from(map, ([value, confirmed]) => ({ value, confirmed }));
	});

	const allIdhals = $derived(() => {
		const map = new Map<string, boolean>();
		authors.forEach((a) => { if (a.idhal && !map.has(a.idhal)) map.set(a.idhal, false); });
		identifiers.filter((i) => i.id_type === 'idhal' && i.status !== 'rejected').forEach((i) => {
			map.set(i.id_value, map.get(i.id_value) || i.status === 'confirmed');
		});
		return Array.from(map, ([value, confirmed]) => ({ value, confirmed }));
	});

	function buildFilterParams(): URLSearchParams {
		const params = new URLSearchParams();
		params.set('person_id', personId ?? '');
		if (selectedYears.length) params.set('year', selectedYears.join(','));
		if (selectedDocTypes.length) params.set('doc_type', selectedDocTypes.join(','));
		if (selectedOa.length) params.set('oa_status', selectedOa.join(','));
		if (selectedCorr.length) params.set('is_corresponding', selectedCorr.join(','));
		const sf = Object.entries(sourceStates).filter(([, v]) => v === 'yes' || v === 'no').map(([k, v]) => `${k}_${v}`).join(',');
		if (sf) params.set('source_filter', sf);
		return params;
	}

	async function loadFacets() {
		const params = buildFilterParams();
		const data = await api<{
			years: { value: number; count: number }[];
			doc_types: { value: string; count: number }[];
			oa_statuses: { value: string; count: number }[];
			corresponding: { value: string; count: number }[];
		}>('/api/publications/facets?' + params);
		yearOptions = data.years.map((y) => ({
			value: String(y.value), text: String(y.value), count: y.count
		}));
		docTypeOptions = data.doc_types.map((d) => ({
			value: d.value, text: docTypeLabelsMap[d.value] || d.value, count: d.count
		}));
		oaOptions = data.oa_statuses.map((o) => ({
			value: o.value, text: oaLabelsMap[o.value] || o.value, count: o.count
		}));
		if (data.corresponding?.length) {
			corrOptions = data.corresponding.map((c) => ({
				value: c.value, text: c.value === 'yes' ? 'Oui' : 'Non', count: c.count
			}));
		}
	}

	async function loadPublications() {
		const params = buildFilterParams();
		params.set('page', String(pubPage));
		params.set('per_page', String(pubPerPage));
		params.set('sort', 'year_desc');
		const data = await api<PubResponse>('/api/publications?' + params);
		publications = data.publications;
		pubTotal = data.total;
		pubPages = data.pages;
		pubPage = data.page;
	}

	function onFilterChange(newStates?: Record<string, string>) {
		if (newStates !== undefined) sourceStates = newStates;
		pubPage = 1;
		loadPublications();
		loadFacets();
	}

	async function loadAddresses() {
		const params = new URLSearchParams({
			page: String(addrPage),
			per_page: '50'
		});
		const data = await api<{
			total: number; page: number; pages: number; addresses: Address[];
		}>(`/api/persons/${personId}/addresses?${params}`);
		addresses = data.addresses;
		addrTotal = data.total;
		addrPages = data.pages;
		addrPage = data.page;
		addrLoaded = true;
	}

	function exportCsvUrl(): string {
		const params = buildFilterParams();
		params.set('sort', 'year_desc');
		return `${base}/api/publications/export.csv?${params}`;
	}

	async function excludeAuthorship(authorshipId: number, pubId: number) {
		if (!confirm('Exclure ce lien auteur–publication ? Il ne sera pas recréé automatiquement.')) return;
		await fetch(base + `/api/authorships/${authorshipId}/exclude`, { method: 'PATCH' });
		publications = publications.filter(p => p.id !== pubId);
		pubTotal--;
	}

	function switchTab(tab: Tab) {
		const url = new URL($page.url);
		if (tab === 'publications') {
			url.searchParams.delete('tab');
		} else {
			url.searchParams.set('tab', tab);
		}
		goto(url.toString(), { replaceState: true, noScroll: true });
		if (tab === 'publications' && publications.length === 0 && pubTotal === 0) { loadFacets(); loadPublications(); }
		if (tab === 'addresses' && !addrLoaded) loadAddresses();
	}

	onMount(async () => {
		canGoBack = (window.navigation?.canGoBack ?? document.referrer.startsWith(window.location.origin));
		// Check admin status (non-blocking)
		fetch(base + '/api/auth/check').then(r => r.json()).then(d => { isAdmin = !!d.authenticated; }).catch(() => {});
		try {
			const profileData = await api<ProfileResponse>(`/api/persons/${personId}/profile`);
			profile = profileData.person;
			identifiers = profileData.identifiers;
			authors = profileData.authors;
		} catch {
			error = true;
			return;
		}
		// Load data for active tab
		if (activeTab === 'addresses') loadAddresses();
		else if (activeTab === 'publications') { loadFacets(); loadPublications(); }
	});
</script>

<svelte:head>
	<title>{displayName || 'Personne'} — Bibliométrie UCA</title>
</svelte:head>

{#if canGoBack}
<!-- svelte-ignore a11y_invalid_attribute -->
<a href="#" class="back-link" onclick={(e) => { e.preventDefault(); history.back(); }}>&larr; Retour</a>
{/if}

{#if error}
	<div class="profile-header">
		<div class="no-results">Personne introuvable</div>
	</div>
{:else if !profile}
	<div class="profile-header">
		<div class="loading">Chargement...</div>
	</div>
{:else}
	<!-- Profile header -->
	<div class="profile-header">
		<h1 class="profile-name">
			{titleCase(profile.first_name)}
			<span class="profile-last">{titleCase(profile.last_name)}</span>
		</h1>
		<div class="profile-meta">
			{#if profile.role_title}
				<span class="role-badge">{profile.role_title}</span>
			{/if}
			{#if profile.department_name}
				<span>{profile.department_name}</span>
			{/if}
			{#if profile.start_date || profile.end_date}
				<span>
					Du {profile.start_date ? formatDate(profile.start_date) : '?'}
					— {profile.end_date ? formatDate(profile.end_date) : 'en poste'}
				</span>
			{/if}
			{#each allOrcids() as oid}
				<span class="id-item" class:id-confirmed={oid.confirmed}>
					<span class="id-label">ORCID</span>
					<a href="https://orcid.org/{oid.value}" target="_blank" rel="noopener" class="id-badge">{oid.value}</a>
					{#if oid.confirmed}<span class="confirmed-check" title="Vérifié manuellement">&#10003;</span>{/if}
				</span>
			{/each}
			{#each allIdhals() as idh}
				<span class="id-item" class:id-confirmed={idh.confirmed}>
					<span class="id-label">idHAL</span>
					<a href="https://hal.science/search/index/?q=%2A&authIdHal_s={idh.value}" target="_blank" rel="noopener" class="id-badge">{idh.value}</a>
					{#if idh.confirmed}<span class="confirmed-check" title="Vérifié manuellement">&#10003;</span>{/if}
				</span>
			{/each}
		</div>
	</div>

	<!-- Tabs -->
	<div class="tabs">
		<button class="tab" class:active={activeTab === 'publications'} onclick={() => switchTab('publications')}>
			Publications
			{#if pubTotal}<span class="tab-count">{pubTotal}</span>{/if}
		</button>
		<button class="tab" class:active={activeTab === 'identities'} onclick={() => switchTab('identities')}>
			Identités
			{#if authors.length}<span class="tab-count">{authors.length}</span>{/if}
		</button>
		<button class="tab" class:active={activeTab === 'addresses'} onclick={() => switchTab('addresses')}>
			Adresses
			{#if addrLoaded}<span class="tab-count">{addrTotal}</span>{/if}
		</button>
	</div>

	<!-- Tab: Publications -->
	{#if activeTab === 'publications'}
		<div class="tab-content">
			<div class="toolbar">
				<FacetDropdown label="Années" options={yearOptions} bind:selected={selectedYears} onchange={onFilterChange} />
				<FacetDropdown label="Types" options={docTypeOptions} bind:selected={selectedDocTypes} onchange={onFilterChange} />
				<FacetDropdown label="Voies OA" options={oaOptions} bind:selected={selectedOa} onchange={onFilterChange} />
				{#if corrOptions.length}
					<FacetDropdown label="Corresp." options={corrOptions} bind:selected={selectedCorr} onchange={onFilterChange} />
				{/if}
				<SourceFilterToggle bind:states={sourceStates} onchange={onFilterChange} />
				<span class="count">{pubTotal} publication{pubTotal > 1 ? 's' : ''}</span>
				<a href={exportCsvUrl()} class="export-btn" download>Export CSV</a>
			</div>
			<table class="pub-table">
				<thead>
					<tr>
						{#if isAdmin}<th style="width:28px"></th>{/if}
						<th>Titre</th>
						<th>Revue</th>
						<th style="width:80px">Type</th>
						<th style="width:40px">An.</th>
						<th style="width:80px">Labo(s)</th>
						<th style="width:30px" title="Auteur correspondant">&#9993;</th>
						<th style="width:50px">OA</th>
						<th style="width:80px">Liens</th>
					</tr>
				</thead>
				<tbody>
					{#if publications.length === 0}
						<tr><td colspan={isAdmin ? 9 : 8} class="no-results">Aucune publication</td></tr>
					{:else}
						{#each publications as p (p.id)}
							<tr>
								{#if isAdmin}
									<td class="exclude-cell">
										{#if p.authorship_id}
											<button class="exclude-btn" title="Exclure ce lien auteur–publication"
												onclick={() => excludeAuthorship(p.authorship_id!, p.id)}>✕</button>
										{/if}
									</td>
								{/if}
								<td><a href="{base}/publications/{p.id}" class="pub-title">{@html sanitizeTitle(p.title)}</a></td>
								<td class="journal-cell">{p.journal || ''}</td>
								<td>
									<span class="type-label">{typeLabels[p.doc_type || ''] || p.doc_type || ''}</span>
								</td>
								<td>{p.pub_year || ''}</td>
								<td>
									{#each (p.labs || '').split(', ').filter(Boolean) as lab}
										<span class="lab-tag">{lab}</span>
									{/each}
								</td>
								<td class="corr-cell">
									{#if p.is_corresponding}
										<span title="Auteur correspondant">&#10003;</span>
									{/if}
								</td>
								<td>
									{#if p.oa_status && p.oa_status !== 'unknown'}
										<span class="oa-tag oa-{p.oa_status}">{p.oa_status}</span>
									{/if}
								</td>
								<td class="links-cell">
									{#if p.hal_id}
										<a href="https://hal.science/{p.hal_id}" target="_blank" rel="noopener" class="source-tag source-hal" title="HAL: {p.hal_id}">
											<img src="https://hal.science/favicon.ico" alt="HAL" />
										</a>
									{:else}
										<span class="source-tag source-placeholder"></span>
									{/if}
									{#if p.openalex_id}
										<a href="https://openalex.org/{p.openalex_id}" target="_blank" rel="noopener" class="source-tag source-oa" title="OpenAlex: {p.openalex_id}">
											<img src="https://raw.githubusercontent.com/ourresearch/openalex-gui/refs/heads/master/public/favicon.png" alt="OA" />
										</a>
									{:else}
										<span class="source-tag source-placeholder"></span>
									{/if}
									{#if p.wos_id}
										<a href="https://www.webofscience.com/wos/woscc/full-record/{p.wos_id}" target="_blank" rel="noopener" class="source-tag source-wos" title="WoS: {p.wos_id}">
											<img src="https://www.webofscience.com/favicon.ico" alt="WoS" />
										</a>
									{:else}
										<span class="source-tag source-placeholder"></span>
									{/if}
									{#if p.doi}
										<a href="https://doi.org/{p.doi}" target="_blank" rel="noopener" class="source-tag source-doi" title={p.doi}>
											<svg viewBox="0 0 24 24" fill="none" stroke="#555" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
										</a>
									{:else}
										<span class="source-tag source-placeholder"></span>
									{/if}
								</td>
							</tr>
						{/each}
					{/if}
				</tbody>
			</table>
			<Pagination page={pubPage} pages={pubPages} onchange={(p) => { pubPage = p; loadPublications(); }} />
		</div>
	{/if}

	<!-- Tab: Identités -->
	{#if activeTab === 'identities'}
		<div class="tab-content">
			{#if authors.length > 0}
				<table>
					<thead>
						<tr>
							<th>Source</th>
							<th>Nom complet</th>
							<th>ORCID / idHAL</th>
							<th>Identifiant source</th>
							<th>Publis UCA</th>
						</tr>
					</thead>
					<tbody>
						{#each authors as a (a.id + '-' + a.source)}
							<tr>
								<td>
									{#if a.source === 'hal'}
										<span class="source-tag-label source-hal-label">HAL</span>
									{:else}
										<span class="source-tag-label source-oa-label">OpenAlex</span>
									{/if}
								</td>
								<td>{a.full_name}</td>
								<td>
									{#if a.orcid}
										<a href="https://orcid.org/{a.orcid}" target="_blank" rel="noopener" class="id-badge">{a.orcid}</a>
									{/if}
									{#if a.idhal}
										<a href="https://hal.science/search/index/?q=%2A&authIdHal_s={a.idhal}" target="_blank" rel="noopener" class="id-badge">{a.idhal}</a>
									{/if}
								</td>
								<td>
									{#if a.source === 'hal' && a.hal_person_id}
										<span class="id-badge">{a.hal_person_id}</span>
									{:else if a.source === 'openalex' && a.openalex_id}
										<a href="https://openalex.org/{a.openalex_id}" target="_blank" rel="noopener" class="id-badge">{a.openalex_id}</a>
									{/if}
								</td>
								<td>{a.uca_pub_count}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{:else}
				<div class="no-results">Aucune identité liée</div>
			{/if}
		</div>
	{/if}

	<!-- Tab: Adresses -->
	{#if activeTab === 'addresses'}
		<div class="tab-content">
			{#if !addrLoaded}
				<div class="loading">Chargement...</div>
			{:else if addresses.length === 0}
				<div class="no-results">Aucune adresse</div>
			{:else}
				<table>
					<thead>
						<tr>
							<th>Adresse</th>
							<th style="width:160px">Structures</th>
						</tr>
					</thead>
					<tbody>
						{#each addresses as a (a.id)}
							<tr>
								<td class="addr-cell">{a.raw_text}</td>
								<td>
									{#if a.structures?.length}
										{#each a.structures as s (s.id)}
											<span class="struct-tag">{s.acronym || s.name}</span>
										{/each}
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
				<Pagination page={addrPage} pages={addrPages} onchange={(p) => { addrPage = p; loadAddresses(); }} />
			{/if}
		</div>
	{/if}
{/if}

<style>
	.back-link {
		display: inline-block;
		margin-bottom: 12px;
		font-size: 0.95rem;
		color: var(--accent);
		text-decoration: none;
	}
	.back-link:hover { text-decoration: underline; }

	.profile-header {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 20px 24px;
		margin-bottom: 0;
	}
	.profile-name {
		font-size: 1.45rem;
		font-weight: 600;
		margin: 0 0 6px;
	}
	.profile-last { font-weight: 600; }
	.profile-meta {
		display: flex;
		gap: 16px;
		align-items: center;
		flex-wrap: wrap;
		font-size: 0.95rem;
		color: var(--muted);
	}
	.role-badge {
		display: inline-block;
		padding: 2px 8px;
		background: #f0efec;
		border-radius: 3px;
		font-size: 0.85rem;
		color: var(--muted);
	}
	.id-item { display: flex; align-items: center; gap: 6px; font-size: 0.95rem; }
	.id-label { font-weight: 500; color: var(--muted); font-size: 0.85rem; }
	.id-badge {
		display: inline-block;
		padding: 2px 7px;
		background: #e8f0f8;
		border-radius: 3px;
		font-size: 0.8rem;
		color: var(--accent);
		text-decoration: none;
		white-space: nowrap;
	}
	.id-badge:hover { background: #d4e4f3; text-decoration: none; }
	.id-confirmed .id-label { background: #e6f4ec; color: #2a7d4f; }
	.id-confirmed .id-badge { background: #e6f4ec; color: #2a7d4f; }
	.id-confirmed .id-badge:hover { background: #d0eadb; }
	.confirmed-check {
		color: #2a7d4f;
		font-size: 0.8rem;
		font-weight: 700;
		margin-left: 2px;
	}

	/* Tabs */
	.tabs {
		display: flex;
		gap: 0;
		background: var(--card);
		border-left: 1px solid var(--border);
		border-right: 1px solid var(--border);
		border-bottom: 1px solid var(--border);
		border-radius: 0 0 6px 6px;
		margin-bottom: 16px;
		overflow: hidden;
	}
	.tab {
		flex: 1;
		padding: 10px 16px;
		border: none;
		background: #f5f4f1;
		font-size: 0.95rem;
		font-weight: 500;
		color: var(--muted);
		cursor: pointer;
		font-family: inherit;
		border-right: 1px solid var(--border);
		transition: background 0.15s, color 0.15s;
	}
	.tab:last-child { border-right: none; }
	.tab:hover { background: #eae9e5; color: var(--text); }
	.tab.active {
		background: var(--card);
		color: var(--accent);
		box-shadow: inset 0 -2px 0 var(--accent);
	}
	.tab-count {
		font-size: 0.8rem;
		font-weight: 400;
		color: var(--muted);
		margin-left: 4px;
	}

	/* Shared table styles */
	.tab-content table {
		width: 100%;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		overflow: hidden;
	}
	.tab-content thead th {
		background: #f5f4f1;
		padding: 8px 10px;
		text-align: left;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		white-space: nowrap;
	}
	.tab-content tbody tr { border-bottom: 1px solid #f0efec; }
	.tab-content tbody tr:last-child { border-bottom: none; }
	.tab-content tbody tr:hover { background: #fafaf8; }
	.tab-content td {
		padding: 7px 10px;
		font-size: 0.95rem;
		vertical-align: middle;
	}
	.tab-content td a { color: var(--accent); text-decoration: none; }
	.tab-content td a:hover { text-decoration: underline; }

	.source-tag-label {
		display: inline-block;
		padding: 2px 7px;
		border-radius: 3px;
		font-size: 0.8rem;
		font-weight: 600;
	}
	.source-hal-label { background: #e8f0f8; color: #3b6b9e; }
	.source-oa-label { background: #fef3e0; color: #b8733e; }
	.source-wos-label { background: #e8e0f8; color: #5a3d8a; }

	/* Publications tab */
	.toolbar {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 10px;
	}
	.count {
		font-size: 0.85rem;
		color: var(--muted);
	}
	.export-btn {
		padding: 4px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--card);
		font-size: 0.85rem;
		color: var(--muted);
		text-decoration: none;
		cursor: pointer;
		white-space: nowrap;
	}
	.export-btn:hover {
		border-color: var(--accent);
		color: var(--accent);
	}
	.pub-table td { vertical-align: top; }
	.pub-title {
		font-weight: 500; color: var(--text); max-width: 500px;
		text-decoration: none; display: inline-block;
	}
	.pub-title:hover { color: var(--accent); text-decoration: underline; }
	.journal-cell { font-size: 0.85rem; color: var(--muted); }

	.source-tag {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		text-decoration: none;
		margin-right: 3px;
		vertical-align: middle;
		transition: transform 0.1s;
	}
	.source-tag:hover { transform: scale(1.15); }
	.source-tag img, .source-tag :global(svg) { width: 14px; height: 14px; display: block; }
	.source-hal { background: #e8f0f8; }
	.source-hal:hover { background: #d0e3f4; }
	.source-oa { background: #fef3e0; }
	.source-oa:hover { background: #fde8c8; }
	.source-wos { background: #e8e0f8; }
	.source-wos:hover { background: #d8c8f4; }
	.wos-label { font-size: 11px; font-weight: 700; color: #5a3d8a; line-height: 14px; }
	.source-doi { background: #f0f0f0; }
	.source-doi:hover { background: #e0e0e0; }
	.source-placeholder { visibility: hidden; }
	.links-cell { white-space: nowrap; }

	.lab-tag {
		display: inline-block;
		font-size: 0.8rem;
		padding: 1px 7px;
		border-radius: 10px;
		background: #e8f0f8;
		color: var(--accent);
		font-weight: 500;
	}
	.oa-tag {
		display: inline-block;
		font-size: 0.7rem;
		padding: 1px 6px;
		border-radius: 8px;
		font-weight: 600;
	}
	:global(.oa-gold) { background: #fef3e0; color: #d4a017; }
	:global(.oa-diamond) { background: #e0f2f7; color: #0288a8; }
	:global(.oa-hybrid) { background: #f3eef9; color: #8e6bbf; }
	:global(.oa-green) { background: #e6f4ec; color: #2a7d4f; }
	:global(.oa-bronze) { background: #fdf0e6; color: #b8733e; }
	:global(.oa-closed) { background: #e0e0e0; color: #555; }
	.type-label { font-size: 0.8rem; color: var(--muted); }
	.corr-cell { text-align: center; color: var(--accent); font-size: 0.85rem; }

	/* Addresses tab */
	.addr-cell { font-size: 0.85rem; color: var(--muted); word-break: break-all; }
	.struct-tag {
		display: inline-block;
		padding: 2px 7px;
		background: #e8f0f8;
		border-radius: 3px;
		font-size: 0.8rem;
		color: var(--accent);
		font-weight: 500;
		margin: 1px 2px;
	}

	.exclude-cell { padding: 0 2px !important; text-align: center; vertical-align: middle; }
	.exclude-btn {
		background: none; border: none; cursor: pointer;
		color: #ccc; font-size: 0.85rem; padding: 2px 4px;
		border-radius: 3px; line-height: 1; transition: color 0.15s, background 0.15s;
	}
	.exclude-btn:hover { color: #c0392b; background: #fdeaea; }

	.no-results { text-align: center; padding: 40px; color: var(--muted); }
	.loading { text-align: center; padding: 40px; color: var(--muted); }
</style>
