<script lang="ts">
	import { pageTitle } from '$lib/institution.svelte';
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { api, ApiError, publishers as publishersApi } from '$lib/api';
	import { useDebouncedSearch } from '$lib/composables/useDebouncedSearch.svelte';
	import PublishersListView from '$lib/components/PublishersListView.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import Picker from '$lib/components/Picker.svelte';
	import { toast } from '$lib/dialogs.svelte';

	import type { components } from '$lib/api/schema';
	type Publisher = components['schemas']['PublisherListItem'];
	type EnumOption = components['schemas']['EnumOption'];
	type Country = components['schemas']['CountryOut'];

	let publisherTypes: EnumOption[] = $state([]);
	let countries: Country[] = $state([]);

	// Clé d'API utilisée pour forcer le reload de PublishersListView après une édition ou fusion (incrément invalide le cache).
	let viewVersion = $state(0);
	const apiKey = $derived(`admin-publishers-${viewVersion}`);
	function reload() { viewVersion += 1; }

	// Modal édition
	let editModal: {
		id: number;
		name: string;
		country: string;
		publisher_type: string;
	} | null = $state(null);

	function openEdit(pub: Publisher) {
		editModal = {
			id: pub.id,
			name: pub.name,
			country: (pub.country || '').toUpperCase(),
			publisher_type: pub.publisher_type,
		};
	}

	async function saveEdit() {
		if (!editModal) return;
		const body: Record<string, any> = {};
		if (editModal.name.trim()) body.name = editModal.name.trim();
		body.country = editModal.country.trim() || null;
		body.publisher_type = editModal.publisher_type;
		try {
			await publishersApi.update(editModal.id, body);
			editModal = null;
			reload();
		} catch (e: any) {
			const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
			toast('Erreur : ' + msg, 'error');
		}
	}

	// Merge state : recherche avec debounce + cible en cours de fusion
	let mergeTargetId: number | null = $state(null);
	const mergeSearch = useDebouncedSearch<Publisher>({
		search: async (q, request) => {
			const data = await request<{ publishers: Publisher[] }>(
				// Les éditeurs les plus fournis en revues d'abord : la cible d'une fusion est rarement une variante isolée.
				`/api/publishers?search=${encodeURIComponent(q)}&sort=journals_desc&per_page=10`,
			);
			return data.publishers;
		},
		transform: (results) => results.filter((p) => p.id !== mergeTargetId),
	});

	function openMerge(id: number) {
		mergeTargetId = id;
		mergeSearch.clear();
	}

	function closeMerge() {
		mergeTargetId = null;
		mergeSearch.clear();
	}

	type BlockingJournal = components['schemas']['BlockingJournalItem'];

	let blockingJournals: BlockingJournal[] | null = $state(null);
	let blockingDetail = $state('');

	async function doMerge(sourceId: number) {
		if (!mergeTargetId) return;
		try {
			await publishersApi.merge(mergeTargetId, sourceId);
			closeMerge();
			reload();
		} catch (e: any) {
			if (e instanceof ApiError) {
				const body = e.detail as Partial<components['schemas']['PublisherMergeBlockedResponse']>;
				if (body?.blocking_journals?.length) {
					blockingJournals = body.blocking_journals;
					blockingDetail = body.detail ?? '';
					return;
				}
				toast(body?.detail || `HTTP ${e.status}`, 'error');
				return;
			}
			toast('Erreur réseau : ' + e.message, 'error');
		}
	}

	function dismissBlocking() {
		blockingJournals = null;
		blockingDetail = '';
	}

	onMount(async () => {
		publisherTypes = await api<EnumOption[]>('/api/publishers/types');
		countries = await api<Country[]>('/api/countries');
	});
</script>

<svelte:head><title>{pageTitle("Éditeurs")}</title></svelte:head>

<h2>Éditeurs</h2>

