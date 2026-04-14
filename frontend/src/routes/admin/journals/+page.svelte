<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { api } from '$lib/api';
	import Pagination from '$lib/components/Pagination.svelte';

	interface Journal {
		id: number;
		title: string;
		issn: string | null;
		eissn: string | null;
		issnl: string | null;
		publisher_id: number | null;
		pub_name: string | null;
		openalex_id: string | null;
		is_in_doaj: boolean;
		is_predatory: boolean;
		apc_amount: number | null;
		apc_currency: string | null;
		oa_model: string | null;
		pub_count: number;
	}

	let journals: Journal[] = $state([]);
	let total = $state(0);
	let page = $state(1);
	let pages = $state(1);
	let perPage = 50;
	let search = $state('');
	let sort = $state('-pubs');
	let searchTimer: ReturnType<typeof setTimeout>;

	// Merge state
	let mergeTargetId: number | null = $state(null);
	let mergeQuery = $state('');
	let mergeResults: Journal[] = $state([]);
	let mergeLoading = $state(false);
	let mergeTimer: ReturnType<typeof setTimeout>;

	async function load() {
		const params = new URLSearchParams({ page: String(page), per_page: String(perPage), sort });
		if (search) params.set('search', search);
		const data = await api<any>(`/api/journals?${params}`);
		journals = data.journals;
		total = data.total;
		pages = data.pages;
	}

	function onSearch(value: string) {
		search = value;
		clearTimeout(searchTimer);
		searchTimer = setTimeout(() => { page = 1; load(); }, 300);
	}

	function setSort(s: string) { sort = s; page = 1; load(); }

	function formatIssns(j: Journal): string {
		const parts = [];
		if (j.issn) parts.push(j.issn);
		if (j.eissn) parts.push(j.eissn);
		if (j.issnl && j.issnl !== j.issn && j.issnl !== j.eissn) parts.push(`L:${j.issnl}`);
		return parts.join(' / ');
	}

	// Modal édition
	let editModal: {
		id: number; title: string; issn: string; eissn: string; issnl: string;
		doi_prefix: string; oa_model: string; journal_type: string;
		is_academic: boolean; is_predatory: boolean; is_in_doaj: boolean;
		apc_amount: string; notes: string;
	} | null = $state(null);

	function openEdit(j: Journal) {
		editModal = {
			id: j.id, title: j.title,
			issn: j.issn || '', eissn: j.eissn || '', issnl: j.issnl || '',
			doi_prefix: '', oa_model: j.oa_model || '',
			journal_type: 'journal', is_academic: true,
			is_predatory: j.is_predatory, is_in_doaj: j.is_in_doaj,
			apc_amount: j.apc_amount ? String(j.apc_amount) : '',
			notes: '',
		};
	}

	async function saveEdit() {
		if (!editModal) return;
		const body: Record<string, any> = {};
		body.title = editModal.title.trim();
		body.issn = editModal.issn.trim() || null;
		body.eissn = editModal.eissn.trim() || null;
		body.issnl = editModal.issnl.trim() || null;
		body.doi_prefix = editModal.doi_prefix.trim() || null;
		body.oa_model = editModal.oa_model || null;
		body.journal_type = editModal.journal_type;
		body.is_academic = editModal.is_academic;
		body.is_predatory = editModal.is_predatory;
		body.is_in_doaj = editModal.is_in_doaj;
		body.apc_amount = editModal.apc_amount ? parseFloat(editModal.apc_amount) : null;
		if (editModal.notes.trim()) body.notes = editModal.notes.trim();
		try {
			const res = await fetch(base + '/api/journals/' + editModal.id, {
				method: 'PUT', headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body),
			});
			if (!res.ok) throw new Error(await res.text());
			editModal = null;
			await load();
		} catch (e: any) { alert('Erreur : ' + e.message); }
	}

	// Merge
	function openMerge(id: number) {
		mergeTargetId = id;
		mergeQuery = '';
		mergeResults = [];
	}

	function closeMerge() { mergeTargetId = null; }

	function onMergeSearch(query: string) {
		mergeQuery = query;
		clearTimeout(mergeTimer);
		if (query.length < 2) { mergeResults = []; return; }
		mergeLoading = true;
		mergeTimer = setTimeout(async () => {
			const data = await api<any>(`/api/journals?search=${encodeURIComponent(query)}&per_page=10`);
			mergeResults = data.journals.filter((j: Journal) => j.id !== mergeTargetId);
			mergeLoading = false;
		}, 300);
	}

	async function doMerge(sourceId: number) {
		if (!mergeTargetId) return;
		try {
			const res = await fetch(`${base}/api/journals/${mergeTargetId}/merge`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ source_id: sourceId }),
			});
			if (!res.ok) {
				const text = await res.text();
				try { alert(JSON.parse(text).detail); } catch { alert(`Erreur ${res.status}: ${text}`); }
				return;
			}
			closeMerge();
			await load();
		} catch (e: any) {
			alert('Erreur réseau : ' + e.message);
		}
	}

	onMount(load);
</script>

<svelte:head><title>Revues — Bibliométrie UCA</title></svelte:head>

<h2>Revues <span class="count">({total})</span></h2>

<div class="toolbar">
	<input type="text" placeholder="Rechercher une revue…" value={search}
		oninput={(e) => onSearch((e.target as HTMLInputElement).value)} class="search-input" />
</div>

