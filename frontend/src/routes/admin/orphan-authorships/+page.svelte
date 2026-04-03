<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { replaceState } from '$app/navigation';
	import { api } from '$lib/api';
	import { titleCase } from '$lib/utils';
	import Pagination from '$lib/components/Pagination.svelte';

	let search = $state('');
	let currentPage = $state(1);
	let totalPages = $state(1);
	let total = $state(0);
	let orphans: any[] = $state([]);
	let assignSearch: Record<number, { query: string; results: any[]; loading: boolean }> = $state({});
	let timers: Record<number, ReturnType<typeof setTimeout>> = {};
	let selectedIds = $state(new Set<string>());  // "source-authorship_id"
	let batchSearch = $state('');
	let batchResults: any[] = $state([]);
	let batchLoading = $state(false);
	let batchTimer: ReturnType<typeof setTimeout>;
	const allSelected = $derived(orphans.length > 0 && orphans.every(o => selectedIds.has(`${o.source}-${o.authorship_id}`)));
	let createModal: { lastName: string; firstName: string; items: any[] } | null = $state(null);

	async function loadOrphans() {
		const params = new URLSearchParams({ page: String(currentPage), per_page: '50' });
		if (search.trim()) params.set('search', search.trim());
		const data = await api<{ total: number; page: number; pages: number; authorships: any[] }>(
			'/api/orphan-authorships?' + params, { key: 'orphans' }
		);
		orphans = data.authorships;
		total = data.total;
		totalPages = data.pages;
		currentPage = data.page;
	}

	function openAssign(idx: number) {
		assignSearch = { [idx]: { query: '', results: [], loading: false } };
	}

	function handleSearchInput(idx: number, query: string) {
		assignSearch = { ...assignSearch, [idx]: { ...assignSearch[idx], query } };
		if (timers[idx]) clearTimeout(timers[idx]);
		if (query.trim().length < 2) {
			assignSearch = { ...assignSearch, [idx]: { ...assignSearch[idx], results: [], loading: false } };
			return;
		}
		timers[idx] = setTimeout(async () => {
			assignSearch = { ...assignSearch, [idx]: { ...assignSearch[idx], loading: true } };
			const results = await api<any[]>(`/api/persons/search?q=${encodeURIComponent(query.trim())}`);
			assignSearch = { ...assignSearch, [idx]: { ...assignSearch[idx], results, loading: false } };
		}, 300);
	}

	async function assign(orphan: any, personId: number) {
		await fetch(`${base}/api/orphan-authorships/assign`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ source: orphan.source, authorship_id: orphan.authorship_id, person_id: personId })
		});
		assignSearch = {};
		loadOrphans();
	}

	function createAndAssign(orphan: any) {
		const parts = orphan.full_name.includes(',')
			? orphan.full_name.split(',').map((s: string) => s.trim())
			: [orphan.full_name.split(' ').slice(-1)[0], orphan.full_name.split(' ').slice(0, -1).join(' ')];
		createModal = {
			lastName: parts[0] || orphan.full_name,
			firstName: parts[1] || '',
			items: [orphan],
		};
		assignSearch = {};
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

	function handleBatchSearchInput(query: string) {
		batchSearch = query;
		if (batchTimer) clearTimeout(batchTimer);
		if (query.trim().length < 2) { batchResults = []; batchLoading = false; return; }
		batchLoading = true;
		batchTimer = setTimeout(async () => {
			batchResults = await api<any[]>(`/api/persons/search?q=${encodeURIComponent(query.trim())}`);
			batchLoading = false;
		}, 300);
	}

	async function batchAssign(personId: number) {
		const items = orphans.filter(o => selectedIds.has(`${o.source}-${o.authorship_id}`));
		await fetch(`${base}/api/orphan-authorships/batch-assign`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				person_id: personId,
				authorships: items.map(o => ({ source: o.source, authorship_id: o.authorship_id }))
			})
		});
		selectedIds = new Set();
		batchSearch = '';
		batchResults = [];
		loadOrphans();
	}

	function openCreateModal() {
		const items = orphans.filter(o => selectedIds.has(`${o.source}-${o.authorship_id}`));
		if (!items.length) return;
		const name = items[0].full_name;
		const parts = name.includes(',')
			? name.split(',').map((s: string) => s.trim())
			: [name.split(' ').slice(-1)[0], name.split(' ').slice(0, -1).join(' ')];
		createModal = {
			lastName: parts[0] || name,
			firstName: parts[1] || '',
			items,
		};
	}

	async function confirmCreate() {
		if (!createModal) return;
		const { lastName, firstName, items } = createModal;
		// Créer la personne avec la première authorship
		const resp = await fetch(`${base}/api/orphan-authorships/assign`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				source: items[0].source, authorship_id: items[0].authorship_id,
				create_person: { last_name: lastName, first_name: firstName }
			})
		});
		const data = await resp.json();
		if (!data.person_id) return;
		// Attribuer le reste
		const remaining = items.slice(1);
		if (remaining.length) {
			await fetch(`${base}/api/orphan-authorships/batch-assign`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					person_id: data.person_id,
					authorships: remaining.map((o: any) => ({ source: o.source, authorship_id: o.authorship_id }))
				})
			});
		}
		createModal = null;
		selectedIds = new Set();
		batchSearch = '';
		batchResults = [];
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
	<input type="text" placeholder="Filtrer par nom…" bind:value={search}
		oninput={onSearchInput} autocomplete="off" />
