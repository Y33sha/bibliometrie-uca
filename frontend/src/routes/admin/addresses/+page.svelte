<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { api } from '$lib/api';
	import { esc, sanitizeTitle } from '$lib/utils';
	import Pagination from '$lib/components/Pagination.svelte';

	// ---- Type definitions ----

	interface Structure {
		id: number;
		name: string;
		acronym: string | null;
		code: string | null;
		type: string;
	}

	interface Stats {
		pending: number;
		rejected: number;
		confirmed: number;
	}

	interface AddressStructure {
		acronym: string | null;
		name: string;
	}

	interface Address {
		id: number;
		raw_text: string;
		pub_count: number;
		is_confirmed: boolean | null;
		structures: AddressStructure[];
	}

	interface AddressesResponse {
		total: number;
		pages: number;
		page: number;
		addresses: Address[];
	}

	interface Publication {
		title: string | null;
		pub_year: number | null;
		doc_type: string | null;
		author_name: string | null;
		journal_title: string | null;
		doi: string | null;
		openalex_id: string | null;
	}

	interface PublicationsResponse {
		publications: Publication[];
	}

	interface GroupedStructures {
		[type: string]: Structure[];
	}

	// ---- Constants ----

	const TYPE_LABELS: Record<string, string> = {
		universite: 'Universités',
		onr: 'Organismes de recherche',
		chu: 'CHU',
		ecole: 'Écoles',
		labo: 'Laboratoires'
	};
	const ALLOWED_TYPES = Object.keys(TYPE_LABELS);

	// ---- Reactive state ----

	let currentPage = $state(1);
	let currentStatus = $state('pending');
	let currentSearch = $state('');
	let currentSearchMode = $state('contains');
	let currentStructureId = $state<number | null>(null);

	let structures = $state<GroupedStructures>({});
	let stats = $state<Stats>({ pending: 0, rejected: 0, confirmed: 0 });
	let addresses = $state<Address[]>([]);
	let totalAddresses = $state(0);
	let totalPages = $state(0);
	let loading = $state(true);

	let selectedIds = $state<Set<number>>(new Set());
	let selectAll = $state(false);

	let expandedId = $state<number | null>(null);
	let publications = $state<Publication[]>([]);
	let pubsLoading = $state(false);

	let searchTimeout: ReturnType<typeof setTimeout> | null = null;

	let mainPanel: HTMLDivElement | undefined = $state();

	const selectedCount = $derived(selectedIds.size);
	const resultCountText = $derived(
		`${totalAddresses} adresse${totalAddresses > 1 ? 's' : ''}`
	);

	// ---- Data loading ----

	async function loadStructures(): Promise<void> {
		const all = await api<Structure[]>('/api/structures');
		const grouped: GroupedStructures = {};
		let ucaId: number | null = null;

		for (const s of all) {
			if (!ALLOWED_TYPES.includes(s.type)) continue;
			if (s.code === 'uca') ucaId = s.id;
			if (!grouped[s.type]) grouped[s.type] = [];
			grouped[s.type].push(s);
		}

		structures = grouped;

		if (ucaId) {
			currentStructureId = ucaId;
		} else {
			// Pick the first available structure
			for (const type of ALLOWED_TYPES) {
				if (grouped[type]?.length) {
					currentStructureId = grouped[type][0].id;
					break;
				}
			}
		}
	}

	async function loadStats(): Promise<void> {
		const params = new URLSearchParams();
		if (currentStructureId) params.set('structure_id', String(currentStructureId));
		stats = await api<Stats>(`/api/stats?${params}`);
	}

	async function loadAddresses(): Promise<void> {
		loading = true;
		const params = new URLSearchParams({
			page: String(currentPage),
			per_page: '200',
			status: currentStatus,
			search: currentSearch,
			search_mode: currentSearchMode
		});
		if (currentStructureId) params.set('structure_id', String(currentStructureId));

		const data = await api<AddressesResponse>(`/api/addresses?${params}`);
		addresses = data.addresses;
		totalAddresses = data.total;
		totalPages = data.pages;
		selectAll = false;
		loading = false;
	}

	async function loadPublications(addrId: number): Promise<void> {
		pubsLoading = true;
		const data = await api<PublicationsResponse>(`/api/addresses/${addrId}/publications`);
		publications = data.publications;
		pubsLoading = false;
	}

	// ---- Actions ----

	function toggleDetail(addrId: number): void {
		if (expandedId === addrId) {
			expandedId = null;
			publications = [];
			return;
		}
		expandedId = addrId;
		publications = [];
		loadPublications(addrId);
	}

	async function reviewAddr(addrId: number, isConfirmed: boolean | null): Promise<void> {
		await fetch(`${base}/api/addresses/${addrId}/review`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ structure_id: currentStructureId, is_confirmed: isConfirmed })
		});
		loadStats();
		loadAddresses();
	}

	async function batchReview(isConfirmed: boolean | null): Promise<void> {
		const ids = Array.from(selectedIds);
		await fetch(base + '/api/addresses/batch-review', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				address_ids: ids,
				structure_id: currentStructureId,
				is_confirmed: isConfirmed
			})
		});
		selectedIds = new Set();
		loadStats();
		loadAddresses();
	}

	function toggleSelectAll(checked: boolean): void {
		selectAll = checked;
		if (checked) {
			selectedIds = new Set(addresses.map((a) => a.id));
		} else {
			selectedIds = new Set();
		}
	}

	function toggleSelect(addrId: number): void {
		const next = new Set(selectedIds);
		if (next.has(addrId)) {
			next.delete(addrId);
		} else {
			next.add(addrId);
		}
		selectedIds = next;
	}

	function clearSelection(): void {
		selectedIds = new Set();
		selectAll = false;
	}

	function onSearchInput(e: Event): void {
		const value = (e.target as HTMLInputElement).value;
		if (searchTimeout) clearTimeout(searchTimeout);
		searchTimeout = setTimeout(() => {
			currentSearch = value;
			currentPage = 1;
			loadAddresses();
		}, 400);
	}

	function onSearchModeChange(e: Event): void {
		currentSearchMode = (e.target as HTMLSelectElement).value;
		if (currentSearch) {
			currentPage = 1;
			loadAddresses();
		}
	}

	function onStatusChange(e: Event): void {
		currentStatus = (e.target as HTMLSelectElement).value;
		currentPage = 1;
		loadAddresses();
	}

	function onStructureChange(e: Event): void {
		currentStructureId = parseInt((e.target as HTMLSelectElement).value);
		currentPage = 1;
		loadStats();
		loadAddresses();
	}

	function goToPage(p: number): void {
		currentPage = p;
		loadAddresses();
		mainPanel?.scrollTo(0, 0);
	}

	function cardClass(addr: Address): string {
		if (addr.is_confirmed === false) return 'addr-card reviewed-rejected';
		if (addr.is_confirmed === true) return 'addr-card reviewed-confirmed';
		return 'addr-card';
	}

	// ---- Init ----

	onMount(() => {
		loadStructures().then(() => {
			loadStats();
			loadAddresses();
		});
	});