<table class="data-table">
	<thead>
		<tr>
			<th class="sortable" onclick={() => setSort(sort === 'title' ? '-title' : 'title')}>
				Titre {sort === 'title' ? '▲' : sort === '-title' ? '▼' : ''}
			</th>
			<th>ISSN</th>
			<th class="sortable" onclick={() => setSort(sort === 'publisher' ? '-publisher' : 'publisher')}>
				Éditeur {sort === 'publisher' ? '▲' : sort === '-publisher' ? '▼' : ''}
			</th>
			<th class="sortable num" onclick={() => setSort(sort === '-pubs' ? 'pubs' : '-pubs')}>
				Publis {sort === '-pubs' ? '▲' : sort === 'pubs' ? '▼' : ''}
			</th>
			<th></th>
		</tr>
	</thead>
	<tbody>
		{#each journals as j (j.id)}
			<tr class:predatory={j.is_predatory}>
				<td>
					<span class="journal-title">{j.title}</span>
					{#if j.is_predatory}<span class="badge-pred">prédateur</span>{/if}
					{#if j.is_in_doaj}<span class="badge-doaj">DOAJ</span>{/if}
				</td>
				<td class="issn-cell">{formatIssns(j)}</td>
				<td class="muted">{j.pub_name || ''}</td>
				<td class="num">{j.pub_count}</td>
				<td class="actions">
					{#if mergeTargetId === j.id}
						<div class="merge-search">
							<input type="text" placeholder="Fusionner avec…" value={mergeQuery}
								oninput={(e) => onMergeSearch((e.target as HTMLInputElement).value)}
								class="merge-input" />
							<button class="btn btn-sm" onclick={closeMerge}>Annuler</button>
							{#if mergeLoading}
								<div class="merge-results"><span class="muted">Recherche…</span></div>
							{:else if mergeResults.length > 0}
								<div class="merge-results">
									{#each mergeResults as r (r.id)}
										<button class="merge-result" onclick={() => doMerge(r.id)}>
											{r.title}
											{#if r.pub_name}<span class="muted"> — {r.pub_name}</span>{/if}
											<span class="muted"> ({r.pub_count} publis)</span>
										</button>
									{/each}
								</div>
							{:else if mergeQuery.length >= 2}
								<div class="merge-results"><span class="muted">Aucun résultat</span></div>
							{/if}
						</div>
					{:else}
						<button class="btn btn-sm" onclick={() => openEdit(j)}>Modifier</button>
						<button class="btn btn-sm btn-merge" onclick={() => openMerge(j.id)}>Fusionner…</button>
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
		<h3>Modifier la revue</h3>
		<label>Titre</label>
		<input bind:value={editModal.title} />
		<div style="display:flex;gap:8px">
			<div style="flex:1"><label>ISSN</label><input bind:value={editModal.issn} placeholder="1234-5678" /></div>
			<div style="flex:1"><label>eISSN</label><input bind:value={editModal.eissn} /></div>
			<div style="flex:1"><label>ISSN-L</label><input bind:value={editModal.issnl} /></div>
		</div>
		<label>DOI prefix</label>
		<input bind:value={editModal.doi_prefix} placeholder="ex: 10.1038/s41586" />
		<div style="display:flex;gap:8px">
			<div style="flex:1">
				<label>Modèle OA</label>
				<select bind:value={editModal.oa_model}>
					<option value="">(non renseigné)</option>
					<option value="subscription">Abonnement</option>
					<option value="full_oa">Full OA (gold/diamond)</option>
					<option value="repository">Archive/dépôt</option>
				</select>
			</div>
			<div style="flex:1">
				<label>Type</label>
				<select bind:value={editModal.journal_type}>
					<option value="journal">Revue</option>
					<option value="proceedings">Proceedings</option>
					<option value="repository">Archive/dépôt</option>
					<option value="book_series">Série d'ouvrages</option>
					<option value="preprint_server">Serveur de preprints</option>
					<option value="media">Média</option>
				</select>
			</div>
		</div>
		<div style="display:flex;gap:12px;margin-top:8px">
			<label><input type="checkbox" bind:checked={editModal.is_academic} /> Académique</label>
			<label><input type="checkbox" bind:checked={editModal.is_predatory} /> Prédateur</label>
			<label><input type="checkbox" bind:checked={editModal.is_in_doaj} /> DOAJ</label>
		</div>
		<label>APC (€)</label>
		<input bind:value={editModal.apc_amount} placeholder="ex: 2500" type="number" />
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

	.journal-title { font-weight: 500; }
	.issn-cell { font-family: "JetBrains Mono", monospace; font-size: 0.8rem; white-space: nowrap; }
	.muted { color: var(--muted); font-size: 0.85rem; }
	.predatory td { background: #fff0f0; }
	.badge-pred { font-size: 0.7rem; padding: 1px 5px; background: #d32f2f; color: white; border-radius: 8px; margin-left: 6px; }
	.badge-doaj { font-size: 0.7rem; padding: 1px 5px; background: #2e7d32; color: white; border-radius: 8px; margin-left: 6px; }

	.actions { white-space: nowrap; position: relative; }
	.btn-merge { font-size: 0.8rem; color: var(--accent); background: none; border: 1px solid var(--border); border-radius: 3px; cursor: pointer; padding: 2px 8px; }
	.btn-merge:hover { background: var(--accent-light); }

	.merge-search { display: inline-block; position: relative; }
	.merge-input { width: 160px; padding: 3px 6px; font-size: 0.85rem; border: 1px solid var(--accent); border-radius: 3px; font-family: inherit; }
	.merge-results { position: absolute; right: 0; top: 100%; z-index: 10; border: 1px solid var(--border); border-radius: 4px; margin-top: 2px; max-height: 200px; overflow-y: auto; background: white; min-width: 350px; box-shadow: 0 2px 8px rgba(0,0,0,0.12); }
	.merge-result { display: block; width: 100%; padding: 5px 8px; font-size: 0.85rem; cursor: pointer; background: none; border: none; text-align: left; font-family: inherit; }
	.merge-result:hover { background: var(--warning-light, #fff3e0); }
</style>
