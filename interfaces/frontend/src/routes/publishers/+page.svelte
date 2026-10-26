<script lang="ts">
	import IconButton from '#lib/components/IconButton.svelte';
	import { institution, pageTitle } from '#lib/institution.svelte.js';
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { api, ApiError, publishers as publishersApi } from '#lib/api/index.js';
	import { useDebouncedSearch } from '#lib/composables/useDebouncedSearch.svelte.js';
	import PublishersListView from '#lib/components/PublishersListView.svelte';
	import Modal from '#lib/components/Modal.svelte';
	import Picker from '#lib/components/Picker.svelte';
	import { toast } from '#lib/dialogs.svelte.js';
	import { isAdmin } from '#lib/session.svelte.js';

	import type { components } from '#lib/api/schema.js';
	type Publisher = components['schemas']['PublisherListItem'];
	type EnumOption = components['schemas']['EnumOption'];
	type Country = components['schemas']['CountryOut'];

	let publisherTypes: EnumOption[] = $state([]);
	let countries: Country[] = $state([]);

	// Clé d'API utilisée pour forcer le reload de PublishersListView après une édition ou fusion (incrément invalide le cache).
	let viewVersion = $state(0);
	const apiKey = $derived(`publishers-list-${viewVersion}`);
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
				`/api/publishers?search=${encodeURIComponent(q)}&sort=serials_desc&per_page=10`,
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

	type BlockingSerial = components['schemas']['BlockingSerialItem'];

	let blockingSerials: BlockingSerial[] | null = $state(null);
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
				if (body?.blocking_serials?.length) {
					blockingSerials = body.blocking_serials;
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
		blockingSerials = null;
		blockingDetail = '';
	}

	onMount(async () => {
		if (!isAdmin()) return;
		publisherTypes = await api<EnumOption[]>('/api/publishers/types');
		countries = await api<Country[]>('/api/countries');
	});
</script>

<svelte:head>
	<title>{pageTitle("Éditeurs")}</title>
</svelte:head>

<h1>Éditeurs</h1>
<p class="hint">
	Liste des éditeurs des publications en série observées sur les publications du périmètre
	{institution.name}. Cliquer sur un éditeur pour explorer ses publications en série et ses
	publications.
</p>

{#if blockingSerials}
	<div class="blocking-panel" role="alert">
		<div class="blocking-header">
			<strong>Fusion impossible</strong>
			<button class="btn btn-sm" onclick={dismissBlocking}>Fermer</button>
		</div>
		<p class="blocking-detail">{blockingDetail}</p>
		<p class="muted">
			Fusionner d'abord ces paires de publications en série dans l'<a href={resolve('admin/serials')}>administration des publications en série</a>,
			puis relancer la fusion des éditeurs.
		</p>
		<table class="blocking-table">
			<thead>
				<tr>
					<th>Publication en série (cible)</th>
					<th>Publication en série (source)</th>
					<th>Raison</th>
				</tr>
			</thead>
			<tbody>
				{#each blockingSerials as bj (bj.target_serial_id + '_' + bj.source_serial_id)}
					<tr>
						<td>
							<a href={resolve(`journals/${bj.target_serial_id}`)} target="_blank" rel="noopener">
								{bj.target_title}
							</a>
							<span class="muted">#{bj.target_serial_id}</span>
						</td>
						<td>
							<a href={resolve(`journals/${bj.source_serial_id}`)} target="_blank" rel="noopener">
								{bj.source_title}
							</a>
							<span class="muted">#{bj.source_serial_id}</span>
						</td>
						<td>{bj.reason}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{/if}

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
				{r.name} <span class="muted">({r.serial_count} publications en série, {r.publication_count} publis)</span>
			{/snippet}
		</Picker>
	{:else}
		<IconButton icon="edit" label="Modifier" onclick={() => openEdit(pub)} />
		<button class="btn btn-sm btn-merge" onclick={() => openMerge(pub.id)}>Fusionner…</button>
	{/if}
{/snippet}

<PublishersListView
	{apiKey}
	urlSync
	actionCell={isAdmin() ? actionCell : undefined}
/>

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
	h1 { margin: 0 0 8px; font-size: 1.5rem; }
	.hint { color: var(--muted); font-size: 0.9rem; margin: 0 0 16px; }

	.btn-merge { font-size: 0.8rem; color: var(--accent); background: none; border: 1px solid var(--border); border-radius: var(--radius); cursor: pointer; padding: 2px 8px; }
	.btn-merge:hover { background: var(--accent-light); }

	.muted { color: var(--muted); }

	.blocking-panel {
		background: var(--warning-light); border: 1px solid var(--warning);
		border-radius: var(--radius); padding: 12px 16px; margin: 12px 0;
	}
	.blocking-header {
		display: flex; justify-content: space-between; align-items: center;
		margin-bottom: 6px;
	}
	.blocking-detail { margin: 4px 0 8px; font-size: 0.95rem; }
	.blocking-table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
	.blocking-table th {
		text-align: left; padding: 4px 8px; font-weight: 600; color: var(--muted);
		border-bottom: 1px solid var(--warning);
	}
	.blocking-table td { padding: 6px 8px; border-bottom: 1px solid color-mix(in srgb, var(--warning) 40%, white); vertical-align: top; }
	.blocking-table tr:last-child td { border-bottom: none; }
</style>
