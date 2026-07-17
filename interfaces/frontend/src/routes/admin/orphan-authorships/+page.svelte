<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { replaceState } from '$app/navigation';
	import { api, ApiError, orphanAuthorships } from '$lib/api';
	import { useDebouncedSearch } from '$lib/composables/useDebouncedSearch.svelte';
	import { titleCase } from '$lib/utils';
	import { autofocus } from '$lib/actions/focus';
	import Pagination from '$lib/components/Pagination.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import type { components } from '$lib/api/schema';

	type PersonResult = components['schemas']['PersonSearchResult'];
	type OrphanAuthorship = components['schemas']['OrphanAuthorshipOut'];
	type OrphansResponse = components['schemas']['OrphanAuthorshipsResponse'];
	type RejectedPair = components['schemas']['RejectedPairItem'];

	async function searchPersons(q: string): Promise<PersonResult[]> {
		return api<PersonResult[]>(`/api/persons/search?q=${encodeURIComponent(q)}`);
	}

	let search = $state('');
	let currentPage = $state(1);
	let totalPages = $state(1);
	let total = $state(0);
	let orphans: OrphanAuthorship[] = $state([]);
	// Une seule ligne peut avoir son panneau "attribuer" ouvert à la fois.
	let activeAssignIdx: number | null = $state(null);
	const assignSearch = useDebouncedSearch<PersonResult>({ search: searchPersons });
	let selectedIds = $state(new Set<string>());  // "source-authorship_id"
	const batchSearch = useDebouncedSearch<PersonResult>({ search: searchPersons });
	const allSelected = $derived(orphans.length > 0 && orphans.every(o => selectedIds.has(`${o.source}-${o.authorship_id}`)));
	let createModal: { lastName: string; firstName: string; items: OrphanAuthorship[] } | null = $state(null);
	// Modale de confirmation quand la réassignation porte sur une paire déjà rejetée (409).
	let rejectModal: { detail: string; pairs: RejectedPair[]; retry: () => Promise<void> } | null =
		$state(null);

	/**
	 * Exécute une réassignation en interceptant le 409 « paire déjà rejetée » :
	 * ouvre la modale de confirmation avec une closure qui rejoue l'opération
	 * en `force=true` (lève le rejet puis réassigne). Les autres erreurs
	 * remontent normalement.
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

	async function loadOrphans() {
		const params = new URLSearchParams({ page: String(currentPage), per_page: '50' });
		if (search.trim()) params.set('search', search.trim());
		const data = await api<OrphansResponse>(
			'/api/admin/orphan-authorships?' + params, { key: 'orphans' }
		);
		orphans = data.authorships;
		total = data.total;
		totalPages = data.pages;
		currentPage = data.page;
	}

	function openAssign(idx: number) {
		activeAssignIdx = idx;
		assignSearch.clear();
	}

	function closeAssign() {
		activeAssignIdx = null;
		assignSearch.clear();
	}

	async function assign(orphan: any, personId: number) {
		await withRejectGuard(async (force) => {
			await orphanAuthorships.assign({
				source: orphan.source,
				authorship_id: orphan.authorship_id,
				person_id: personId,
				force,
			});
			closeAssign();
			loadOrphans();
		});
	}

	function createAndAssign(orphan: OrphanAuthorship) {
		createModal = {
			lastName: orphan.last_name || orphan.full_name,
			firstName: orphan.first_name,
			items: [orphan],
		};
		closeAssign();
	}

	function toggleSelect(o: any) {
		const key = `${o.source}-${o.authorship_id}`;
		const s = new Set(selectedIds);
		if (s.has(key)) s.delete(key); else s.add(key);
		selectedIds = s;
	}

	function toggleAll() {
		if (allSelected) {
			selectedIds = new Set();
		} else {
			selectedIds = new Set(orphans.map(o => `${o.source}-${o.authorship_id}`));
		}
	}

	async function batchAssign(personId: number) {
		const items = orphans.filter(o => selectedIds.has(`${o.source}-${o.authorship_id}`));
		await withRejectGuard(async (force) => {
			await orphanAuthorships.batchAssign({
				person_id: personId,
				authorship_ids: items.map(o => o.authorship_id),
				force,
			});
			selectedIds = new Set();
			batchSearch.clear();
			loadOrphans();
		});
	}

	function openCreateModal() {
		const items = orphans.filter(o => selectedIds.has(`${o.source}-${o.authorship_id}`));
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
		// Créer la personne avec la première authorship
		const data = await orphanAuthorships.assign({
			source: items[0].source,
			authorship_id: items[0].authorship_id,
			create_person: { last_name: lastName, first_name: firstName },
		}) as { person_id?: number };
		if (!data.person_id) return;
		// Attribuer le reste
		const remaining = items.slice(1);
		if (remaining.length) {
			await orphanAuthorships.batchAssign({
				person_id: data.person_id,
				authorship_ids: remaining.map((o: any) => o.authorship_id),
			});
		}
		createModal = null;
		selectedIds = new Set();
		batchSearch.clear();
		loadOrphans();
	}

	function syncUrl() {
		const p = new URLSearchParams();
		if (currentPage > 1) p.set('page', String(currentPage));
		if (search.trim()) p.set('search', search.trim());
		const qs = p.toString();
		replaceState(`${base}/admin/orphan-authorships` + (qs ? '?' + qs : ''), {});
	}

	let debounceTimer: ReturnType<typeof setTimeout>;
	function onSearchInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(() => { currentPage = 1; syncUrl(); loadOrphans(); }, 400);
	}

	onMount(() => {
		const params = new URLSearchParams(window.location.search);
		if (params.get('page')) currentPage = parseInt(params.get('page')!) || 1;
		if (params.get('search')) search = params.get('search')!;
		loadOrphans();
	});
</script>

<svelte:head>
	<title>Authorships orphelines — Admin</title>
</svelte:head>

<div class="header">
	<h1>Authorships orphelines ({total})</h1>
	<a href="{base}/admin/persons" class="btn">← Retour aux personnes</a>
</div>

<div class="info-box">
	Authorships UCA non reliées à une personne. Pour chaque authorship, vous pouvez l'attribuer à une personne existante ou créer une nouvelle personne.
</div>

<div class="toolbar">
	<input type="search" placeholder="Filtrer par nom…" bind:value={search}
		use:autofocus onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onSearchInput(); } }}
		oninput={onSearchInput} autocomplete="off" />
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
			<div class="batch-results">
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
	<p class="empty">Aucune authorship orpheline{search.trim() ? ' pour ce filtre' : ''}.</p>
{:else}
	<table class="data-table">
		<thead>
			<tr>
				<th style="width:30px"><input type="checkbox" checked={allSelected} onchange={toggleAll} /></th>
				<th>Source</th>
				<th>Nom</th>
				<th>Publication</th>
				<th>Action</th>
			</tr>
		</thead>
		<tbody>
			{#each orphans as o, i}
				<tr>
					<td><input type="checkbox" checked={selectedIds.has(`${o.source}-${o.authorship_id}`)} onchange={() => toggleSelect(o)} /></td>
					<td><span class="tag tag-source">{SOURCE_LABELS[o.source] ?? o.source}</span></td>
					<td>{o.full_name}</td>
					<td>
						<a href="{base}/publications/{o.publication_id}" class="pub-link">
							{o.pub_year ?? '?'} — {o.pub_title?.slice(0, 80)}{(o.pub_title?.length ?? 0) > 80 ? '…' : ''}
						</a>
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
									<div class="assign-results">
										{#each assignSearch.results as r (r.id)}
											<button class="result-btn" onclick={() => assign(o, r.id)}>
												<strong>{titleCase(r.last_name)}</strong> {titleCase(r.first_name)}
												{#if r.has_rh}<span class="rh-check">✓</span>{/if}
												<span class="result-hint">{r.department_name || `#${r.id}`}</span>
											</button>
										{/each}
									</div>
								{:else if assignSearch.query.length >= 2}
									<div class="assign-results">
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

	<Pagination page={currentPage} pages={totalPages} onchange={(p) => { currentPage = p; syncUrl(); loadOrphans(); }} />
{/if}

{#if createModal}
	<Modal
		title={`Créer une personne (${createModal.items.length} authorship${createModal.items.length > 1 ? 's' : ''})`}
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
						<a href="{base}/publications/{p.publication_id}" target="_blank" rel="noopener">
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
		background: #fff8e1; border: 1px solid #ffe082; border-radius: 6px;
		padding: 10px 14px; font-size: 0.85rem; color: #6d4c00; margin-bottom: 14px;
	}
	.toolbar input { width: 300px; }
	.tag-source { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 0.75rem; font-weight: 600; background: var(--accent-light); color: var(--accent); }
	.pub-link { color: var(--accent); text-decoration: none; font-size: 0.85rem; }
	.pub-link:hover { text-decoration: underline; }
	:global(.data-table) { overflow: visible; }
	.assign-panel { position: relative; }
	.assign-row { display: flex; gap: 4px; align-items: center; }
	.assign-row input { padding: 4px 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 0.85rem; width: 200px; }
	.assign-results {
		position: absolute; top: 100%; left: 0; z-index: 50;
		display: flex; flex-direction: column; gap: 2px;
		background: white; border: 1px solid #ccc; border-radius: 4px;
		box-shadow: 0 4px 12px rgba(0,0,0,0.1); padding: 4px; min-width: 250px;
	}
	.result-btn {
		display: block; width: 100%; text-align: left; padding: 4px 8px;
		border: none; background: #f5f5f5; cursor: pointer; border-radius: 3px; font-size: 0.85rem;
	}
	.result-btn:hover { background: #e0e0e0; }
	.result-hint { font-size: 0.75rem; color: #888; margin-left: 4px; }
	.loading-text { font-size: 0.8rem; color: #888; }
	.batch-bar {
		display: flex; align-items: center; gap: 10px;
		padding: 10px 14px; margin-bottom: 10px;
		background: #e3f2fd; border: 1px solid #90caf9; border-radius: 6px;
		position: relative;
	}
	.batch-bar input { padding: 5px 10px; border: 1px solid #90caf9; border-radius: 4px; font-size: 0.85rem; width: 220px; }
	.batch-results {
		position: absolute; top: 100%; left: 0; z-index: 50;
		display: flex; flex-direction: column; gap: 2px;
		background: white; border: 1px solid #ccc; border-radius: 4px;
		box-shadow: 0 4px 12px rgba(0,0,0,0.1); padding: 4px; min-width: 280px;
		margin-top: 4px;
	}
	.create-form { display: flex; flex-direction: column; gap: 10px; margin: 12px 0; }
	.create-form label { display: flex; flex-direction: column; gap: 3px; font-size: 0.85rem; font-weight: 500; }
	.create-form input { padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 0.9rem; }
	.reject-detail { font-weight: 600; margin: 8px 0; }
	.reject-muted { color: #888; font-size: 0.85rem; }
	.reject-list { margin: 10px 0; padding-left: 18px; font-size: 0.85rem; }
</style>
