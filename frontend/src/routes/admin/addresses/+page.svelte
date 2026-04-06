<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { page } from '$app/stores';
	import { replaceState } from '$app/navigation';
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
		total: number;
		detected: number;
		pending: number;
		rejected: number;
		confirmed: number;
	}

	interface AddressStructure {
		acronym: string | null;
		name: string;
		is_confirmed: boolean | null;
		is_detected: boolean;
	}

	interface Address {
		id: number;
		raw_text: string;
		pub_count: number;
		is_confirmed: boolean | null;
		is_detected: boolean;
		structures: AddressStructure[];
	}

	interface AddressesResponse {
		total: number;
		pages: number;
		page: number;
		addresses: Address[];
		requires_search?: boolean;
	}

	interface Publication {
		title: string | null;
		pub_year: number | null;
		doc_type: string | null;
		author_name: string | null;
		journal_title: string | null;
		doi: string | null;
		source_id: string | null;
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

	// ---- URL params helpers ----

	function readUrlParams(): { detected: string; validation: string; search: string; searchMode: string; p: number; structureId: number | null } {
		const sp = $page.url.searchParams;
		return {
			detected: sp.get('detected') || 'yes',
			validation: sp.get('validation') || 'pending',
			search: sp.get('search') || '',
			searchMode: sp.get('search_mode') || 'contains',
			p: parseInt(sp.get('page') || '1') || 1,
			structureId: sp.has('structure_id') ? parseInt(sp.get('structure_id')!) || null : null,
		};
	}

	function syncUrl(): void {
		const sp = new URLSearchParams();
		if (currentStructureId) sp.set('structure_id', String(currentStructureId));
		if (currentDetected !== 'yes') sp.set('detected', currentDetected);
		if (currentValidation !== 'pending') sp.set('validation', currentValidation);
		if (currentSearch) sp.set('search', currentSearch);
		if (currentSearchMode !== 'contains') sp.set('search_mode', currentSearchMode);
		if (currentPage > 1) sp.set('page', String(currentPage));
		const qs = sp.toString();
		const newUrl = window.location.pathname + (qs ? '?' + qs : '');
		replaceState(newUrl, {});
	}

	// ---- Reactive state ----

	let currentPage = $state(1);
	let currentDetected = $state('yes');
	let currentValidation = $state('pending');
	let currentSearch = $state('');
	let currentSearchMode = $state('contains');
	let currentStructureId = $state<number | null>(null);

	let structures = $state<GroupedStructures>({});
	let stats = $state<Stats>({ total: 0, detected: 0, pending: 0, rejected: 0, confirmed: 0 });
	let addresses = $state<Address[]>([]);
	let totalAddresses = $state(0);
	let totalPages = $state(0);
	let loading = $state(true);
	let requiresSearch = $state(false);

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
		stats = await api<Stats>(`/api/stats?${params}`, { key: 'addr-stats' });
	}

	async function loadAddresses(): Promise<void> {
		syncUrl();
		loading = true;
		const params = new URLSearchParams({
			page: String(currentPage),
			per_page: '200',
			detected: currentDetected,
			validation: currentValidation,
			search: currentSearch,
			search_mode: currentSearchMode
		});
		if (currentStructureId) params.set('structure_id', String(currentStructureId));

		const data = await api<AddressesResponse>(`/api/addresses?${params}`, { key: 'addr-list' });
		requiresSearch = data.requires_search ?? false;
		addresses = data.addresses;
		totalAddresses = data.total;
		totalPages = data.pages;
		selectAll = false;
		selectedIds = new Set();
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
		try {
			const resp = await fetch(`${base}/api/addresses/${addrId}/review`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ structure_id: currentStructureId, is_confirmed: isConfirmed })
			});
			if (!resp.ok) {
				const err = await resp.json().catch(() => ({}));
				alert(`Erreur ${resp.status} : ${err.detail || resp.statusText}`);
				return;
			}
			const result = await resp.json();

			// Mise à jour locale : mettre à jour puis retirer si ne correspond plus au filtre
			const updated = { ...addresses.find((a) => a.id === addrId)!, is_confirmed: result.is_confirmed, is_detected: result.is_detected, structures: result.structures };
			const keep = matchesFilter(updated);
			addresses = keep
				? addresses.map((a) => (a.id === addrId ? updated : a))
				: addresses.filter((a) => a.id !== addrId);
			if (!keep) totalAddresses--;
			loadStats();
		} catch (e: unknown) {
			const msg = e instanceof Error ? e.message : String(e);
			alert('Erreur réseau : ' + msg);
		}
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

	function onFilterChange(): void {
		currentPage = 1;
		loadAddresses();
	}

	function onStructureChange(e: Event): void {
		currentStructureId = parseInt((e.target as HTMLSelectElement).value);
		localStorage.setItem('admin_structure_id', String(currentStructureId));
		currentPage = 1;
		loadStats();
		loadAddresses();
	}

	function goToPage(p: number): void {
		currentPage = p;
		loadAddresses();
		mainPanel?.scrollTo(0, 0);
	}

	function matchesFilter(addr: Address): boolean {
		if (currentDetected === 'yes' && !addr.is_detected) return false;
		if (currentDetected === 'no' && addr.is_detected) return false;
		if (currentValidation === 'pending' && addr.is_confirmed !== null) return false;
		if (currentValidation === 'confirmed' && addr.is_confirmed !== true) return false;
		if (currentValidation === 'rejected' && addr.is_confirmed !== false) return false;
		return true;
	}

	function cardClass(addr: Address): string {
		if (addr.is_confirmed === false) return 'addr-card reviewed-rejected';
		if (addr.is_confirmed === true) return 'addr-card reviewed-confirmed';
		return 'addr-card';
	}

	function structTagClass(s: AddressStructure): string {
		if (s.is_confirmed === true) return 'struct-tag struct-confirmed';
		if (s.is_confirmed === false) return 'struct-tag struct-rejected';
		return 'struct-tag struct-pending';
	}

	// ---- Init ----

	onMount(() => {
		const url = readUrlParams();
		currentDetected = url.detected;
		currentValidation = url.validation;
		currentSearch = url.search;
		currentSearchMode = url.searchMode;
		currentPage = url.p;

		loadStructures().then(() => {
			// Priorité : URL > localStorage > UCA par défaut
			const urlSid = $page.url.searchParams.get('structure_id');
			if (urlSid) {
				currentStructureId = parseInt(urlSid);
				localStorage.setItem('admin_structure_id', urlSid);
			} else {
				const saved = localStorage.getItem('admin_structure_id');
				if (saved) currentStructureId = parseInt(saved);
			}
			loadStats();
			loadAddresses();
		});
	});