{#if blockingJournals}
	<div class="blocking-panel" role="alert">
		<div class="blocking-header">
			<strong>Fusion impossible</strong>
			<button class="btn btn-sm" onclick={dismissBlocking}>Fermer</button>
		</div>
		<p class="blocking-detail">{blockingDetail}</p>
		<p class="muted">
			Fusionner d'abord ces paires de revues côté <a href="{base}/admin/journals">admin Revues</a>,
			puis relancer la fusion des éditeurs.
		</p>
		<table class="blocking-table">
			<thead>
				<tr>
					<th>Revue (cible)</th>
					<th>Revue (source)</th>
					<th>Raison</th>
				</tr>
			</thead>
			<tbody>
				{#each blockingJournals as bj (bj.target_journal_id + '_' + bj.source_journal_id)}
					<tr>
						<td>
							<a href="{base}/journals/{bj.target_journal_id}" target="_blank" rel="noopener">
								{bj.target_title}
							</a>
							<span class="muted">#{bj.target_journal_id}</span>
						</td>
						<td>
							<a href="{base}/journals/{bj.source_journal_id}" target="_blank" rel="noopener">
								{bj.source_title}
							</a>
							<span class="muted">#{bj.source_journal_id}</span>
						</td>
						<td>{bj.reason}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

<PublishersListView {apiKey}>
	{#snippet actionCell(pub: Publisher)}
		{#if mergeTargetId === pub.id}
			<Picker
				floating
				align="end"
				minLength={2}
				placeholder="Fusionner avec…"
				search={mergeSearch.query}
				onsearch={mergeSearch.setQuery}
				loading={mergeSearch.loading}
				results={mergeSearch.results}
				onpick={(r) => doMerge(r.id)}
				onclose={closeMerge}
			>
				{#snippet item(r)}
					{r.name} <span class="muted">({r.journal_count} revues, {r.pub_count} publis)</span>
				{/snippet}
			</Picker>
		{:else}
			<button class="btn btn-sm" onclick={() => openEdit(pub)}>Modifier</button>
			<button class="btn btn-sm btn-merge" onclick={() => openMerge(pub.id)}>Fusionner…</button>
		{/if}
	{/snippet}
</PublishersListView>

{#if editModal}
<Modal title="Modifier l'éditeur" maxWidth="460px" onclose={() => editModal = null} onsubmit={saveEdit}>
		<label>Nom <input bind:value={editModal.name} /></label>
		<label>Pays <select bind:value={editModal.country}>
			<option value="">— Aucun —</option>
			{#each countries as c (c.code)}
				<option value={c.code.toUpperCase()}>{c.name} ({c.code.toUpperCase()})</option>
			{/each}
		</select></label>
		<label>Type <select bind:value={editModal.publisher_type}>
			{#each publisherTypes as opt (opt.value)}
				<option value={opt.value}>{opt.label_fr}</option>
			{/each}
		</select></label>
		{#snippet actions()}
			<button class="btn" onclick={() => editModal = null}>Annuler</button>
			<button class="btn btn-primary" onclick={saveEdit}>Enregistrer</button>
		{/snippet}
</Modal>
{/if}

<style>
	h2 { font-size: 1.2rem; font-weight: 600; margin: 0 0 12px; }

	.btn-merge { font-size: 0.8rem; color: var(--accent); background: none; border: 1px solid var(--border); border-radius: 3px; cursor: pointer; padding: 2px 8px; }
	.btn-merge:hover { background: var(--accent-light); }

	.muted { color: var(--muted); }

	.blocking-panel {
		background: #fef3e0; border: 1px solid #e8a838;
		border-radius: 6px; padding: 12px 16px; margin: 12px 0;
	}
	.blocking-header {
		display: flex; justify-content: space-between; align-items: center;
		margin-bottom: 6px;
	}
	.blocking-detail { margin: 4px 0 8px; font-size: 0.95rem; }
	.blocking-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
	.blocking-table th {
		text-align: left; padding: 4px 8px; font-weight: 600; color: var(--muted);
		border-bottom: 1px solid #e8a838;
	}
	.blocking-table td { padding: 6px 8px; border-bottom: 1px solid #f0d9b0; vertical-align: top; }
	.blocking-table tr:last-child td { border-bottom: none; }
</style>
