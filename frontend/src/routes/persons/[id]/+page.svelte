<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import { onMount } from 'svelte';
	import { api } from '$lib/api';
	import { titleCase, formatDate, sanitizeTitle } from '$lib/utils';
	import { typeLabels } from '$lib/labels';
	import Pagination from '$lib/components/Pagination.svelte';

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
		labs: string | null;
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
		const set = new Set<string>();
		identifiers.filter((i) => i.id_type === 'orcid').forEach((i) => set.add(i.id_value));
		return Array.from(set);
	});

	const allIdhals = $derived(() => {
		const set = new Set<string>();
		authors.forEach((a) => { if (a.idhal) set.add(a.idhal); });
		identifiers.filter((i) => i.id_type === 'idhal').forEach((i) => set.add(i.id_value));
		return Array.from(set);
	});

	async function loadPublications() {
		const params = new URLSearchParams({
			page: String(pubPage),
			per_page: String(pubPerPage),
			person_id: personId,
			sort: 'year_desc'
		});
		const data = await api<PubResponse>('/api/publications?' + params);
		publications = data.publications;
		pubTotal = data.total;
		pubPages = data.pages;
		pubPage = data.page;
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
		return `${base}/api/publications/export.csv?person_id=${personId}&sort=year_desc`;
	}

	function switchTab(tab: Tab) {
		const url = new URL($page.url);
		if (tab === 'publications') {
			url.searchParams.delete('tab');
		} else {
			url.searchParams.set('tab', tab);
		}
		goto(url.toString(), { replaceState: true, noScroll: true });
		if (tab === 'publications' && publications.length === 0 && pubTotal === 0) loadPublications();
		if (tab === 'addresses' && !addrLoaded) loadAddresses();
	}

	onMount(async () => {
		canGoBack = (window.navigation?.canGoBack ?? document.referrer.startsWith(window.location.origin));
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
		else if (activeTab === 'publications') loadPublications();
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
				<span class="id-item">
					<span class="id-label">ORCID</span>
					<a href="https://orcid.org/{oid}" target="_blank" rel="noopener" class="id-badge">{oid}</a>
				</span>
			{/each}
			{#each allIdhals() as idh}
				<span class="id-item">
					<span class="id-label">idHAL</span>
					<a href="https://hal.science/search/index/?q=%2A&authIdHal_s={idh}" target="_blank" rel="noopener" class="id-badge">{idh}</a>
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
				<span class="count">{pubTotal} publication{pubTotal > 1 ? 's' : ''}</span>
				<a href={exportCsvUrl()} class="export-btn" download>Export CSV</a>
			</div>
			<table class="pub-table">
				<thead>
					<tr>
						<th style="width:40px">An.</th>
						<th>Titre</th>
						<th>Revue</th>
						<th style="width:80px">Labo(s)</th>
						<th style="width:80px">Liens</th>
						<th style="width:50px">OA</th>
						<th style="width:80px">Type</th>
					</tr>
				</thead>
				<tbody>
					{#if publications.length === 0}
						<tr><td colspan="7" class="no-results">Aucune publication</td></tr>
					{:else}
						{#each publications as p (p.id)}
							<tr>
								<td>{p.pub_year || ''}</td>
								<td><a href="{base}/publications/{p.id}" class="pub-title">{@html sanitizeTitle(p.title)}</a></td>
								<td class="journal-cell">{p.journal || ''}</td>
								<td>
									{#each (p.labs || '').split(', ').filter(Boolean) as lab}
										<span class="lab-tag">{lab}</span>
									{/each}
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
									{#if p.doi}
										<a href="https://doi.org/{p.doi}" target="_blank" rel="noopener" class="source-tag source-doi" title={p.doi}>
											<svg viewBox="0 0 24 24" fill="none" stroke="#555" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
										</a>
									{:else}
										<span class="source-tag source-placeholder"></span>
									{/if}
								</td>
								<td>
									{#if p.oa_status && p.oa_status !== 'unknown'}
										<span class="oa-tag oa-{p.oa_status}">{p.oa_status}</span>
									{/if}
								</td>
								<td>
									<span class="type-label">{typeLabels[p.doc_type || ''] || p.doc_type || ''}</span>
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
		font-size: 13px;
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
		font-size: 20px;
		font-weight: 600;
		margin: 0 0 6px;
	}
	.profile-last { font-weight: 600; }
	.profile-meta {
		display: flex;
		gap: 16px;
		align-items: center;
		flex-wrap: wrap;
		font-size: 13px;
		color: var(--muted);
	}
	.role-badge {
		display: inline-block;
		padding: 2px 8px;
		background: #f0efec;
		border-radius: 3px;
		font-size: 12px;
		color: var(--muted);
	}
	.id-item { display: flex; align-items: center; gap: 6px; font-size: 13px; }
	.id-label { font-weight: 500; color: var(--muted); font-size: 12px; }
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
		font-size: 13px;
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
		font-size: 11px;
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
		font-size: 12px;
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
		font-size: 13px;
		vertical-align: middle;
	}
	.tab-content td a { color: var(--accent); text-decoration: none; }
	.tab-content td a:hover { text-decoration: underline; }

	.source-tag-label {
		display: inline-block;
		padding: 2px 7px;
		border-radius: 3px;
		font-size: 11px;
		font-weight: 600;
	}
	.source-hal-label { background: #e8f0f8; color: #3b6b9e; }
	.source-oa-label { background: #fef3e0; color: #b8733e; }

	/* Publications tab */
	.toolbar {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 10px;
	}
	.count {
		font-size: 12px;
		color: var(--muted);
	}
	.export-btn {
		padding: 4px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--card);
		font-size: 12px;
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
	.journal-cell { font-size: 12px; color: var(--muted); }

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
	.source-doi { background: #f0f0f0; }
	.source-doi:hover { background: #e0e0e0; }
	.source-placeholder { visibility: hidden; }
	.links-cell { white-space: nowrap; }

	.lab-tag {
		display: inline-block;
		font-size: 11px;
		padding: 1px 7px;
		border-radius: 10px;
		background: #e8f0f8;
		color: var(--accent);
		font-weight: 500;
	}
	.oa-tag {
		display: inline-block;
		font-size: 10px;
		padding: 1px 6px;
		border-radius: 8px;
		font-weight: 600;
	}
	:global(.oa-gold) { background: #fef3e0; color: #d4a017; }
	:global(.oa-hybrid) { background: #f3eef9; color: #8e6bbf; }
	:global(.oa-green) { background: #e6f4ec; color: #2a7d4f; }
	:global(.oa-bronze) { background: #fdf0e6; color: #b8733e; }
	:global(.oa-closed) { background: #e0e0e0; color: #555; }
	.type-label { font-size: 11px; color: var(--muted); }

	/* Addresses tab */
	.addr-cell { font-size: 12px; color: var(--muted); word-break: break-all; }
	.struct-tag {
		display: inline-block;
		padding: 2px 7px;
		background: #e8f0f8;
		border-radius: 3px;
		font-size: 11px;
		color: var(--accent);
		font-weight: 500;
		margin: 1px 2px;
	}

	.no-results { text-align: center; padding: 40px; color: var(--muted); }
	.loading { text-align: center; padding: 40px; color: var(--muted); }
</style>