</script>

<svelte:head>
	<title>Admin - Adresses - Bibliométrie UCA</title>
</svelte:head>

<div class="page-addresses">
	<!-- Structure selection + feedback button -->
	<div class="structure-bar">
		<span class="structure-label">Structure :</span>
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
		<div class="stats-bar">
			<span class="stat-badge stat-total">{stats.total.toLocaleString('fr-FR')} adresses</span>
			<span class="stat-badge stat-detected">Détectées : {stats.detected}</span>
			<span class="stat-badge stat-pending">Non validées : {stats.pending}</span>
			<span class="stat-badge stat-confirmed">Reliées : {stats.confirmed}</span>
			<span class="stat-badge stat-rejected">Rejetées : {stats.rejected}</span>
		</div>
		{#if currentStructureId}
			<a href="{base}/admin/feedback?structure_id={currentStructureId}" class="btn btn-sm feedback-btn">Qualité de la détection</a>
		{/if}
	</div>

	<!-- Filters -->
	<div class="toolbar">
		<select value={currentSearchMode} onchange={onSearchModeChange}>
			<option value="contains">contient</option>
			<option value="not_contains">ne contient pas</option>
		</select>

		<input
			type="text"
			class="search-input"
			placeholder="Rechercher dans les adresses..."
			autocomplete="off"
			value={currentSearch}
			oninput={onSearchInput}
		/>

		<select
			value={currentDetected}
			onchange={(e) => { currentDetected = (e.target as HTMLSelectElement).value; onFilterChange(); }}
		>
			<option value="all">Détection : tous</option>
			<option value="yes">Détecté</option>
			<option value="no">Non détecté</option>
		</select>

		<select
			value={currentValidation}
			onchange={(e) => { currentValidation = (e.target as HTMLSelectElement).value; onFilterChange(); }}
		>
			<option value="all">Validation : tous</option>
			<option value="pending">Non validé</option>
			<option value="confirmed">Relié</option>
			<option value="rejected">Rejeté</option>
		</select>

		<span class="count">{resultCountText}</span>
	</div>

	<!-- Batch action bar -->
	{#if selectedCount > 0}
		<div class="batch-bar">
			<span>{selectedCount} sélectionnée{selectedCount > 1 ? 's' : ''}</span>
			<div class="batch-actions">
				<button onclick={() => batchReview(false)}>&#x2717; Rejeter</button>
				<button onclick={() => batchReview(true)}>&#x2713; Relier</button>
				<button onclick={() => batchReview(null)}>&#x21BA; Reset</button>
				<button onclick={clearSelection}>Annuler</button>
			</div>
		</div>
	{/if}

	<!-- Address list -->
	<div class="main-panel" bind:this={mainPanel}>
		{#if loading}
			<div class="loading-msg">Chargement...</div>
		{:else if requiresSearch}
			<div class="loading-msg">Saisissez un terme de recherche pour afficher les résultats.</div>
		{:else if addresses.length === 0}
			<div class="loading-msg">Aucune adresse trouvée.</div>
		{:else}
			<div class="select-all-row">
				<label class="select-all-label">
					<input
						type="checkbox"
						checked={selectAll}
						onchange={(e) => toggleSelectAll((e.target as HTMLInputElement).checked)}
					/>
					Tout sélectionner
				</label>
			</div>
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
									<span class={structTagClass(s)}>{@html esc(s.acronym || s.name)}</span>
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
								class="btn btn-danger"
								title="Rejeter le lien"
								onclick={() => reviewAddr(addr.id, false)}>&#x2717;</button
							>
							<button
								class="btn btn-confirm"
								title="Relier à la structure"
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
								<div class="detail-loading">Aucune publication liée.</div>
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
		--warning: #c68a19;
		--warning-light: #fef5e0;
		--highlight: #fff3b0;
	}

	/* Stats bar */
	.structure-bar {
		display: flex;
		align-items: center;
		gap: 12px;
		margin-bottom: 10px;
		padding: 8px 12px;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
		flex-wrap: wrap;
	}
	.structure-label {
		font-weight: 600;
		font-size: 0.9rem;
		color: var(--muted);
	}
	.stats-bar {
		display: flex;
		gap: 8px;
		font-size: 0.85rem;
		flex: 1;
	}
	.feedback-btn {
		margin-left: auto;
		white-space: nowrap;
	}
	.stat-badge {
		padding: 3px 10px;
		border-radius: 12px;
		font-weight: 500;
	}
	.stat-total {
		background: #f0f0ee;
		color: #666;
	}
	.stat-detected {
		background: var(--accent-light);
		color: var(--accent);
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
	.toolbar input[type='text'],
	.toolbar select { background: white; }
	.search-input { width: 250px; }
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
	.select-all-row {
		padding: 4px 12px;
	}
	.select-all-label {
		font-size: 0.85rem;
		display: flex;
		align-items: center;
		gap: 4px;
		cursor: pointer;
		color: var(--muted);
	}

	/* Main panel */
	.main-panel {
		overflow-y: auto;
		max-height: calc(100vh - 240px);
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
		font-size: 0.95rem;
		word-break: break-word;
	}
	.addr-meta {
		display: flex;
		gap: 6px;
		margin-top: 4px;
		font-size: 0.8rem;
		color: var(--muted);
		flex-wrap: wrap;
	}
	.pub-count-tag {
		display: inline-block;
		font-size: 0.8rem;
		padding: 1px 7px;
		border-radius: 10px;
		background: var(--accent-light);
		color: var(--accent);
		font-weight: 500;
	}
	.struct-tag {
		display: inline-block;
		font-size: 0.8rem;
		padding: 1px 7px;
		border-radius: 10px;
		font-weight: 500;
	}
	.struct-confirmed {
		background: var(--success-light);
		color: var(--success);
	}
	.struct-pending {
		background: var(--warning-light);
		color: var(--warning);
	}
	.struct-rejected {
		background: #f0f0ee;
		color: #999;
		text-decoration: line-through;
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
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--muted);
		margin: 8px 0 4px 0;
		text-transform: uppercase;
		letter-spacing: 0.5px;
	}

	.pub-row {
		padding: 5px 0;
		border-bottom: 1px solid #f0f0ee;
		font-size: 0.85rem;
	}
	.pub-row:last-child {
		border-bottom: none;
	}
	.pub-title-link {
		font-weight: 500;
		color: var(--text);
	}
	.pub-meta-inline {
		font-size: 0.8rem;
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

	/* Buttons (page-specific) */
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
		font-size: 0.85rem;
		cursor: pointer;
		font-family: inherit;
	}
	.batch-bar button:hover {
		background: rgba(255, 255, 255, 0.15);
	}

</style>
