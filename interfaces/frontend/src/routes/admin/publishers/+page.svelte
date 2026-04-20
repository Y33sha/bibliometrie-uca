<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError, publishers as publishersApi } from '$lib/api';
	import { useDebouncedSearch } from '$lib/composables/useDebouncedSearch.svelte';
	import Pagination from '$lib/components/Pagination.svelte';

	interface Publisher {
		id: number;
		name: string;
		openalex_id: string | null;
		country: string | null;
		doi_prefix: string | null;
		is_predatory: boolean;
		journal_count: number;
		pub_count: number;
	}

	// Modal édition
	let editModal: { id: number; name: string; country: string; doi_prefix: string; is_predatory: boolean; notes: string } | null = $state(null);

	function openEdit(pub: Publisher) {
		editModal = {
			id: pub.id,
			name: pub.name,
			country: pub.country || '',
			doi_prefix: pub.doi_prefix || '',
			is_predatory: pub.is_predatory,
			notes: '',
		};
	}

	async function saveEdit() {
		if (!editModal) return;
		const body: Record<string, any> = {};
		if (editModal.name.trim()) body.name = editModal.name.trim();
		body.country = editModal.country.trim() || null;
		body.doi_prefix = editModal.doi_prefix.trim() || null;
		body.is_predatory = editModal.is_predatory;
		if (editModal.notes.trim()) body.notes = editModal.notes.trim();
		try {
			await publishersApi.update(editModal.id, body);
			editModal = null;
			await load();
		} catch (e: any) {
			const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
			alert('Erreur : ' + msg);
		}
	}

	let publishers: Publisher[] = $state([]);
	let total = $state(0);
	let page = $state(1);
	let pages = $state(1);
	let perPage = 50;
	let search = $state('');
	let sort = $state('-pubs');
	let searchTimer: ReturnType<typeof setTimeout>;

	// Merge state : recherche avec debounce + cible en cours de fusion
	let mergeTargetId: number | null = $state(null);
	const mergeSearch = useDebouncedSearch<Publisher>({
		search: async (q) => {
			const data = await api<{ publishers: Publisher[] }>(
				`/api/publishers?search=${encodeURIComponent(q)}&per_page=10`,
			);
			return data.publishers;
		},
		transform: (results) => results.filter((p) => p.id !== mergeTargetId),
	});

	async function load() {
		const params = new URLSearchParams({ page: String(page), per_page: String(perPage), sort });
		if (search) params.set('search', search);
		const data = await api<any>(`/api/publishers?${params}`);
		publishers = data.publishers;
		total = data.total;
		pages = data.pages;
	}

	function onSearch(value: string) {
		search = value;
		clearTimeout(searchTimer);
		searchTimer = setTimeout(() => { page = 1; load(); }, 300);
	}

	function setSort(s: string) { sort = s; page = 1; load(); }

	// Merge
	function openMerge(id: number) {
		mergeTargetId = id;
		mergeSearch.clear();
	}

	function closeMerge() {
		mergeTargetId = null;
		mergeSearch.clear();
	}

	async function doMerge(sourceId: number) {
		if (!mergeTargetId) return;
		try {
			await publishersApi.merge(mergeTargetId, sourceId);
			closeMerge();
			await load();
		} catch (e: any) {
			if (e instanceof ApiError) {
				const detail = (e.detail as { detail?: string })?.detail;
				alert(detail || `HTTP ${e.status}`);
				return;
			}
			alert('Erreur réseau : ' + e.message);
		}
	}

	onMount(load);
</script>

<svelte:head><title>Éditeurs — Bibliométrie UCA</title></svelte:head>

<h2>Éditeurs <span class="count">({total})</span></h2>

<div class="toolbar">
	<input type="text" placeholder="Rechercher un éditeur…" value={search}
		oninput={(e) => onSearch((e.target as HTMLInputElement).value)} class="search-input" />
</div>

