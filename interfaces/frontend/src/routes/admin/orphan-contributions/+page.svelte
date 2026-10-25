<script lang="ts">
	import { institution } from '#lib/institution.svelte.js';
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { replaceState } from '$app/navigation';
	import { api, ApiError, orphanContributions } from '#lib/api/index.js';
	import { useDebouncedSearch } from '#lib/composables/useDebouncedSearch.svelte.js';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import { titleCase } from '#lib/utils.js';
	import { autofocus } from '#lib/actions/focus.js';
	import { anchored } from '#lib/actions/anchored.js';
	import Pagination from '#lib/components/Pagination.svelte';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import Modal from '#lib/components/Modal.svelte';
	import FacetDropdown from '#lib/components/FacetDropdown.svelte';
	import type { FacetOption } from '#lib/components/FacetDropdown.svelte';
	import type { components } from '#lib/api/schema.js';

	type PersonResult = components['schemas']['PersonSearchResult'];
	type OrphanContribution = components['schemas']['OrphanContributionOut'];
	type RejectedPair = components['schemas']['RejectedPairItem'];
	type OrphanFacets = components['schemas']['OrphanContributionsFacetsResponse'];

	async function searchPersons(
		q: string,
		request: <T>(url: string) => Promise<T>,
	): Promise<PersonResult[]> {
		return request<PersonResult[]>(`/api/persons/search?search=${encodeURIComponent(q)}`);
	}

	let search = $state('');
	let selectedLabs: string[] = $state([]);
	let labOptions: FacetOption[] = $state([]);

	function filterParams(): URLSearchParams {
		const params = new URLSearchParams();
		if (search.trim()) params.set('search', search.trim());
		if (selectedLabs.length) params.set('lab_id', selectedLabs.join(','));
		return params;
	}

	const list = usePaginatedFetch<OrphanContribution>({
		endpoint: '/api/contributions/orphans',
		itemsKey: 'contributions',
		apiKey: 'orphans',
		buildParams: filterParams,
	});

	async function loadFacets() {
		const data = await api<OrphanFacets>('/api/contributions/orphans/facets?' + filterParams(), {
			key: 'orphans-facets',
		});
		labOptions = [
			{ value: 'none', text: '— Aucun labo —', count: data.no_lab_count },
			...data.labs.map((l) => ({ value: l.value, text: l.label ?? l.value, count: l.count })),
		];
	}

	function onLabsChange() {
		list.page = 1;
		syncUrl();
		list.load();
	}

	/** Recharge la liste et la facette après une attribution, qui retire des contributions de la file. */
	function reload() {
		list.load();
		loadFacets();
	}
	const orphans = $derived(list.items);
	// Une seule ligne peut avoir son panneau "attribuer" ouvert à la fois.
	let activeAssignIdx: number | null = $state(null);
	const assignSearch = useDebouncedSearch<PersonResult>({ search: searchPersons });
	let selectedIds = $state(new Set<number>());  // `contribution_id` des contributions sélectionnées
	const batchSearch = useDebouncedSearch<PersonResult>({ search: searchPersons });
	const allSelected = $derived(orphans.length > 0 && orphans.every(o => selectedIds.has(o.contribution_id)));
	let createModal: { lastName: string; firstName: string; items: OrphanContribution[] } | null = $state(null);
	// Modale de confirmation quand la réassignation porte sur une paire déjà rejetée (409).
	let rejectModal: { detail: string; pairs: RejectedPair[]; retry: () => Promise<void> } | null =
		$state(null);

	/**
	 * Exécute une réassignation en interceptant le 409 « paire déjà rejetée » : ouvre la modale de confirmation avec une closure qui rejoue l'opération en `force=true` (lève le rejet puis réassigne). Les autres erreurs remontent normalement.
	 */
	async function withRejectGuard(run: (force: boolean) => Promise<void>) {
		try {
			await run(false);
		} catch (e) {
			if (e instanceof ApiError && e.status === 409) {
				const body = e.detail as Partial<components['schemas']['RejectedPairsResponse']>;
				if (body?.rejected_pairs?.length) {
					rejectModal = { detail: body.detail ?? '', pairs: body.rejected_pairs, retry: () => run(true) };
					return;
				}
			}
			throw e;
		}
	}

	async function confirmReassign() {
		if (!rejectModal) return;
		const retry = rejectModal.retry;
		rejectModal = null;
		await retry();
	}

	const SOURCE_LABELS: Record<string, string> = {
		hal: 'HAL',
		openalex: 'OA',
		wos: 'WoS',
		theses: 'Thèses',
		scanr: 'ScanR',
		crossref: 'CrossRef',
		datacite: 'DataCite',
	};

	function openAssign(idx: number) {
		activeAssignIdx = idx;
		assignSearch.clear();
	}

	function closeAssign() {
		activeAssignIdx = null;
		assignSearch.clear();
	}

	async function assign(orphan: OrphanContribution, personId: number) {
		await withRejectGuard(async (force) => {
			await orphanContributions.assign({
				contribution_id: orphan.contribution_id,
				person_id: personId,
				force,
			});
			closeAssign();
			reload();
		});
	}

	function createAndAssign(orphan: OrphanContribution) {
		createModal = {
			lastName: orphan.last_name || orphan.full_name,
			firstName: orphan.first_name,
			items: [orphan],
		};
		closeAssign();
	}

	function toggleSelect(o: OrphanContribution) {
		const s = new Set(selectedIds);
		if (s.has(o.contribution_id)) s.delete(o.contribution_id); else s.add(o.contribution_id);
		selectedIds = s;
	}

	function toggleAll() {
		if (allSelected) {
			selectedIds = new Set();
		} else {
			selectedIds = new Set(orphans.map(o => o.contribution_id));
		}
	}

	async function batchAssign(personId: number) {
		const items = orphans.filter(o => selectedIds.has(o.contribution_id));
		await withRejectGuard(async (force) => {
			await orphanContributions.batchAssign({
				person_id: personId,
				group_ids: items.map(o => o.contribution_id),
				force,
			});
			selectedIds = new Set();
			batchSearch.clear();
			reload();
		});
	}

	function openCreateModal() {
		const items = orphans.filter(o => selectedIds.has(o.contribution_id));
		if (!items.length) return;
		const first = items[0];
		createModal = {
			lastName: first.last_name || first.full_name,
			firstName: first.first_name,
			items,
		};
	}

	async function confirmCreate() {
		if (!createModal) return;
		const { lastName, firstName, items } = createModal;
		// Créer la personne avec la première contribution
		const data = await orphanContributions.assign({
			contribution_id: items[0].contribution_id,
			create_person: { last_name: lastName, first_name: firstName },
		}) as { person_id?: number };
		if (!data.person_id) return;
		// Attribuer le reste
		const remaining = items.slice(1);
		if (remaining.length) {
			await orphanContributions.batchAssign({
				person_id: data.person_id,
				group_ids: remaining.map(o => o.contribution_id),
			});
		}
		createModal = null;
		selectedIds = new Set();
		batchSearch.clear();
		reload();
	}

	function syncUrl() {
		const p = new URLSearchParams();
		if (list.page > 1) p.set('page', String(list.page));
		if (search.trim()) p.set('search', search.trim());
		if (selectedLabs.length) p.set('lab', selectedLabs.join(','));
		const qs = p.toString();
		replaceState(resolve('admin/orphan-contributions') + (qs ? '?' + qs : ''), {});
	}

	let debounceTimer: ReturnType<typeof setTimeout>;
	function onSearchInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => { list.page = 1; syncUrl(); list.load(); loadFacets(); }, 400);
	}

	onMount(() => {
		const params = new URLSearchParams(window.location.search);
		if (params.get('page')) list.page = parseInt(params.get('page')!) || 1;
		if (params.get('search')) search = params.get('search')!;
		if (params.get('lab')) selectedLabs = params.get('lab')!.split(',');
		list.load();
		loadFacets();
	});
