<script lang="ts">
	import { pageTitle } from '$lib/institution.svelte';
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { ApiError, monographs as monographsApi } from '$lib/api';
	import { autofocus } from '$lib/actions/focus';
	import { toast } from '$lib/dialogs.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Pagination from '$lib/components/Pagination.svelte';
	import TableStatusRow from '$lib/components/TableStatusRow.svelte';
	import { usePaginatedFetch } from '$lib/composables/usePaginatedFetch.svelte';
	import type { components } from '$lib/api/schema';

	type Monograph = components['schemas']['MonographListItem'];

	let search = $state('');
	let kind = $state('');
	let currentSort = $state('pubs_desc');
	// Incrément qui invalide le cache de la liste après une édition.
	let viewVersion = $state(0);

	const monographs = usePaginatedFetch<Monograph>({
		endpoint: '/api/monographs',
		itemsKey: 'monographs',
		perPage: 50,
		apiKey: () => `admin-monographs-${viewVersion}`,
		buildParams() {
			const params = new URLSearchParams();
			params.set('sort', currentSort);
			if (kind) params.set('kind', kind);
			const q = search.trim();
			if (q) params.set('search', q);
			return params;
		},
	});

	let searchTimer: ReturnType<typeof setTimeout> | undefined;
	function onSearchInput() {
		clearTimeout(searchTimer);
		searchTimer = setTimeout(() => {
			monographs.page = 1;
			monographs.load();
		}, 300);
	}

	function onKindChange() {
		monographs.page = 1;
		monographs.load();
	}

	function setSort(column: 'title' | 'year' | 'pubs') {
		currentSort = currentSort === `${column}_desc` ? `${column}_asc` : `${column}_desc`;
		monographs.page = 1;
		monographs.load();
	}

	function sortArrow(column: 'title' | 'year' | 'pubs'): string {
		if (currentSort === `${column}_asc`) return '▲';
		if (currentSort === `${column}_desc`) return '▼';
		return '';
	}

	let editModal: { id: number; title: string; proceedings: boolean; year: string } | null =
		$state(null);

	function openEdit(m: Monograph) {
		editModal = { id: m.id, title: m.title, proceedings: m.proceedings, year: m.year ? String(m.year) : '' };
	}

	async function saveEdit() {
		if (!editModal) return;
		try {
			await monographsApi.update(editModal.id, {
				title: editModal.title.trim(),
				proceedings: editModal.proceedings,
				year: editModal.year.trim() ? Number(editModal.year) : null,
			});
			editModal = null;
			viewVersion += 1;
			monographs.load();
		} catch (e: any) {
			const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
			toast('Erreur : ' + msg, 'error');
		}
	}

	onMount(() => monographs.load());
</script>

<svelte:head><title>{pageTitle('Monographies')}</title></svelte:head>

<h2>Monographies</h2>

<div class="toolbar toolbar-card toolbar-sticky">
	<input
		type="search"
		class="search"
		placeholder="Rechercher par titre ou ISBN…"
		bind:value={search}
		use:autofocus
		onkeydown={(e) => { if (e.key === 'Escape') { search = ''; onSearchInput(); } }}
		oninput={onSearchInput}
	/>
	<select bind:value={kind} onchange={onKindChange}>
		<option value="">Livres et actes</option>
		<option value="book">Livres</option>
		<option value="proceedings">Volumes d'actes</option>
	</select>
	<span class="count">{monographs.total.toLocaleString('fr-FR')} monographie{monographs.total > 1 ? 's' : ''}</span>
</div>

<div class="table-scroll">
	<table class="monographs-table">
		<thead>
			<tr>
				<th class="sortable" onclick={() => setSort('title')}>Titre {sortArrow('title')}</th>
				<th>Type</th>
				<th class="num sortable" onclick={() => setSort('year')}>Année {sortArrow('year')}</th>
				<th>ISBN</th>
				<th>Éditeur</th>
				<th>Collection</th>
				<th class="num sortable" onclick={() => setSort('pubs')}>Publis {sortArrow('pubs')}</th>
				<th></th>
			</tr>
		</thead>
		<tbody>
			{#each monographs.items as m (m.id)}
				<tr>
					<td>{m.title}</td>
					<td class="muted">{m.proceedings ? 'Actes' : 'Livre'}</td>
					<td class="num">{m.year ?? ''}</td>
					<td class="isbn">{[m.isbn, m.eisbn].filter(Boolean).join(' / ')}</td>
					<td>
						{#if m.publisher_id}<a href="{base}/publishers/{m.publisher_id}">{m.pub_name}</a>{/if}
					</td>
					<td>
						{#if m.journal_id}<a href="{base}/journals/{m.journal_id}">{m.journal_title}</a>{/if}
					</td>
					<td class="num">{m.pub_count.toLocaleString('fr-FR')}</td>
					<td class="actions"><button class="btn btn-sm" onclick={() => openEdit(m)}>Modifier</button></td>
				</tr>
			{/each}
			{#if monographs.items.length === 0}
				<TableStatusRow loading={monographs.loading} colspan={8} emptyText="Aucune monographie ne correspond aux filtres." />
			{/if}
		</tbody>
	</table>
</div>

<Pagination
	page={monographs.page}
	pages={monographs.pages}
	onchange={(p) => {
		monographs.page = p;
		monographs.load();
	}}
/>

{#if editModal}
	<Modal title="Modifier la monographie" maxWidth="520px" onclose={() => (editModal = null)} onsubmit={saveEdit}>
		<label>Titre <input bind:value={editModal.title} /></label>
		<div style="display:flex;gap:8px">
			<div style="flex:1">
				<label>Type <select bind:value={editModal.proceedings}>
					<option value={false}>Livre</option>
					<option value={true}>Volume d'actes</option>
				</select></label>
			</div>
			<div style="flex:1"><label>Année <input bind:value={editModal.year} inputmode="numeric" /></label></div>
		</div>
	</Modal>
{/if}

<style>
	.monographs-table {
		width: 100%;
		min-width: 720px;
		border-collapse: collapse;
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 6px;
	}
	.monographs-table thead th {
		background: var(--surface);
		padding: 8px 10px;
		text-align: left;
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--muted);
		border-bottom: 2px solid var(--border);
		white-space: nowrap;
	}
	.monographs-table thead th.num { text-align: right; }
	.monographs-table thead th.sortable { cursor: pointer; user-select: none; }
	.monographs-table thead th.sortable:hover { color: var(--accent); }
	.monographs-table tbody tr { border-bottom: 1px solid var(--border-subtle); }
	.monographs-table tbody tr:last-child { border-bottom: none; }
	.monographs-table td { padding: 6px 10px; font-size: 0.9rem; vertical-align: top; }
	.monographs-table td.num { text-align: right; white-space: nowrap; }
	.isbn { font-family: var(--mono, monospace); font-size: 0.8rem; white-space: nowrap; }
	.actions { white-space: nowrap; text-align: right; }
	.muted { color: var(--muted); }
	.search { width: 22rem; max-width: 100%; }
</style>
