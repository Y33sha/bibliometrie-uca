<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { api } from '$lib/api';
	import Pagination from '$lib/components/Pagination.svelte';
	import type { components } from '$lib/api/schema';

	type Publisher = components['schemas']['PublisherListItem'];
	type PublisherListResponse = components['schemas']['PublisherListResponse'];
	type EnumOption = components['schemas']['EnumOption'];

	const PER_PAGE = 50;

	let search = $state('');
	let publisherType = $state('');
	let country = $state('');
	let sort = $state('-pubs');
	let page = $state(1);

	let data = $state<PublisherListResponse | null>(null);
	let loading = $state(false);
	let publisherTypes: EnumOption[] = $state([]);
	let countries: string[] = $state([]);
	const publisherTypeLabels = $derived(
		Object.fromEntries(publisherTypes.map((t) => [t.value, t.label_fr]))
	);
	let searchTimer: ReturnType<typeof setTimeout> | undefined;

	async function loadPublishers() {
		loading = true;
		try {
			const params = new URLSearchParams();
			const q = search.trim();
			if (q.length >= 2) params.set('search', q);
			if (publisherType) params.set('publisher_type', publisherType);
			if (country) params.set('country', country);
			params.set('with_pubs', 'true');
			params.set('sort', sort);
			params.set('page', String(page));
			params.set('per_page', String(PER_PAGE));
			data = await api<PublisherListResponse>(`/api/publishers?${params}`);
		} finally {
			loading = false;
		}
	}

	async function loadFacetOptions() {
		const [types, ctrs] = await Promise.all([
			api<EnumOption[]>('/api/publisher-types'),
			api<string[]>('/api/publishers/countries')
		]);
		publisherTypes = types;
		countries = ctrs;
	}

	function onSearchInput() {
		if (searchTimer) clearTimeout(searchTimer);
		searchTimer = setTimeout(() => {
			page = 1;
			loadPublishers();
		}, 300);
	}

	function onFilterChange() {
		page = 1;
		loadPublishers();
	}

	function setSort(s: string) {
		sort = sort === s ? oppositeSort(s) : s;
		page = 1;
		loadPublishers();
	}

	function oppositeSort(s: string): string {
		return s.startsWith('-') ? s.slice(1) : '-' + s;
	}

	function sortArrow(col: 'name' | 'journals' | 'pubs'): string {
		if (sort === col) return '▲';
		if (sort === '-' + col) return '▼';
		return '';
	}

	const totalPages = $derived(data ? data.pages : 1);

	onMount(async () => {
		await loadFacetOptions();
		await loadPublishers();
	});
</script>

<svelte:head>
	<title>Éditeurs — Bibliométrie UCA</title>
</svelte:head>

<h1>Éditeurs</h1>
<p class="hint">
	Liste des éditeurs des revues observées sur les publications du périmètre
	UCA. Cliquer sur un éditeur pour explorer son portfolio de revues et ses
	publications.
</p>

