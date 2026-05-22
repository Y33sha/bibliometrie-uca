<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { api } from '$lib/api';
	import Pagination from '$lib/components/Pagination.svelte';
	import type { components } from '$lib/api/schema';

	type Journal = components['schemas']['JournalOut'];
	type JournalListResponse = components['schemas']['JournalListResponse'];
	type EnumOption = components['schemas']['EnumOption'];

	const PER_PAGE = 50;

	let search = $state('');
	let journalType = $state('');
	let inDoaj = $state(''); // '', 'true', 'false'
	let oaModel = $state('');
	let sort = $state('-pubs');
	let page = $state(1);

	let data = $state<JournalListResponse | null>(null);
	let loading = $state(false);
	let journalTypes: EnumOption[] = $state([]);
	let oaModels: string[] = $state([]);
	let searchTimer: ReturnType<typeof setTimeout> | undefined;

	async function loadJournals() {
		loading = true;
		try {
			const params = new URLSearchParams();
			const q = search.trim();
			if (q.length >= 2) params.set('search', q);
			if (journalType) params.set('journal_type', journalType);
			if (inDoaj) params.set('is_in_doaj', inDoaj);
			if (oaModel) params.set('oa_model', oaModel);
			params.set('sort', sort);
			params.set('page', String(page));
			params.set('per_page', String(PER_PAGE));
			data = await api<JournalListResponse>(`/api/journals?${params}`);
		} finally {
			loading = false;
		}
	}

	async function loadFacetOptions() {
		const [types, models] = await Promise.all([
			api<EnumOption[]>('/api/journal-types'),
			api<string[]>('/api/journals/oa-models')
		]);
		journalTypes = types;
		oaModels = models;
	}

	function onSearchInput() {
		if (searchTimer) clearTimeout(searchTimer);
		searchTimer = setTimeout(() => {
			page = 1;
			loadJournals();
		}, 300);
	}

	function onFilterChange() {
		page = 1;
		loadJournals();
	}

	function setSort(s: string) {
		sort = sort === s ? oppositeSort(s) : s;
		page = 1;
		loadJournals();
	}

	function oppositeSort(s: string): string {
		return s.startsWith('-') ? s.slice(1) : '-' + s;
	}

	function sortArrow(col: 'title' | 'publisher' | 'pubs'): string {
		if (sort === col) return '▲';
		if (sort === '-' + col) return '▼';
		return '';
	}

	function formatIssns(j: Journal): string {
		const parts: string[] = [];
		if (j.issn) parts.push(j.issn);
		if (j.eissn) parts.push(j.eissn);
		return parts.join(' / ');
	}

	const totalPages = $derived(data ? data.pages : 1);

	onMount(async () => {
		await loadFacetOptions();
		await loadJournals();
	});
</script>

<svelte:head>
	<title>Revues — Bibliométrie UCA</title>
</svelte:head>

<div class="page">
	<h1>Revues</h1>
	<p class="hint">
		Liste des revues observées sur les publications du périmètre UCA. Cliquer
		sur une revue pour explorer ses publications, sa répartition par type/OA
		et ses données DOAJ.
	</p>

	<div class="filters">
		<input
			type="text"
			placeholder="Rechercher dans les titres…"
			bind:value={search}
			oninput={onSearchInput}
		/>
		<label>
			Type
			<select bind:value={journalType} onchange={onFilterChange}>
				<option value="">Tous</option>
				{#each journalTypes as t (t.value)}
					<option value={t.value}>{t.label_fr}</option>
				{/each}
			</select>
		</label>
		<label>
			DOAJ
			<select bind:value={inDoaj} onchange={onFilterChange}>
				<option value="">Tous</option>
				<option value="true">Indexée</option>
				<option value="false">Non indexée</option>
			</select>
		</label>
		<label>
			Modèle OA
			<select bind:value={oaModel} onchange={onFilterChange}>
				<option value="">Tous</option>
				{#each oaModels as m (m)}
					<option value={m}>{m}</option>
				{/each}
			</select>
		</label>
		<span class="spacer"></span>
		<span class="count">{data ? data.total.toLocaleString('fr-FR') : '…'} revues</span>
	</div>

	{#if loading && !data}
		<p class="loading">Chargement…</p>
	{:else if data}
		<table class="journals-table">
			<thead>
				<tr>
					<th class="sortable" onclick={() => setSort('title')}>
						Titre {sortArrow('title')}
					</th>
					<th>ISSN</th>
					<th class="sortable" onclick={() => setSort('publisher')}>
						Éditeur {sortArrow('publisher')}
					</th>
					<th class="num sortable" onclick={() => setSort('pubs')}>
						Publis {sortArrow('pubs')}
					</th>
				</tr>
			</thead>
			<tbody>
				{#each data.journals as j (j.id)}
					<tr>
						<td>
							<a href="{base}/journals/{j.id}" class="journal-link">{j.title}</a>
							{#if j.is_in_doaj}<span class="badge-doaj">DOAJ</span>{/if}
							{#if j.is_predatory}<span class="badge-pred">prédatrice</span>{/if}
						</td>
						<td class="issn-cell">{formatIssns(j)}</td>
						<td class="muted">{j.pub_name ?? ''}</td>
						<td class="num">{j.pub_count.toLocaleString('fr-FR')}</td>
					</tr>
				{/each}
				{#if data.journals.length === 0}
					<tr><td colspan="4" class="no-results">Aucune revue ne correspond aux filtres.</td></tr>
				{/if}
			</tbody>
		</table>
		<Pagination {page} pages={totalPages} onchange={(p) => { page = p; loadJournals(); }} />
	{/if}
</div>

<style>
	.page { max-width: 1100px; margin: 0 auto; padding: 16px; }
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

	.journals-table {
		width: 100%; border-collapse: collapse;
		background: var(--card); border: 1px solid var(--border); border-radius: 6px;
	}
	.journals-table thead th {
		background: #f5f4f1; padding: 8px 10px; text-align: left;
		font-size: 0.85rem; font-weight: 600; color: var(--muted);
		border-bottom: 2px solid var(--border); white-space: nowrap;
	}
	.journals-table thead th.num { text-align: right; }
	.journals-table thead th.sortable { cursor: pointer; user-select: none; }
	.journals-table thead th.sortable:hover { color: var(--accent); }
	.journals-table tbody tr { border-bottom: 1px solid #f0efec; }
	.journals-table tbody tr:last-child { border-bottom: none; }
	.journals-table tbody tr:hover { background: #fafaf8; }
	.journals-table td { padding: 7px 10px; font-size: 0.95rem; vertical-align: top; }
	.journals-table td.num {
		text-align: right; font-variant-numeric: tabular-nums; color: var(--muted);
	}
	.issn-cell { color: var(--muted); font-size: 0.85rem; font-variant-numeric: tabular-nums; white-space: nowrap; }
	.muted { color: var(--muted); }
	.no-results { text-align: center; color: var(--muted); padding: 30px; }

	.journal-link { color: var(--accent); text-decoration: none; font-weight: 500; }
	.journal-link:hover { text-decoration: underline; }
	.badge-doaj {
		font-size: 0.7rem; padding: 1px 5px; background: #2e7d32;
		color: white; border-radius: 8px; margin-left: 6px;
		vertical-align: middle; font-weight: 600;
	}
	.badge-pred {
		font-size: 0.7rem; padding: 1px 5px; background: #c0392b;
		color: white; border-radius: 8px; margin-left: 4px;
		vertical-align: middle; font-weight: 600;
	}
</style>