</script>

<svelte:head>
	<title>Admin - Adresses - Bibliometrie UCA</title>
</svelte:head>

<div class="page-addresses">
	<!-- Toolbar: structure filter, search, status -->
	<div class="toolbar">
		<select
			class="structure-filter"
			value={currentStructureId ?? ''}
			onchange={onStructureChange}
		>
			{#each ALLOWED_TYPES as type}
				{#if structures[type]?.length}
					<optgroup label={TYPE_LABELS[type]}>
						{#each structures[type] as s (s.id)}
							<option value={s.id}>{s.acronym || s.name}</option>
						{/each}
					</optgroup>
				{/if}
			{/each}
		</select>

		<div class="toolbar-sep"></div>

		<label class="select-all-label">
			<input
				type="checkbox"
				checked={selectAll}
				onchange={(e) => toggleSelectAll((e.target as HTMLInputElement).checked)}
			/>
			Tout
		</label>

		<select value={currentSearchMode} onchange={onSearchModeChange}>
			<option value="contains">contient</option>
			<option value="not_contains">ne contient pas</option>
		</select>

		<input
			type="text"
			class="search-input"
			placeholder="Rechercher dans les adresses..."
			oninput={onSearchInput}
		/>

		<select value={currentStatus} onchange={onStatusChange}>
			<option value="pending">A examiner</option>
			<option value="confirmed">Confirmes</option>
			<option value="rejected">Rejetes</option>
			<option value="all">Tous</option>
		</select>

		<span class="count">{resultCountText}</span>
	</div>

	<!-- Stats bar -->
	<div class="stats-bar">
		<span class="stat-badge stat-pending">A examiner : {stats.pending}</span>
		<span class="stat-badge stat-rejected">Rejetes : {stats.rejected}</span>
		<span class="stat-badge stat-confirmed">Confirmes : {stats.confirmed}</span>
	</div>

	<!-- Batch action bar -->
	{#if selectedCount > 0}
		<div class="batch-bar">
			<span>{selectedCount} sélectionnée{selectedCount > 1 ? 's' : ''}</span>
			<div class="batch-actions">
				<button onclick={() => batchReview(false)}>&#x2717; Rejeter</button>
				<button onclick={() => batchReview(true)}>&#x2713; Confirmer</button>
				<button onclick={() => batchReview(null)}>&#x21BA; Reset</button>
				<button onclick={clearSelection}>Annuler</button>
			</div>
		</div>
	{/if}

	<!-- Address list -->
	<div class="main-panel" bind:this={mainPanel}>
		{#if loading}
			<div class="loading-msg">Chargement...</div>
		{:else if addresses.length === 0}
			<div class="loading-msg">Aucune adresse trouvee.</div>
		{:else}
			{#each addresses as addr (addr.id)}
				<div class={cardClass(addr)}>
					<div
						class="addr-header"
						onclick={() => toggleDetail(addr.id)}
						role="button"
						tabindex="0"
						onkeydown={(e) => {
							if (e.key === 'Enter' || e.key === ' ') toggleDetail(addr.id);
						}}
					>
						<!-- svelte-ignore a11y_click_events_have_key_events -->
						<input
							type="checkbox"
							checked={selectedIds.has(addr.id)}
							onclick={(e) => {
								e.stopPropagation();
								toggleSelect(addr.id);
							}}
						/>
						<div>
							<div class="addr-text">{@html esc(addr.raw_text)}</div>
							<div class="addr-meta">
								<span class="pub-count-tag"
									>{addr.pub_count} publi{addr.pub_count > 1 ? 's' : ''}</span
								>
								{#each addr.structures || [] as s}
									<span class="lab-tag">{@html esc(s.acronym || s.name)}</span>
								{/each}
							</div>
						</div>
						<!-- svelte-ignore a11y_click_events_have_key_events -->
						<div
							class="addr-actions"
							onclick={(e) => e.stopPropagation()}
							role="group"
						>
							<button
								class="btn btn-reject"
								title="Rejeter le lien"
								onclick={() => reviewAddr(addr.id, false)}>&#x2717;</button
							>
							<button
								class="btn btn-confirm"
								title="Confirmer le lien"
								onclick={() => reviewAddr(addr.id, true)}>&#x2713;</button
							>
							<button
								class="btn btn-reset"
								title="Reset"
								onclick={() => reviewAddr(addr.id, null)}>&#x21BA;</button
							>
						</div>
					</div>

					{#if expandedId === addr.id}
						<div class="addr-detail">
							{#if pubsLoading}
								<div class="detail-loading">Chargement...</div>
							{:else if publications.length === 0}
								<div class="detail-loading">Aucune publication liee.</div>
							{:else}
								<div class="detail-title">
									Publications ({publications.length})
								</div>
								{#each publications as p}
									<div class="pub-row">
										<div class="pub-title-link">
											{@html sanitizeTitle(p.title || '(sans titre)')}
										</div>
										<div class="pub-meta-inline">
											{p.pub_year}
											{#if p.doc_type}&middot; {@html esc(p.doc_type)}{/if}
											{#if p.author_name}&middot; {@html esc(p.author_name)}{/if}
											{#if p.journal_title}&middot; {@html esc(p.journal_title)}{/if}
											{#if p.doi}
												<a
													href="https://doi.org/{encodeURIComponent(p.doi)}"
													target="_blank"
													rel="noopener noreferrer">DOI</a
												>
											{/if}
											{#if p.openalex_id}
												<a
													href="https://openalex.org/{encodeURIComponent(p.openalex_id)}"
													target="_blank"
													rel="noopener noreferrer">OpenAlex</a
												>
											{/if}
										</div>
									</div>
								{/each}
							{/if}
						</div>
					{/if}
				</div>
			{/each}
		{/if}

		<Pagination page={currentPage} pages={totalPages} onchange={goToPage} />
	</div>
</div>

<style>
	/* Local CSS variables for status colors */
	.page-addresses {
		--danger: #c44;
		--danger-light: #fce8e8;
		--success: #2a7d4f;
		--success-light: #e6f5ed;
		--warning: #c68a19;
		--warning-light: #fef5e0;
		--accent-light: #e8f0f8;
		--highlight: #fff3b0;
	}

	/* Stats bar */
	.stats-bar {
		display: flex;
		gap: 12px;
		margin-bottom: 10px;
		font-size: 12px;
	}
	.stat-badge {
		padding: 3px 10px;
		border-radius: 12px;
		font-weight: 500;
	}
	.stat-pending {
		background: var(--warning-light);
		color: var(--warning);
	}
	.stat-rejected {
		background: var(--danger-light);
		color: var(--danger);
	}
	.stat-confirmed {
		background: var(--success-light);
		color: var(--success);
	}

	/* Toolbar */
	.toolbar {
		display: flex;
		gap: 8px;
		margin-bottom: 12px;
		align-items: center;
		flex-wrap: wrap;
	}
	.toolbar input[type='text'],
	.toolbar select {
		padding: 6px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 13px;
		background: white;
		font-family: inherit;
	}
	.search-input {
		width: 250px;
	}
	.count {
		margin-left: auto;
		color: var(--muted);
		font-size: 12px;
	}
	.toolbar-sep {
		width: 1px;
		height: 24px;
		background: var(--border);
		margin: 0 4px;
	}
	.structure-filter {
		font-weight: 600;
		border-color: var(--accent) !important;
		color: var(--accent);
	}
	.select-all-label {
		font-size: 12px;
		display: flex;
		align-items: center;
		gap: 4px;
		cursor: pointer;
	}

	/* Main panel */
	.main-panel {
		overflow-y: auto;
		max-height: calc(100vh - 220px);
	}

	/* Address cards */
	.addr-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		margin-bottom: 6px;
		transition: border-color 0.15s;
	}
	.addr-card:hover {
		border-color: var(--accent);
	}
	.reviewed-rejected {
		border-left: 3px solid var(--danger);
	}
	.reviewed-confirmed {
		border-left: 3px solid var(--success);
	}

	.addr-header {
		padding: 8px 12px;
		cursor: pointer;
		display: grid;
		grid-template-columns: 28px 1fr auto;
		gap: 10px;
		align-items: start;
	}
	.addr-header:hover {
		background: #fafaf8;
	}

	.addr-text {
		font-size: 13px;
		word-break: break-word;
	}
	.addr-meta {
		display: flex;
		gap: 10px;
		margin-top: 4px;
		font-size: 11px;
		color: var(--muted);
	}
	.lab-tag {
		display: inline-block;
		font-size: 11px;
		padding: 1px 7px;
		border-radius: 10px;
		background: var(--warning-light);
		color: var(--warning);
		font-weight: 500;
	}
	.pub-count-tag {
		display: inline-block;
		font-size: 11px;
		padding: 1px 7px;
		border-radius: 10px;
		background: var(--accent-light);
		color: var(--accent);
		font-weight: 500;
	}

	.addr-actions {
		display: flex;
		gap: 4px;
		flex-shrink: 0;
	}

	/* Detail panel */
	.addr-detail {
		padding: 0 12px 12px 50px;
		border-top: 1px solid var(--border);
	}
	.detail-loading {
		padding: 8px;
		color: var(--muted);
	}
	.detail-title {
		font-size: 11px;
		font-weight: 600;
		color: var(--muted);
		margin: 8px 0 4px 0;
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.pub-row {
		padding: 5px 0;
		border-bottom: 1px solid #f0f0ee;
		font-size: 12px;
	}
	.pub-row:last-child {
		border-bottom: none;
	}
	.pub-title-link {
		font-weight: 500;
		color: var(--text);
	}
	.pub-meta-inline {
		font-size: 11px;
		color: var(--muted);
		margin-top: 2px;
	}
	.pub-meta-inline a {
		color: var(--accent);
		text-decoration: none;
		margin-left: 6px;
	}
	.pub-meta-inline a:hover {
		text-decoration: underline;
	}

	/* Buttons */
	.btn {
		padding: 4px 10px;
		border-radius: 4px;
		border: 1px solid var(--border);
		background: white;
		font-size: 12px;
		cursor: pointer;
		transition: all 0.15s;
		font-family: inherit;
	}
	.btn:hover {
		background: #f0f0f0;
	}
	.btn-reject {
		color: var(--danger);
	}
	.btn-reject:hover {
		background: var(--danger-light);
		border-color: var(--danger);
	}
	.btn-confirm {
		color: var(--success);
	}
	.btn-confirm:hover {
		background: var(--success-light);
		border-color: var(--success);
	}
	.btn-reset {
		color: #888;
	}
	.btn-reset:hover {
		background: #f0f0f0;
		border-color: #888;
	}

	/* Batch bar */
	.batch-bar {
		background: var(--accent);
		color: white;
		padding: 8px 16px;
		border-radius: 6px;
		margin-bottom: 10px;
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.batch-actions {
		display: flex;
		gap: 6px;
	}
	.batch-bar button {
		padding: 4px 12px;
		border-radius: 4px;
		border: 1px solid rgba(255, 255, 255, 0.3);
		background: transparent;
		color: white;
		font-size: 12px;
		cursor: pointer;
		font-family: inherit;
	}
	.batch-bar button:hover {
		background: rgba(255, 255, 255, 0.15);
	}

	/* Loading */
	.loading-msg {
		text-align: center;
		padding: 40px;
		color: var(--muted);
	}
</style>