</div>

{#if selectedIds.size > 0}
	<div class="batch-bar">
		<span>{selectedIds.size} sélectionnée{selectedIds.size > 1 ? 's' : ''}</span>
		<input type="text" placeholder="Attribuer à une personne existante…" value={batchSearch}
			oninput={(e) => handleBatchSearchInput((e.target as HTMLInputElement).value)} autocomplete="off" />
		<button class="btn btn-sm btn-create" onclick={openCreateModal}>Créer une personne</button>
		{#if batchLoading}
			<span class="loading-text">…</span>
		{:else if batchResults.length}
			<div class="batch-results">
				{#each batchResults as r}
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
					<td><span class="tag tag-source">{o.source === 'openalex' ? 'OA' : o.source === 'hal' ? 'HAL' : 'WoS'}</span></td>
					<td>{o.full_name}</td>
					<td>
						<a href="{base}/publications/{o.publication_id}" class="pub-link">
							{o.pub_year ?? '?'} — {o.pub_title?.slice(0, 80)}{(o.pub_title?.length ?? 0) > 80 ? '…' : ''}
						</a>
					</td>
					<td>
						{#if i in assignSearch}
							{@const as = assignSearch[i]}
							<div class="assign-panel">
								<div class="assign-row">
									<input type="text" placeholder="Nom de la personne…" value={as.query}
										oninput={(e) => handleSearchInput(i, (e.target as HTMLInputElement).value)} />
									<button class="btn btn-sm" onclick={() => { delete assignSearch[i]; assignSearch = assignSearch; }}>&times;</button>
								</div>
								{#if as.loading}
									<span class="loading-text">…</span>
								{:else if as.results.length}
									<div class="assign-results">
										{#each as.results as r}
											<button class="result-btn" onclick={() => assign(o, r.id)}>
												<strong>{titleCase(r.last_name)}</strong> {titleCase(r.first_name)}
												{#if r.has_rh}<span class="rh-check">✓</span>{/if}
												<span class="result-hint">{r.department_name || `#${r.id}`}</span>
											</button>
										{/each}
									</div>
								{:else if as.query.length >= 2}
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
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="modal-overlay" onclick={() => { createModal = null; }}>
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div class="modal-content" onclick={(e) => e.stopPropagation()}>
			<h3>Créer une personne ({createModal.items.length} authorship{createModal.items.length > 1 ? 's' : ''})</h3>
			<div class="create-form">
				<label>
					Nom
					<input type="text" bind:value={createModal.lastName}
						onkeydown={(e) => { if (e.key === 'Enter') confirmCreate(); }} />
				</label>
				<label>
					Prénom
					<input type="text" bind:value={createModal.firstName}
						onkeydown={(e) => { if (e.key === 'Enter') confirmCreate(); }} />
				</label>
			</div>
			<div class="modal-actions">
				<button class="btn" onclick={() => { createModal = null; }}>Annuler</button>
				<button class="btn btn-confirm" onclick={confirmCreate}>Créer et attribuer</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
	.header h1 { margin: 0; font-size: 1.2rem; }
	.info-box {
		background: #fff8e1; border: 1px solid #ffe082; border-radius: 6px;
		padding: 10px 14px; font-size: 0.85rem; color: #6d4c00; margin-bottom: 14px;
	}
	.toolbar input { width: 300px; }
	.tag-source { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 0.75rem; font-weight: 600; background: #e8f0f8; color: #3b6b9e; }
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
	.modal-content { max-width: 400px; }
	.create-form { display: flex; flex-direction: column; gap: 10px; margin: 12px 0; }
	.create-form label { display: flex; flex-direction: column; gap: 3px; font-size: 0.85rem; font-weight: 500; }
	.create-form input { padding: 6px 8px; border: 1px solid #ccc; border-radius: 4px; font-size: 0.9rem; }
</style>
