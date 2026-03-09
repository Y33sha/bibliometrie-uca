<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { api } from '$lib/api';
	import { sanitizeTitle } from '$lib/utils';
	import FacetDropdown from '$lib/components/FacetDropdown.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import type { FacetOption } from '$lib/components/FacetDropdown.svelte';

	/* ── Types ── */

	interface AuthorshipStats {
		total_uca_authors: number;
		linked_to_person: number;
		with_orcid: number;
		with_idhal: number;
	}

	interface PersonRef {
		id: number;
		first_name: string;
		last_name: string;
		department_name?: string;
		has_rh?: boolean;
	}

	interface Author {
		id: number;
		source: string;
		full_name: string;
		orcid?: string;
		idhal?: string;
		uca_pub_count: number;
		person_id?: number | null;
		person?: PersonRef;
	}

	interface AuthorListResponse {
		total: number;
		page: number;
		pages: number;
		authors: Author[];
	}

	interface Signature {
		source: string;
		raw_affiliation: string;
	}

	interface Publication {
		pub_year: number | null;
		title: string;
		doi?: string;
	}

	interface AuthorDetails {
		signatures: Signature[];
		publications: Publication[];
	}

	interface Lab {
		id: number;
		name: string;
		acronym: string | null;
	}

	interface LinkSearch {
		query: string;
		results: PersonRef[];
		loading: boolean;
	}

	/* ── Filter options ── */

	const linkedOptions: FacetOption[] = [
		{ value: 'yes', text: 'Identité résolue' },
		{ value: 'no', text: 'Non résolue' }
	];
	const orcidOptions: FacetOption[] = [
		{ value: 'yes', text: 'Avec ORCID' },
		{ value: 'no', text: 'Sans ORCID' }
	];
	const idhalOptions: FacetOption[] = [
		{ value: 'yes', text: 'Avec idHAL' },
		{ value: 'no', text: 'Sans idHAL' }
	];

	/* ── State ── */

	let stats: AuthorshipStats | null = $state(null);

	let search = $state('');
	let selectedLinked: string[] = $state([]);
	let selectedOrcid: string[] = $state([]);
	let selectedIdhal: string[] = $state([]);
	let selectedLabs: string[] = $state([]);
	let labOptions: FacetOption[] = $state([]);

	let currentPage = $state(1);
	let totalPages = $state(0);
	let totalCount = $state(0);
	let authors: Author[] = $state([]);
	let loading = $state(false);

	let expandedRows: Record<string, AuthorDetails | 'loading'> = $state({});
	let linkSearches: Record<string, LinkSearch> = $state({});

	let searchTimeout: ReturnType<typeof setTimeout> | null = null;
	let linkSearchTimers: Record<string, ReturnType<typeof setTimeout>> = {};

	/* ── Derived ── */

	const unlinked = $derived(
		stats ? stats.total_uca_authors - stats.linked_to_person : 0
	);

	/* ── Data loading ── */

	async function loadStats() {
		const params = new URLSearchParams();
		if (selectedLabs.length === 1) params.set('lab_id', selectedLabs[0]);
		const qs = params.toString();
		stats = await api<AuthorshipStats>('/api/authorships/stats' + (qs ? '?' + qs : ''));
	}

	async function loadTable() {
		loading = true;
		const params = new URLSearchParams({
			page: String(currentPage),
			per_page: '50'
		});
		if (search) params.set('search', search);
		if (selectedLinked.length === 1) params.set('linked', selectedLinked[0]);
		if (selectedOrcid.length === 1) params.set('has_orcid', selectedOrcid[0]);
		if (selectedIdhal.length === 1) params.set('has_idhal', selectedIdhal[0]);
		if (selectedLabs.length === 1) params.set('lab_id', selectedLabs[0]);

		const data = await api<AuthorListResponse>('/api/authorships?' + params);
		authors = data.authors;
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
		setOrDel('lab', selectedLabs.length === 1 ? selectedLabs[0] : '');
		setOrDel('linked', selectedLinked.length === 1 ? selectedLinked[0] : '');
		setOrDel('orcid', selectedOrcid.length === 1 ? selectedOrcid[0] : '');
		setOrDel('idhal', selectedIdhal.length === 1 ? selectedIdhal[0] : '');
		history.replaceState(null, '', url);
	}

	function readUrlFilters() {
		const p = new URLSearchParams(window.location.search);
		if (p.get('p')) currentPage = Math.max(1, parseInt(p.get('p')!, 10) || 1);
		if (p.get('search')) search = p.get('search')!;
		if (p.get('lab')) selectedLabs = [p.get('lab')!];
		if (p.get('linked')) selectedLinked = [p.get('linked')!];
		if (p.get('orcid')) selectedOrcid = [p.get('orcid')!];
		if (p.get('idhal')) selectedIdhal = [p.get('idhal')!];
	}

	function handleSearch() {
		if (searchTimeout) clearTimeout(searchTimeout);
		searchTimeout = setTimeout(() => {
			currentPage = 1;
			loadTable();
		}, 400);
	}

	function handleFilterChange() {
		currentPage = 1;
		loadStats();
		loadTable();
	}

	function handlePageChange(p: number) {
		currentPage = p;
		loadTable();
		window.scrollTo(0, 0);
	}

	/* ── Detail expand/collapse ── */

	function rowKey(a: Author): string {
		return `${a.source}-${a.id}`;
	}

	async function toggleDetail(a: Author) {
		const key = rowKey(a);
		if (key in expandedRows) {
			const next = { ...expandedRows };
			delete next[key];
			expandedRows = next;
			return;
		}
		expandedRows = { ...expandedRows, [key]: 'loading' };
		const details = await api<AuthorDetails>(
			`/api/authors/${a.source}/${a.id}/details`
		);
		expandedRows = { ...expandedRows, [key]: details };
	}

	function isExpanded(a: Author): boolean {
		return rowKey(a) in expandedRows;
	}

	function getDetails(a: Author): AuthorDetails | 'loading' | undefined {
		return expandedRows[rowKey(a)];
	}

	/* ── Link / Unlink ── */

	function openLinkSearch(a: Author) {
		const key = rowKey(a);
		linkSearches = { [key]: { query: '', results: [], loading: false } };
	}

	function closeLinkSearch(a: Author) {
		const key = rowKey(a);
		const next = { ...linkSearches };
		delete next[key];
		linkSearches = next;
		if (linkSearchTimers[key]) clearTimeout(linkSearchTimers[key]);
	}

	function handleLinkSearchInput(a: Author, query: string) {
		const key = rowKey(a);
		linkSearches = { ...linkSearches, [key]: { ...linkSearches[key], query } };

		if (linkSearchTimers[key]) clearTimeout(linkSearchTimers[key]);
		if (query.trim().length < 2) {
			linkSearches = { ...linkSearches, [key]: { ...linkSearches[key], results: [], loading: false } };
			return;
		}

		linkSearchTimers[key] = setTimeout(async () => {
			linkSearches = { ...linkSearches, [key]: { ...linkSearches[key], loading: true } };
			const results = await api<PersonRef[]>(`/api/persons/search?q=${encodeURIComponent(query.trim())}`);
			linkSearches = { ...linkSearches, [key]: { ...linkSearches[key], results, loading: false } };
		}, 300);
	}

	async function linkAuthor(a: Author, personId: number) {
		await fetch(`${base}/api/persons/${personId}/link`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ author_id: a.id, source: a.source })
		});
		closeLinkSearch(a);
		loadStats();
		loadTable();
	}

	async function unlinkAuthor(a: Author) {
		if (!a.person) return;
		await fetch(`${base}/api/persons/${a.person.id}/link/${a.source}/${a.id}`, {
			method: 'DELETE'
		});
		loadStats();
		loadTable();
	}

	/* ── Lifecycle ── */

	onMount(async () => {
		readUrlFilters();

		// Load lab options
		const labs = await api<Lab[]>('/api/laboratories');
		labOptions = labs.map((l) => ({
			value: String(l.id),
			text: l.acronym || l.name
		}));

		loadStats();
		loadTable();
	});