</script>

<svelte:head>
	<title>Contributions orphelines — Admin</title>
</svelte:head>

<div class="header">
	<h1>Contributions orphelines ({list.total})</h1>
	<a href={resolve('admin/persons')} class="btn">← Retour aux personnes</a>
</div>

<div class="info-box">
	Contributions {institution.name} non reliées à une personne. Pour chaque contribution, vous pouvez l'attribuer à une personne existante ou créer une nouvelle personne.
</div>

<div class="toolbar">
	<input type="search" placeholder="Filtrer par nom…" bind:value={search}
		use:autofocus onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onSearchInput(); } }}
		oninput={onSearchInput} autocomplete="off" />
	<FacetDropdown
		label="Laboratoires"
		options={labOptions}
		searchable
		bind:selected={selectedLabs}
		onchange={onLabsChange}
	/>
</div>

{#if selectedIds.size > 0}
	<div class="batch-bar">
		<span>{selectedIds.size} sélectionnée{selectedIds.size > 1 ? 's' : ''}</span>
		<input type="search" placeholder="Attribuer à une personne existante…" value={batchSearch.query}
			onkeydown={(e) => { if (e.key === 'Escape') { batchSearch.setQuery(''); } }}
			oninput={(e) => batchSearch.setQuery((e.target as HTMLInputElement).value)} autocomplete="off" />
		<button class="btn btn-sm btn-create" onclick={openCreateModal}>Créer une personne</button>
		{#if batchSearch.loading}
			<span class="loading-text">…</span>
		{:else if batchSearch.results.length}
			<div class="batch-results" use:anchored>
				{#each batchSearch.results as r (r.id)}
					<button class="result-btn" onclick={() => batchAssign(r.id)}>
						<strong>{titleCase(r.last_name)}</strong> {titleCase(r.first_name)}
						{#if r.has_rh}<span class="rh-check">✓</span>{/if}
						<span class="result-hint">{r.department_name || `#${r.id}`}</span>
					</button>
				{/each}
			</div>
		{/if}
	</div>
{/if}

{#if orphans.length === 0}
	{#if list.loading}
		<p class="loading-msg">Chargement des résultats en cours…</p>
	{:else}
		<p class="empty">Aucune contribution orpheline{search.trim() || selectedLabs.length ? ' pour ce filtre' : ''}.</p>
	{/if}
{:else}
	<table class="data-table">
		<thead>
			<tr>
				<th style="width:30px"><input type="checkbox" checked={allSelected} onchange={toggleAll} /></th>
				<th>Source</th>
				<th>Nom</th>
				<th>Publication</th>
				<th>Labo(s)</th>
				<th>Action</th>
			</tr>
		</thead>
		<tbody>
			{#each orphans as o, i (o.contribution_id)}
				<tr>
					<td><input type="checkbox" checked={selectedIds.has(o.contribution_id)} onchange={() => toggleSelect(o)} /></td>
					<td>
						{#each o.sources as source (source)}
							<span class="tag tag-source">{SOURCE_LABELS[source] ?? source}</span>
						{/each}
					</td>
					<td>{o.full_name}</td>
					<td>
						<a href={resolve(`publications/${o.publication_id}`)} class="publication-link">
							{o.publication_year ?? '?'} — <span class="publication-title"><PublicationTitle titre={o.publication_title} /></span>
						</a>
					</td>
					<td>
						{#each o.labs as lab (lab.id)}
							<a href={resolve(`laboratories/${lab.id}`)} class="lab-tag">{lab.label}</a>
						{/each}
					</td>
					<td>
						{#if activeAssignIdx === i}
							<div class="assign-panel">
								<div class="assign-row">
									<input type="search" placeholder="Nom de la personne…" value={assignSearch.query}
											use:autofocus onkeydown={(e) => { if (e.key === 'Escape') { closeAssign(); } }}
										oninput={(e) => assignSearch.setQuery((e.target as HTMLInputElement).value)} />
									<button class="btn btn-sm" onclick={closeAssign}>&times;</button>
								</div>
								{#if assignSearch.loading}
									<span class="loading-text">…</span>
								{:else if assignSearch.results.length}
									<div class="assign-results" use:anchored>
										{#each assignSearch.results as r (r.id)}
											<button class="result-btn" onclick={() => assign(o, r.id)}>
												<strong>{titleCase(r.last_name)}</strong> {titleCase(r.first_name)}
												{#if r.has_rh}<span class="rh-check">✓</span>{/if}
												<span class="result-hint">{r.department_name || `#${r.id}`}</span>
											</button>
										{/each}
									</div>
								{:else if assignSearch.query.length >= 2}
									<div class="assign-results" use:anchored>
										<span class="loading-text">Aucun résultat</span>
										<button class="btn btn-sm btn-create" onclick={() => createAndAssign(o)}>Créer « {o.full_name} »</button>
									</div>
								{/if}
							</div>
						{:else}
							<button class="btn btn-sm" onclick={() => openAssign(i)}>Attribuer…</button>
						{/if}
					</td>
				</tr>
			{/each}
		</tbody>
	</table>

	<Pagination page={list.page} pages={list.pages} onchange={(p) => { list.goToPage(p); syncUrl(); }} />
{/if}

{#if createModal}
	<Modal
		title={`Créer une personne (${createModal.items.length} contribution${createModal.items.length > 1 ? 's' : ''})`}
		maxWidth="440px"
		onclose={() => { createModal = null; }}
		onsubmit={confirmCreate}
	>
		<div class="create-form">
			<label>
				Nom
				<input type="text" bind:value={createModal.lastName} />
			</label>
			<label>
				Prénom
				<input type="text" bind:value={createModal.firstName} />
			</label>
		</div>
		{#snippet actions()}
			<button class="btn" onclick={() => { createModal = null; }}>Annuler</button>
			<button class="btn btn-confirm" onclick={confirmCreate}>Créer et attribuer</button>
		{/snippet}
	</Modal>
{/if}

{#if rejectModal}
	<Modal title="Réassignation déjà rejetée" onclose={() => { rejectModal = null; }}>
			<p class="reject-detail">{rejectModal.detail}</p>
			<p class="reject-muted">
				Cette personne a été détachée de {rejectModal.pairs.length > 1 ? 'ces publications' : 'cette publication'} manuellement.
				Confirmer lèvera le rejet et recréera le lien.
			</p>
			<ul class="reject-list">
				{#each rejectModal.pairs as p (p.publication_id)}
					<li>
						<a href={resolve(`publications/${p.publication_id}`)} target="_blank" rel="noopener">
							Publication #{p.publication_id}
						</a>
						<span class="reject-muted">— rejetée le {new Date(p.rejected_at).toLocaleDateString('fr-FR')}</span>
					</li>
				{/each}
			</ul>
			{#snippet actions()}
				<button class="btn" onclick={() => { rejectModal = null; }}>Annuler</button>
				<button class="btn btn-confirm" onclick={confirmReassign}>Réassigner quand même</button>
			{/snippet}
	</Modal>
{/if}

<style>
	.header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
	.header h1 { margin: 0; font-size: 1.2rem; }
	.info-box {
		background: var(--warning-light); border: 1px solid color-mix(in srgb, var(--warning) 40%, white); border-radius: 6px;
		padding: 10px 14px; font-size: 0.85rem; color: var(--warning-text); margin-bottom: 14px;
	}
	.toolbar input { width: 300px; }
	.tag-source { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 0.75rem; font-weight: 600; background: var(--accent-light); color: var(--accent); }
	.tag-source + .tag-source { margin-left: 3px; }
	.publication-link { color: var(--accent); text-decoration: none; font-size: 0.85rem; }
	.publication-link:hover { text-decoration: underline; }
	/* Titre coupé à la largeur de 50 caractères, sur une ligne. */
	.publication-title { display: inline-block; max-width: 50ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: bottom; }
	.assign-panel { position: relative; }
	.assign-row { display: flex; gap: 4px; align-items: center; }
	.assign-row input { padding: 4px 8px; border: 1px solid var(--border); border-radius: 4px; font-size: 0.85rem; width: 200px; }
	.assign-results {
		z-index: 50;
		display: flex; flex-direction: column; gap: 2px;
		background: var(--card); border: 1px solid var(--border); border-radius: 4px;
		box-shadow: 0 4px 12px rgba(0,0,0,0.1); padding: 4px; min-width: 250px;
	}
	.result-btn {
		display: block; width: 100%; text-align: left; padding: 4px 8px;
		border: none; background: var(--surface); cursor: pointer; border-radius: 3px; font-size: 0.85rem;
	}
	.result-btn:hover { background: var(--hover); }
	.result-hint { font-size: 0.75rem; color: var(--muted); margin-left: 4px; }
	.loading-text { font-size: 0.8rem; color: var(--muted); }
	.batch-bar {
		display: flex; align-items: center; gap: 10px;
		padding: 10px 14px; margin-bottom: 10px;
		background: var(--accent-light); border: 1px solid color-mix(in srgb, var(--accent) 25%, white); border-radius: 6px;
		position: relative;
	}
	.batch-bar input { padding: 5px 10px; border: 1px solid color-mix(in srgb, var(--accent) 25%, white); border-radius: 4px; font-size: 0.85rem; width: 220px; }
	.batch-results {
		z-index: 50;
		display: flex; flex-direction: column; gap: 2px;
		background: var(--card); border: 1px solid var(--border); border-radius: 4px;
		box-shadow: 0 4px 12px rgba(0,0,0,0.1); padding: 4px; min-width: 280px;
		margin-top: 4px;
	}
	.create-form { display: flex; flex-direction: column; gap: 10px; margin: 12px 0; }
	.create-form label { display: flex; flex-direction: column; gap: 3px; font-size: 0.85rem; font-weight: 500; }
	.create-form input { padding: 6px 8px; border: 1px solid var(--border); border-radius: 4px; font-size: 0.9rem; }
	.reject-detail { font-weight: 600; margin: 8px 0; }
	.reject-muted { color: var(--muted); font-size: 0.85rem; }
	.reject-list { margin: 10px 0; padding-left: 18px; font-size: 0.85rem; }
</style>
