<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { page } from '$app/stores';
	import { replaceState } from '$app/navigation';
	import { addresses as addressesApi, api, ApiError } from '$lib/api';
	import { esc, sanitizeTitle } from '$lib/utils';
	import { toast } from '$lib/dialogs.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import { autofocus } from '$lib/actions/focus';

	// ---- Type definitions ----

	import type { components } from '$lib/api/schema';
	type Stats = components['schemas']['AddressStatsResponse'];
	type AddressStructure = components['schemas']['AddressStructureSummary'];
	type Address = components['schemas']['AddressOut'];
	type AddressesResponse = components['schemas']['AddressListResponse'];
	type Publication = components['schemas']['AddressPublicationItem'];
	type PublicationsResponse = components['schemas']['AddressPublicationsResponse'];

	// Structure : forme propre au front (utilisée par le picker de
	// structure pour assigner manuellement). Côté API, l'endpoint qui
	// liste les structures cibles est dans le router structures, pas
	// addresses — type local conservé.
	interface Structure {
		id: number;
		name: string;
		acronym: string | null;
		code: string | null;
		type: string;
	}

	interface GroupedStructures {
		[type: string]: Structure[];
	}

	// Prédicats composables (cf. chantier filtres-adresses-composables).
	interface TextPredicate {
		mode: 'contains' | 'not_contains';
		term: string;
	}
	interface StructurePredicate {
		operator: 'recognized' | 'not_recognized';
		structureIds: number[];
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

	function parseTextParam(raw: string): TextPredicate | null {
		const i = raw.indexOf(':');
		if (i < 0) return null;
		const mode = raw.slice(0, i);
		const term = raw.slice(i + 1);
		if ((mode === 'contains' || mode === 'not_contains') && term) return { mode, term };
		return null;
	}

	function parseStructParam(raw: string): StructurePredicate | null {
		const i = raw.indexOf(':');
		if (i < 0) return null;
		const operator = raw.slice(0, i);
		if (operator !== 'recognized' && operator !== 'not_recognized') return null;
		const ids = raw
			.slice(i + 1)
			.split(',')
			.map((x) => parseInt(x))
			.filter((n) => !isNaN(n));
		if (!ids.length) return null;
		return { operator, structureIds: ids };
	}

	function readUrlParams(): {
		detected: string;
		validation: string;
		textPredicates: TextPredicate[];
		structurePredicates: StructurePredicate[];
		p: number;
		structureId: number | null;
	} {
		const sp = $page.url.searchParams;
		return {
			detected: sp.get('detected') || 'yes',
			validation: sp.get('validation') || 'pending',
			textPredicates: sp.getAll('text').map(parseTextParam).filter((p): p is TextPredicate => p !== null),
			structurePredicates: sp
				.getAll('struct')
				.map(parseStructParam)
				.filter((p): p is StructurePredicate => p !== null),
			p: parseInt(sp.get('page') || '1') || 1,
			structureId: sp.has('structure_id') ? parseInt(sp.get('structure_id')!) || null : null,
		};
	}

	function serializePredicateParams(sp: URLSearchParams): void {
		for (const t of textPredicates) if (t.term) sp.append('text', `${t.mode}:${t.term}`);
		for (const s of structurePredicates)
			if (s.structureIds.length) sp.append('struct', `${s.operator}:${s.structureIds.join(',')}`);
	}

	function syncUrl(): void {
		const sp = new URLSearchParams();
		if (currentStructureId) sp.set('structure_id', String(currentStructureId));
		if (currentDetected !== 'yes') sp.set('detected', currentDetected);
		if (currentValidation !== 'pending') sp.set('validation', currentValidation);
		serializePredicateParams(sp);
		if (currentPage > 1) sp.set('page', String(currentPage));
		const qs = sp.toString();
		const newUrl = window.location.pathname + (qs ? '?' + qs : '');
		replaceState(newUrl, {});
	}

	// ---- Reactive state ----

	let currentPage = $state(1);
	let currentDetected = $state('yes');
	let currentValidation = $state('pending');
	const newTextPredicate = (): TextPredicate => ({ mode: 'contains', term: '' });
	let textPredicates = $state<TextPredicate[]>([newTextPredicate()]);
	let structurePredicates = $state<StructurePredicate[]>([]);
	let currentStructureId = $state<number | null>(null);

	let structures = $state<GroupedStructures>({});
	// Liste plate de toutes les structures (hors `site`) pour le picker des
	// prédicats Structure — distincte du scope (limité aux ALLOWED_TYPES).
	let allStructures = $state<Structure[]>([]);
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

	// Libellé d'une structure par id (pour les tags des prédicats).
	const structureLabelById = $derived(
		new Map(allStructures.map((s) => [s.id, s.acronym || s.name]))
	);
	const currentStructureName = $derived(
		(currentStructureId !== null && structureLabelById.get(currentStructureId)) || '—'
	);
	// Dédup global : une structure déjà posée dans un prédicat disparaît de tous les pickers.
	const usedStructureIds = $derived(
		new Set(structurePredicates.flatMap((s) => s.structureIds))
	);
	// Structures sélectionnables, groupées par type, ALLOWED_TYPES d'abord.
	const availableStructureGroups = $derived.by((): [string, Structure[]][] => {
		const groups = new Map<string, Structure[]>();
		for (const s of allStructures) {
			if (usedStructureIds.has(s.id)) continue;
			(groups.get(s.type) ?? groups.set(s.type, []).get(s.type)!).push(s);
		}
		const extra = [...groups.keys()].filter((t) => !ALLOWED_TYPES.includes(t));
		return [...ALLOWED_TYPES, ...extra]
			.filter((t) => groups.has(t))
			.map((t) => [t, groups.get(t)!]);
	});

	function reload(): void {
		currentPage = 1;
		loadAddresses();
	}

	// ---- Data loading ----

	async function loadStructures(): Promise<void> {
		const all = await api<Structure[]>('/api/structures');
		allStructures = all.filter((s) => s.type !== 'site');
		const grouped: GroupedStructures = {};
		for (const s of all) {
			if (!ALLOWED_TYPES.includes(s.type)) continue;
			if (!grouped[s.type]) grouped[s.type] = [];
			grouped[s.type].push(s);
		}
		structures = grouped;
	}

	/** Structure de scope par défaut : UCA, sinon la première du premier type peuplé. */
	function defaultStructureId(): number | null {
		const uca = allStructures.find((s) => s.code === 'uca');
		if (uca) return uca.id;
		for (const type of ALLOWED_TYPES) {
			if (structures[type]?.length) return structures[type][0].id;
		}
		return null;
	}

	/** Résout la structure de scope : URL > localStorage (si valides) > défaut. Une seule assignation, pas de passage transitoire par le défaut. */
	function resolveScopeStructure(): void {
		const candidate = $page.url.searchParams.get('structure_id') ?? localStorage.getItem('admin_structure_id');
		const id = candidate ? parseInt(candidate) : NaN;
		const isScope = !isNaN(id) && Object.values(structures).some((list) => list.some((s) => s.id === id));
		currentStructureId = isScope ? id : defaultStructureId();
		if (currentStructureId) localStorage.setItem('admin_structure_id', String(currentStructureId));
	}

	async function loadStats(): Promise<void> {
		const params = new URLSearchParams();
		if (currentStructureId) params.set('structure_id', String(currentStructureId));
		stats = await api<Stats>(`/api/addresses/stats?${params}`, { key: 'addr-stats' });
	}

	async function loadAddresses(): Promise<void> {
		syncUrl();
		loading = true;
		const params = new URLSearchParams({
			page: String(currentPage),
			per_page: '200',
			detected: currentDetected,
			validation: currentValidation
		});
		if (currentStructureId) params.set('structure_id', String(currentStructureId));
		serializePredicateParams(params);

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
			const result = await addressesApi.review(addrId, {
				structure_id: currentStructureId,
				is_confirmed: isConfirmed
			}) as { is_confirmed: boolean; is_detected: boolean; structures: AddressStructure[] };

			// Mise à jour locale : mettre à jour puis retirer si ne correspond plus au filtre
			const updated = { ...addresses.find((a) => a.id === addrId)!, is_confirmed: result.is_confirmed, is_detected: result.is_detected, structures: result.structures };
			const keep = matchesFilter(updated);
			addresses = keep
				? addresses.map((a) => (a.id === addrId ? updated : a))
				: addresses.filter((a) => a.id !== addrId);
			if (!keep) totalAddresses--;
			loadStats();
		} catch (e: unknown) {
			if (e instanceof ApiError) {
				const detail = (e.detail as { detail?: string })?.detail;
				toast(`Erreur ${e.status} : ${detail || 'inconnue'}`, 'error');
				return;
			}
			const msg = e instanceof Error ? e.message : String(e);
			toast('Erreur réseau : ' + msg, 'error');
		}
	}

	async function batchReview(isConfirmed: boolean | null): Promise<void> {
		const ids = Array.from(selectedIds);
		await addressesApi.batchReview({
			address_ids: ids,
			structure_id: currentStructureId,
			is_confirmed: isConfirmed
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

	// ---- Prédicats composables ----

	function addTextPredicate(): void {
		textPredicates = [...textPredicates, newTextPredicate()];
	}

	function addStructurePredicate(): void {
		structurePredicates = [...structurePredicates, { operator: 'recognized', structureIds: [] }];
	}

	function removeTextPredicate(i: number): void {
		const had = !!textPredicates[i]?.term;
		textPredicates = textPredicates.filter((_, j) => j !== i);
		if (had) reload();
	}

	function removeStructurePredicate(i: number): void {
		const had = (structurePredicates[i]?.structureIds.length ?? 0) > 0;
		structurePredicates = structurePredicates.filter((_, j) => j !== i);
		if (had) reload();
	}

	function setTextMode(i: number, mode: string): void {
		textPredicates = textPredicates.map((t, j) =>
			j === i ? { ...t, mode: mode as TextPredicate['mode'] } : t
		);
		if (textPredicates[i].term) reload();
	}

	function onTextTermInput(i: number, value: string): void {
		textPredicates = textPredicates.map((t, j) => (j === i ? { ...t, term: value } : t));
		if (searchTimeout) clearTimeout(searchTimeout);
		searchTimeout = setTimeout(reload, 400);
	}

	function setStructureOperator(i: number, operator: string): void {
		structurePredicates = structurePredicates.map((s, j) =>
			j === i ? { ...s, operator: operator as StructurePredicate['operator'] } : s
		);
		if (structurePredicates[i].structureIds.length) reload();
	}

	function addStructureToPredicate(i: number, id: number): void {
		if (!id || isNaN(id)) return;
		structurePredicates = structurePredicates.map((s, j) =>
			j === i && !s.structureIds.includes(id)
				? { ...s, structureIds: [...s.structureIds, id] }
				: s
		);
		reload();
	}

	function removeStructureFromPredicate(i: number, id: number): void {
		structurePredicates = structurePredicates.map((s, j) =>
			j === i ? { ...s, structureIds: s.structureIds.filter((x) => x !== id) } : s
		);
		reload();
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
		textPredicates = url.textPredicates.length ? url.textPredicates : [newTextPredicate()];
		structurePredicates = url.structurePredicates;
		currentPage = url.p;

		loadStructures().then(() => {
			resolveScopeStructure();
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

	<!-- Filtres composables -->
	<div class="filters-zone">
		<!-- Ligne fixe : détection/validation de la structure étudiée -->
		<div class="filters-row scope-row">
			<span class="filters-title">Filtres</span>
			<span class="scope-echo">Structure étudiée : <strong>{currentStructureName}</strong></span>
			<label class="scope-field">
				Détection
				<select
					value={currentDetected}
					onchange={(e) => { currentDetected = (e.target as HTMLSelectElement).value; onFilterChange(); }}
				>
					<option value="all">tous</option>
					<option value="yes">détecté</option>
					<option value="no">non détecté</option>
				</select>
			</label>
			<label class="scope-field">
				Validation
				<select
					value={currentValidation}
					onchange={(e) => { currentValidation = (e.target as HTMLSelectElement).value; onFilterChange(); }}
				>
					<option value="all">tous</option>
					<option value="pending">non validé</option>
					<option value="confirmed">relié</option>
					<option value="rejected">rejeté</option>
				</select>
			</label>
			<span class="count">{resultCountText}</span>
		</div>

		<!-- Prédicats texte -->
		{#each textPredicates as tp, i (i)}
			<div class="filters-row predicate-row">
				<span class="pred-type">Texte</span>
				<select value={tp.mode} onchange={(e) => setTextMode(i, (e.target as HTMLSelectElement).value)}>
					<option value="contains">contient</option>
					<option value="not_contains">ne contient pas</option>
				</select>
				<input
					type="search"
					class="pred-text"
					placeholder="texte recherché…"
					autocomplete="off"
					value={tp.term}
					use:autofocus
					onkeydown={(e) => { if (e.key === 'Escape') { onTextTermInput(i, ''); } }}
					oninput={(e) => onTextTermInput(i, (e.target as HTMLInputElement).value)}
				/>
				<button class="pred-remove" title="Retirer ce filtre" onclick={() => removeTextPredicate(i)}>&#x2717;</button>
			</div>
		{/each}

		<!-- Prédicats structure reconnue (multi-structures, OR / aucune) -->
		{#each structurePredicates as sp, i (i)}
			<div class="filters-row predicate-row">
				<span class="pred-type">Structure</span>
				<select value={sp.operator} onchange={(e) => setStructureOperator(i, (e.target as HTMLSelectElement).value)}>
					<option value="recognized">reconnue comme l'une de</option>
					<option value="not_recognized">non reconnue comme aucune de</option>
				</select>
				<div class="struct-tags">
					{#each sp.structureIds as sid (sid)}
						<span class="struct-chip">
							{structureLabelById.get(sid) || `#${sid}`}
							<button title="Retirer" onclick={() => removeStructureFromPredicate(i, sid)}>&#x2717;</button>
						</span>
					{/each}
					<select
						class="struct-add"
						value=""
						onchange={(e) => {
							const el = e.target as HTMLSelectElement;
							addStructureToPredicate(i, parseInt(el.value));
							el.value = '';
						}}
					>
						<option value="" disabled selected>+ structure</option>
						{#each availableStructureGroups as [type, list] (type)}
							<optgroup label={TYPE_LABELS[type] || type}>
								{#each list as s (s.id)}
									<option value={s.id}>{s.acronym || s.name}</option>
								{/each}
							</optgroup>
						{/each}
					</select>
				</div>
				<button class="pred-remove" title="Retirer cette ligne" onclick={() => removeStructurePredicate(i)}>&#x2717;</button>
			</div>
		{/each}

		<!-- Ajout de prédicats -->
		<div class="filters-row add-row">
			<button class="add-btn" onclick={addTextPredicate}>+ Texte</button>
			<button class="add-btn" onclick={addStructurePredicate}>+ Structure reconnue</button>
		</div>
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
			<div class="loading-msg">Chargement…</div>
		{:else if requiresSearch}
			<div class="loading-msg">Ajoutez un filtre (texte ou structure) pour afficher les résultats.</div>
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
							{#if addr.is_confirmed !== false}
								<button class="btn btn-sm btn-danger-outline" title="Rejeter le lien" onclick={() => reviewAddr(addr.id, false)}>&#x2717;</button>
							{/if}
							{#if addr.is_confirmed !== true}
								<button class="btn btn-sm btn-confirm-outline" title="Relier à la structure" onclick={() => reviewAddr(addr.id, true)}>&#x2713;</button>
							{/if}
							{#if addr.is_confirmed !== null}
								<button class="btn btn-sm btn-reset" title="Reset" onclick={() => reviewAddr(addr.id, null)}>&#x21BA;</button>
							{/if}
						</div>
					</div>

					{#if expandedId === addr.id}
						<div class="addr-detail">
							{#if pubsLoading}
								<div class="detail-loading">Chargement…</div>
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

	.structure-filter {
		padding: 6px 10px;
		border: 1px solid var(--accent);
		border-radius: 4px;
		font-size: 0.95rem;
		font-family: inherit;
		background: white;
		font-weight: 600;
		color: var(--accent);
	}

	/* Filtres composables */
	.filters-zone {
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--card);
		padding: 8px 12px;
		margin-bottom: 10px;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.filters-zone select {
		padding: 6px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 0.95rem;
		font-family: inherit;
		background: white;
	}
	.filters-row {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.scope-row {
		padding-bottom: 6px;
		border-bottom: 1px solid var(--border);
	}
	.filters-title {
		font-weight: 600;
		color: var(--muted);
		text-transform: uppercase;
		font-size: 0.75rem;
		letter-spacing: 0.5px;
	}
	.scope-echo {
		font-size: 0.85rem;
		color: var(--muted);
	}
	.scope-field {
		font-size: 0.8rem;
		color: var(--muted);
		display: flex;
		align-items: center;
		gap: 4px;
	}
	.count {
		margin-left: auto;
		font-size: 0.85rem;
		color: var(--muted);
	}
	.pred-type {
		font-size: 0.75rem;
		font-weight: 600;
		color: var(--muted);
		min-width: 64px;
	}
	.pred-text {
		flex: 1;
		min-width: 180px;
	}
	.struct-tags {
		display: flex;
		align-items: center;
		gap: 4px;
		flex-wrap: wrap;
		flex: 1;
	}
	.struct-chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 0.8rem;
		padding: 2px 4px 2px 8px;
		border-radius: 10px;
		background: var(--accent-light);
		color: var(--accent);
		font-weight: 500;
	}
	.struct-chip button {
		border: none;
		background: none;
		color: inherit;
		cursor: pointer;
		font-size: 0.75rem;
		padding: 0 2px;
		line-height: 1;
	}
	.struct-chip button:hover {
		color: var(--danger);
	}
	.struct-add {
		font-size: 0.85rem;
	}
	.pred-remove {
		border: 1px solid var(--border);
		background: white;
		color: var(--muted);
		border-radius: 4px;
		cursor: pointer;
		padding: 2px 7px;
		line-height: 1;
	}
	.pred-remove:hover {
		border-color: var(--danger);
		color: var(--danger);
	}
	.add-row {
		gap: 6px;
	}
	.add-btn {
		border: 1px dashed var(--border);
		background: white;
		color: var(--accent);
		border-radius: 4px;
		cursor: pointer;
		padding: 3px 10px;
		font-size: 0.85rem;
		font-family: inherit;
	}
	.add-btn:hover {
		border-color: var(--accent);
		background: var(--accent-light);
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
		background: var(--surface-hover);
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