</script>

<svelte:head>
	<title>Admin - Auteurs UCA - Bibliométrie UCA</title>
</svelte:head>

<!-- Stats row -->
{#if stats}
	<div class="stats-row">
		<div class="stat-card">
			<div class="value">{stats.total_uca_authors}</div>
			<div class="label">Auteurs UCA</div>
		</div>
		<div class="stat-card hl-success">
			<div class="value value-success">{stats.linked_to_person}</div>
			<div class="label">Identité résolue</div>
		</div>
		<div class="stat-card hl-warning">
			<div class="value value-warning">{unlinked}</div>
			<div class="label">Non résolue</div>
		</div>
		<div class="stat-card hl-accent">
			<div class="value value-accent">{stats.with_orcid}</div>
			<div class="label">Avec ORCID</div>
		</div>
		<div class="stat-card hl-accent">
			<div class="value value-accent">{stats.with_idhal}</div>
			<div class="label">Avec idHAL</div>
		</div>
	</div>
{/if}

<!-- Toolbar -->
<div class="toolbar">
	<input
		type="text"
		placeholder="Rechercher (nom, ORCID, idHAL)…"
		bind:value={search}
		oninput={handleSearch}
	/>
	<FacetDropdown label="Laboratoire" options={labOptions} searchable bind:selected={selectedLabs} onchange={handleFilterChange} />
	<FacetDropdown label="Identité" options={linkedOptions} bind:selected={selectedLinked} onchange={handleFilterChange} />
	<FacetDropdown label="ORCID" options={orcidOptions} bind:selected={selectedOrcid} onchange={handleFilterChange} />
	<FacetDropdown label="idHAL" options={idhalOptions} bind:selected={selectedIdhal} onchange={handleFilterChange} />
	<span class="count">{totalCount} auteurs</span>
</div>

<!-- Table -->
{#if authors.length === 0 && !loading}
	<div class="empty">Aucun auteur trouvé.</div>
{:else}
	<table class="data-table">
		<thead>
			<tr>
				<th></th>
				<th>Nom</th>
				<th>Identifiants</th>
				<th>Sources</th>
				<th>Publis UCA</th>
				<th>Identité</th>
			</tr>
		</thead>
		<tbody>
			{#each authors as a (rowKey(a))}
				{@const expanded = isExpanded(a)}
				{@const details = getDetails(a)}
				{@const key = rowKey(a)}
				{@const ls = linkSearches[key]}
				<!-- Main row -->
				<tr>
					<td>
						<button
							class="btn-expand"
							title="Détails"
							onclick={() => toggleDetail(a)}
						>
							{expanded ? '\u25BC' : '\u25B6'}
						</button>
					</td>
					<td><strong>{a.full_name}</strong></td>
					<td>
						{#if a.orcid}
							<span class="tag tag-id" title="ORCID">{a.orcid}</span>
						{/if}
						{#if a.idhal}
							<span class="tag tag-id" title="idHAL">{a.idhal}</span>
						{/if}
						{#if !a.orcid && !a.idhal}
							<span class="no-id">aucun</span>
						{/if}
					</td>
					<td>
						<span class="tag tag-source">{a.source}</span>
					</td>
					<td>{a.uca_pub_count}</td>
					<td>
						{#if a.person}
							<span class="person-link">
								<span class="tag tag-linked"
									>{a.person.first_name} {a.person.last_name}</span
								>
								{#if a.person.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
								{#if a.person.department_name}
									<span class="dept">{a.person.department_name}</span>
								{/if}
								<button
									class="btn-unlink"
									title="Détacher"
									onclick={() => unlinkAuthor(a)}
								>&times;</button>
							</span>
						{:else if ls}
							<div class="link-search">
								<input
									type="text"
									placeholder="Chercher une personne…"
									value={ls.query}
									oninput={(e) => handleLinkSearchInput(a, (e.target as HTMLInputElement).value)}
								/>
								<button class="btn-cancel" onclick={() => closeLinkSearch(a)}>&times;</button>
								{#if ls.loading}
									<div class="search-results"><span class="loading-text">Recherche…</span></div>
								{:else if ls.results.length > 0}
									<div class="search-results">
										{#each ls.results as p (p.id)}
											<button class="search-result" onclick={() => linkAuthor(a, p.id)}>
												<strong>{p.last_name}</strong> {p.first_name}
												{#if p.department_name}
													<span class="dept">{p.department_name}</span>
												{/if}
											</button>
										{/each}
									</div>
								{:else if ls.query.trim().length >= 2}
									<div class="search-results"><span class="loading-text">Aucun résultat</span></div>
								{/if}
							</div>
						{:else}
							<button class="btn-rattacher" onclick={() => openLinkSearch(a)}>
								Rattacher
							</button>
						{/if}
					</td>
				</tr>
				<!-- Detail row -->
				{#if expanded}
					<tr class="detail-row">
						<td colspan="6">
							{#if details === 'loading'}
								<span class="loading-text">Chargement…</span>
							{:else if details}
								<div class="detail-panel">
									{#if details.signatures.length}
										<h5>Signatures ({details.signatures.length})</h5>
										<ul class="sig-list">
											{#each details.signatures as sig}
												<li>
													<span class="sig-source">{sig.source}</span>
													<span class="sig-text"
														>{sig.raw_affiliation}</span
													>
												</li>
											{/each}
										</ul>
									{:else}
										<h5>Signatures</h5>
										<div class="loading-text">Aucune</div>
									{/if}

									{#if details.publications.length}
										<h5>
											Publications UCA récentes ({details.publications
												.length})
										</h5>
										<ul class="pub-list">
											{#each details.publications as pub}
												<li>
													<span class="pub-year"
														>{pub.pub_year ?? '?'}</span
													>
													<span class="pub-title">{@html sanitizeTitle(pub.title)}</span>
													{#if pub.doi}
														<a
															href="https://doi.org/{pub.doi}"
															target="_blank"
															rel="noopener noreferrer"
															class="pub-doi">DOI</a
														>
													{/if}
												</li>
											{/each}
										</ul>
									{/if}
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
	.stat-card.hl-accent {
		border-left: 3px solid var(--accent);
	}
	.value-success {
		color: var(--success);
	}
	.value-warning {
		color: var(--warning);
	}
	.value-accent {
		color: var(--accent);
	}

	/* ── Toolbar ── */
	.toolbar {
		display: flex;
		gap: 8px;
		margin-bottom: 16px;
		align-items: center;
		flex-wrap: wrap;
		padding: 10px 14px;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
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
		overflow: hidden;
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
	.tag-id {
		background: var(--accent-light);
		color: var(--accent);
		font-family: 'SF Mono', SFMono-Regular, Consolas, 'Liberation Mono', Menlo,
			monospace;
		font-size: 10px;
	}
	.tag-source {
		background: #eee;
		color: #555;
		font-size: 10px;
	}
	.no-id {
		color: var(--text-muted);
		font-size: 11px;
	}

	/* ── Person link ── */
	.person-link {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	.dept {
		font-size: 10px;
		color: var(--text-muted);
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
		margin-left: 2px;
	}
	.btn-unlink:hover {
		background: var(--danger);
		color: white;
	}

	/* ── Rattacher button ── */
	.btn-rattacher {
		padding: 2px 8px;
		border: 1px dashed var(--border);
		border-radius: 4px;
		background: none;
		font-size: 11px;
		cursor: pointer;
		color: var(--accent);
		font-family: inherit;
	}
	.btn-rattacher:hover {
		background: var(--accent-light);
		border-style: solid;
	}

	/* ── Link search ── */
	.link-search {
		position: relative;
		display: flex;
		align-items: center;
		gap: 4px;
		flex-wrap: wrap;
	}
	.link-search input {
		padding: 3px 6px;
		border: 1px solid var(--accent);
		border-radius: 3px;
		font-size: 12px;
		font-family: inherit;
		width: 180px;
	}
	.btn-cancel {
		border: 1px solid var(--border);
		background: none;
		border-radius: 3px;
		cursor: pointer;
		padding: 2px 6px;
		font-size: 12px;
		color: var(--text-muted);
		font-family: inherit;
	}
	.btn-cancel:hover {
		background: #f0efec;
	}
	.search-results {
		position: absolute;
		top: 100%;
		left: 0;
		width: 280px;
		background: white;
		border: 1px solid var(--border);
		border-radius: 4px;
		box-shadow: 0 4px 12px rgba(0,0,0,0.1);
		z-index: 10;
		max-height: 200px;
		overflow-y: auto;
		margin-top: 2px;
	}
	.search-results .loading-text {
		padding: 6px 10px;
		font-size: 11px;
	}
	.search-result {
		display: block;
		width: 100%;
		text-align: left;
		padding: 6px 10px;
		border: none;
		background: none;
		cursor: pointer;
		font-size: 12px;
		font-family: inherit;
		border-bottom: 1px solid #f0efec;
	}
	.search-result:last-child {
		border-bottom: none;
	}
	.search-result:hover {
		background: var(--accent-light);
	}

	/* ── Expand button ── */
	.btn-expand {
		background: none;
		border: none;
		cursor: pointer;
		font-size: 14px;
		padding: 2px 6px;
		color: var(--accent);
		font-family: inherit;
	}

	/* ── Detail panel ── */
	.detail-row {
		background: #f5f7fa;
	}
	.detail-row td {
		padding: 10px 20px;
	}
	.detail-row:hover td {
		background: #f5f7fa;
	}
	.detail-panel {
		font-size: 12px;
	}
	.detail-panel h5 {
		margin: 0 0 4px;
		font-size: 11px;
		color: var(--accent);
		text-transform: uppercase;
		letter-spacing: 0.3px;
	}

	/* Signatures */
	.sig-list {
		margin: 0 0 8px;
		padding: 0;
		list-style: none;
	}
	.sig-list li {
		padding: 2px 0;
		border-bottom: 1px solid #f0efec;
		display: flex;
		gap: 6px;
		align-items: baseline;
	}
	.sig-list li:last-child {
		border-bottom: none;
	}
	.sig-source {
		font-size: 10px;
		color: white;
		background: #8899aa;
		border-radius: 3px;
		padding: 0 4px;
		flex-shrink: 0;
	}
	.sig-text {
		word-break: break-word;
		color: #444;
	}

	/* Publications */
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
	.pub-doi {
		font-size: 10px;
		color: var(--accent);
		text-decoration: none;
		margin-left: 4px;
	}
	.pub-doi:hover {
		text-decoration: underline;
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