<table class="data-table">
	<thead>
		<tr>
			<th class="sortable" onclick={() => setSort(sort === 'name' ? '-name' : 'name')}>
				Nom {sort === 'name' ? '▲' : sort === '-name' ? '▼' : ''}
			</th>
			<th>Pays</th>
			<th>DOI prefix</th>
			<th class="sortable num" onclick={() => setSort(sort === '-journals' ? 'journals' : '-journals')}>
				Revues {sort === '-journals' ? '▲' : sort === 'journals' ? '▼' : ''}
			</th>
			<th class="sortable num" onclick={() => setSort(sort === '-pubs' ? 'pubs' : '-pubs')}>
				Publis {sort === '-pubs' ? '▲' : sort === 'pubs' ? '▼' : ''}
			</th>
			<th></th>
		</tr>
	</thead>
	<tbody>
		{#each publishers as pub (pub.id)}
			<tr class:predatory={pub.is_predatory}>
				<td>
					<span class="pub-name">{pub.name}</span>
					{#if pub.is_predatory}<span class="badge-pred">prédateur</span>{/if}
				</td>
				<td class="muted">{pub.country || ''}</td>
				<td class="muted">{pub.doi_prefix || ''}</td>
				<td class="num">{pub.journal_count}</td>
				<td class="num">{pub.pub_count}</td>
				<td class="actions">
					{#if mergeTargetId === pub.id}
						<div class="merge-search">
							<input type="text" placeholder="Fusionner avec…" value={mergeSearch.query}
								oninput={(e) => mergeSearch.setQuery((e.target as HTMLInputElement).value)}
								class="merge-input" />
							<button class="btn btn-sm" onclick={closeMerge}>Annuler</button>
							{#if mergeSearch.loading}
								<div class="merge-results"><span class="muted">Recherche…</span></div>
							{:else if mergeSearch.results.length > 0}
								<div class="merge-results">
									{#each mergeSearch.results as r (r.id)}
										<button class="merge-result" onclick={() => doMerge(r.id)}>
											{r.name} <span class="muted">({r.journal_count} revues, {r.pub_count} publis)</span>
										</button>
									{/each}
								</div>
							{:else if mergeSearch.query.length >= 2}
								<div class="merge-results"><span class="muted">Aucun résultat</span></div>
							{/if}
						</div>
					{:else}
						<button class="btn btn-sm" onclick={() => openEdit(pub)}>Modifier</button>
						<button class="btn btn-sm btn-merge" onclick={() => openMerge(pub.id)}>Fusionner…</button>
					{/if}
				</td>
			</tr>
		{/each}
	</tbody>
</table>

<Pagination {page} {pages} onchange={(p) => { page = p; load(); }} />

{#if editModal}
<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
<div class="modal-bg" onclick={() => editModal = null}>
	<!-- svelte-ignore a11y_no_static_element_interactions a11y_click_events_have_key_events -->
	<div class="modal" onclick={(e) => e.stopPropagation()}>
		<h3>Modifier l'éditeur</h3>
		<label>Nom</label>
		<input bind:value={editModal.name} />
		<label>Pays</label>
		<input bind:value={editModal.country} placeholder="ex: FR, US" />
		<label>DOI prefix</label>
		<input bind:value={editModal.doi_prefix} placeholder="ex: 10.1038" />
		<label>
			<input type="checkbox" bind:checked={editModal.is_predatory} /> Prédateur
		</label>
		<label>Notes</label>
		<textarea bind:value={editModal.notes} rows="2"></textarea>
		<div class="modal-actions">
			<button class="btn" onclick={() => editModal = null}>Annuler</button>
			<button class="btn btn-primary" onclick={saveEdit}>Enregistrer</button>
		</div>
	</div>
</div>
{/if}

<style>
	h2 { font-size: 1.2rem; font-weight: 600; margin: 0 0 12px; }
	.count { color: var(--muted); font-weight: 400; }
	.toolbar { margin-bottom: 12px; }
	.search-input { width: 300px; padding: 6px 10px; border: 1px solid var(--border); border-radius: 4px; font-size: 0.9rem; font-family: inherit; }

	.data-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
	.data-table th { text-align: left; padding: 6px 10px; border-bottom: 2px solid var(--border); font-size: 0.8rem; color: var(--muted); text-transform: uppercase; }
	.data-table td { padding: 6px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
	.data-table .num { text-align: right; }
	.sortable { cursor: pointer; user-select: none; }
	.sortable:hover { color: var(--accent); }

	.pub-name { font-weight: 500; }
	.muted { color: var(--muted); font-size: 0.85rem; }
	.predatory td { background: #fff0f0; }
	.badge-pred { font-size: 0.7rem; padding: 1px 5px; background: #d32f2f; color: white; border-radius: 8px; margin-left: 6px; }

	.actions { white-space: nowrap; position: relative; text-align: right; }
	.btn-merge { font-size: 0.8rem; color: var(--accent); background: none; border: 1px solid var(--border); border-radius: 3px; cursor: pointer; padding: 2px 8px; }
	.btn-merge:hover { background: var(--accent-light); }

	.merge-search { display: inline-block; position: relative; }
	.merge-input { width: 160px; padding: 3px 6px; font-size: 0.85rem; border: 1px solid var(--accent); border-radius: 3px; font-family: inherit; }
	.merge-results { position: absolute; right: 0; top: 100%; z-index: 10; border: 1px solid var(--border); border-radius: 4px; margin-top: 2px; max-height: 200px; overflow-y: auto; background: white; min-width: 350px; box-shadow: 0 2px 8px rgba(0,0,0,0.12); }
	.merge-result { display: block; width: 100%; padding: 5px 8px; font-size: 0.85rem; cursor: pointer; background: none; border: none; text-align: left; font-family: inherit; }
	.merge-result:hover { background: var(--warning-light, #fff3e0); }

</style>