<div class="filters">
	<input
		type="text"
		placeholder="Rechercher dans les noms…"
		bind:value={search}
		oninput={onSearchInput}
	/>
	<label>
		Type
		<select bind:value={publisherType} onchange={onFilterChange}>
			<option value="">Tous</option>
			{#each publisherTypes as t (t.value)}
				<option value={t.value}>{t.label_fr}</option>
			{/each}
		</select>
	</label>
	<label>
		Pays
		<select bind:value={country} onchange={onFilterChange}>
			<option value="">Tous</option>
			{#each countries as c (c)}
				<option value={c}>{c}</option>
			{/each}
		</select>
	</label>
	<span class="spacer"></span>
	<span class="count">{data ? data.total.toLocaleString('fr-FR') : '…'} éditeurs</span>
</div>

{#if loading && !data}
	<p class="loading">Chargement…</p>
{:else if data}
	<table class="publishers-table">
		<thead>
			<tr>
				<th class="sortable" onclick={() => setSort('name')}>
					Nom {sortArrow('name')}
				</th>
				<th>Type</th>
				<th>Pays</th>
				<th>Préfixes DOI</th>
				<th class="num sortable" onclick={() => setSort('journals')}>
					Revues {sortArrow('journals')}
				</th>
				<th class="num sortable" onclick={() => setSort('pubs')}>
					Publis {sortArrow('pubs')}
				</th>
			</tr>
		</thead>
		<tbody>
			{#each data.publishers as p (p.id)}
				<tr>
					<td>
						<a href="{base}/publishers/{p.id}" class="publisher-link">{p.name}</a>
						{#if p.is_predatory}<span class="badge-pred">prédateur</span>{/if}
					</td>
					<td class="muted">{publisherTypeLabels[p.publisher_type] ?? p.publisher_type}</td>
					<td class="muted">{p.country ?? ''}</td>
					<td class="prefixes">
						{#each p.doi_prefixes as dp (dp.prefix)}
							<span class="prefix-chip" title="RA : {dp.ra}{dp.crossref_member_id ? ` / member ${dp.crossref_member_id}` : ''}">{dp.prefix}</span>
						{/each}
					</td>
					<td class="num">{p.journal_count.toLocaleString('fr-FR')}</td>
					<td class="num">{p.pub_count.toLocaleString('fr-FR')}</td>
				</tr>
			{/each}
			{#if data.publishers.length === 0}
				<tr><td colspan="6" class="no-results">Aucun éditeur ne correspond aux filtres.</td></tr>
			{/if}
		</tbody>
	</table>
	<Pagination {page} pages={totalPages} onchange={(p) => { page = p; loadPublishers(); }} />
{/if}

<style>
	h1 { margin: 0 0 8px; font-size: 1.5rem; }
	.hint { color: var(--muted); font-size: 0.9rem; margin: 0 0 16px; }

	.filters {
		display: flex; align-items: center; gap: 12px;
		flex-wrap: wrap; margin-bottom: 16px;
		background: var(--card); border: 1px solid var(--border);
		border-radius: 6px; padding: 12px;
	}
	.filters input[type='text'] { width: 240px; padding: 6px 10px; }
	.filters label {
		display: inline-flex; align-items: center; gap: 6px;
		font-size: 0.85rem; color: var(--muted); font-weight: 600;
	}
	.filters select { padding: 5px 8px; font-size: 0.9rem; }
	.spacer { flex: 1; }
	.count { font-size: 0.9rem; color: var(--muted); font-variant-numeric: tabular-nums; }

	.loading { color: var(--muted); padding: 12px; }

	.publishers-table {
		width: 100%; border-collapse: collapse;
		background: var(--card); border: 1px solid var(--border); border-radius: 6px;
	}
	.publishers-table thead th {
		background: #f5f4f1; padding: 8px 10px; text-align: left;
		font-size: 0.85rem; font-weight: 600; color: var(--muted);
		border-bottom: 2px solid var(--border); white-space: nowrap;
	}
	.publishers-table thead th.num { text-align: right; }
	.publishers-table thead th.sortable { cursor: pointer; user-select: none; }
	.publishers-table thead th.sortable:hover { color: var(--accent); }
	.publishers-table tbody tr { border-bottom: 1px solid #f0efec; }
	.publishers-table tbody tr:last-child { border-bottom: none; }
	.publishers-table tbody tr:hover { background: #fafaf8; }
	.publishers-table td { padding: 7px 10px; font-size: 0.95rem; vertical-align: top; }
	.publishers-table td.num { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
	.muted { color: var(--muted); }
	.no-results { text-align: center; color: var(--muted); padding: 30px; }

	.prefixes { display: flex; flex-wrap: wrap; gap: 3px; }
	.prefix-chip {
		background: #f0efec; color: var(--muted);
		padding: 1px 6px; border-radius: 8px;
		font-size: 0.75rem; font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}

	.publisher-link { color: var(--accent); text-decoration: none; font-weight: 500; }
	.publisher-link:hover { text-decoration: underline; }
	.badge-pred {
		font-size: 0.7rem; padding: 1px 5px; background: #c0392b;
		color: white; border-radius: 8px; margin-left: 6px;
		vertical-align: middle; font-weight: 600;
	}
</style>
