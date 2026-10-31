<script lang="ts">
	import PageHeader from '#lib/components/PageHeader.svelte';
	import IconButton from '#lib/components/IconButton.svelte';
	import { onMount } from 'svelte';
	import { api, serials as serialsApi, errorMessage } from '#lib/api/index.js';
	import { useDebouncedSearch } from '#lib/composables/useDebouncedSearch.svelte.js';
	import HubTabs from '#lib/components/HubTabs.svelte';
	import SerialsListView from '#lib/components/SerialsListView.svelte';
	import SerialDuplicatesList from './SerialDuplicatesList.svelte';
	import LikelyProceedingsList from './LikelyProceedingsList.svelte';
	import DoiNamespaceConflictsList from './DoiNamespaceConflictsList.svelte';
	import { mergeSerial } from './mergeSerial';
	import Modal from '#lib/components/Modal.svelte';
	import Picker from '#lib/components/Picker.svelte';
	import { confirmDialog, toast } from '#lib/dialogs.svelte.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { useTabParam } from '#lib/composables/useTabParam.svelte.js';
	import type { components } from '#lib/api/schema.js';

	type Serial = components['schemas']['SerialListItem'];
	type SerialDetail = components['schemas']['SerialDetailResponse'];
	type SerialListResponse = components['schemas']['SerialListResponse'];
	type EnumOption = components['schemas']['EnumOption'];

	let serialTypes: EnumOption[] = $state([]);
	let oaModels: EnumOption[] = $state([]);

	// Onglets de la session admin : la liste, une file par type de doublon potentiel, la file des recueils d'actes probables, puis celle des publications en série que contredit l'espace de noms DOI. L'onglet ouvert se garde dans l'URL (`?tab=`).
	type TabKey = 'all' | 'same-titles' | 'likely-proceedings' | 'doi-namespace-conflicts';
	const QUEUES: TabKey[] = ['same-titles', 'likely-proceedings', 'doi-namespace-conflicts'];
	const tab = useTabParam(QUEUES, isAdmin);
	let sameTitleCount = $state(0);
	let likelyProceedingsCount = $state(0);
	let doiNamespaceConflictsCount = $state(0);

	async function queueCount(queue: Exclude<TabKey, 'all'>): Promise<number> {
		try {
			return (await api<{ total: number }>(`/api/serials/${queue}/count`)).total;
		} catch {
			return 0;
		}
	}

	async function loadQueueCounts() {
		[sameTitleCount, likelyProceedingsCount, doiNamespaceConflictsCount] = await Promise.all([
			queueCount('same-titles'),
			queueCount('likely-proceedings'),
			queueCount('doi-namespace-conflicts'),
		]);
	}

	// Clé d'API utilisée pour invalider le cache de SerialsListView après une édition ou fusion (force un reload via incrément).
	let viewVersion = $state(0);
	const apiKey = $derived(`journals-list-${viewVersion}`);
	function reload() { viewVersion += 1; }

	// Merge state : recherche avec debounce + cible en cours de fusion
	let mergeTargetId: number | null = $state(null);
	let mergeTargetType = $state('journal');
	const mergeSearch = useDebouncedSearch<Serial>({
		search: async (q, request) => {
			const data = await request<SerialListResponse>(
				// Les publications en série les plus fournies en publications d'abord, comme pour la fusion d'éditeurs.
				`/api/serials?search=${encodeURIComponent(q)}&sort=publications_desc&per_page=10`,
			);
			return data.serials;
		},
		transform: (results) => results.filter((j) => j.id !== mergeTargetId),
	});

	// Modal édition
	let editModal: {
		id: number; title: string;
		oa_model: string;
		serial_type: string; original_serial_type: string;
		is_academic: boolean;
	} | null = $state(null);

	async function openEdit(j: Serial) {
		// La ligne de liste ne porte que le résumé ; on charge le détail pour pré-remplir le formulaire.
		let detail: SerialDetail;
		try {
			detail = await api<SerialDetail>(`/api/serials/${j.id}`);
		} catch (e) {
			toast('Erreur lors du chargement de la publication en série : ' + errorMessage(e), 'error');
			return;
		}
		const jt = detail.serial_type || 'journal';
		editModal = {
			id: detail.id, title: detail.title,
			oa_model: detail.oa_model || '',
			serial_type: jt, original_serial_type: jt,
			is_academic: detail.is_academic ?? true,
		};
	}

	async function saveEdit() {
		if (!editModal) return;

		// Si le serial_type change, prévisualiser l'impact et demander confirmation.
		// Le message reste générique : le compte est exact (publications dont le doc_type change), mais la nouvelle valeur dépend de l'agrégation complète des sources de chaque publication, pas seulement du serial_type — on ne peut pas la prédire ici.
		if (editModal.serial_type !== editModal.original_serial_type) {
			try {
				const impact = await serialsApi.typeChangeImpact(editModal.id, editModal.serial_type);
				if (impact.count > 0) {
					const plural = impact.count > 1 ? 's' : '';
					const msg = `Ce changement entraînera un recalcul de la métadonnée « type de document » sur ${impact.count} publication${plural}. Continuer ?`;
					if (!(await confirmDialog({ message: msg }))) return;
				}
			} catch (e) {
				toast('Erreur lors du calcul d\'impact : ' + errorMessage(e), 'error');
				return;
			}
		}

		const body: Record<string, any> = {};
		body.title = editModal.title.trim();
		body.oa_model = editModal.oa_model || null;
		body.serial_type = editModal.serial_type;
		body.is_academic = editModal.is_academic;
		try {
			await serialsApi.update(editModal.id, body);
			editModal = null;
			reload();
			// Une modification de titre ou de type fait entrer ou sortir la publication en série des files.
			loadQueueCounts();
		} catch (e) {
			toast('Erreur : ' + errorMessage(e), 'error');
		}
	}

	// Merge
	function openMerge(j: Serial) {
		mergeTargetId = j.id;
		mergeTargetType = j.serial_type || 'journal';
		mergeSearch.clear();
	}

	function closeMerge() {
		mergeTargetId = null;
		mergeSearch.clear();
	}

	async function doMerge(sourceId: number) {
		if (!mergeTargetId) return;
		if (await mergeSerial({ id: mergeTargetId, serial_type: mergeTargetType }, sourceId)) {
			closeMerge();
			reload();
			loadQueueCounts();
		}
	}

	onMount(async () => {
		if (!isAdmin()) return;
		loadQueueCounts();
		[serialTypes, oaModels] = await Promise.all([
			api<EnumOption[]>('/api/serials/types'),
			api<EnumOption[]>('/api/serials/oa-models')
		]);
	});
</script>

<PageHeader title="Publications en série" hidden />

{#if isAdmin()}
	<HubTabs
		tabs={[
			{ key: 'all', label: 'Toutes les publications en série' },
			{ key: 'same-titles', label: 'Titres identiques', count: sameTitleCount },
			{ key: 'likely-proceedings', label: "Recueils d'actes probables", count: likelyProceedingsCount },
			{ key: 'doi-namespace-conflicts', label: 'Contredites par le DOI', count: doiNamespaceConflictsCount },
		]}
		active={tab.current}
		onselect={(key) => tab.select(key as TabKey)}
	/>
{/if}

{#snippet actionCell(j: Serial)}
	{#if mergeTargetId === j.id}
		<Picker
			floating
			align="end"
			minLength={2}
			placeholder="Fusionner avec"
			search={mergeSearch.query}
			onsearch={mergeSearch.setQuery}
			loading={mergeSearch.loading}
			results={mergeSearch.results}
			onpick={(r) => doMerge(r.id)}
			onclose={closeMerge}
		>
			{#snippet item(r)}
				{r.title}
				{#if r.publisher_name}<span class="muted"> — {r.publisher_name}</span>{/if}
				<span class="muted"> ({r.publication_count} publis)</span>
			{/snippet}
		</Picker>
	{:else}
		<IconButton icon="edit" label="Modifier" onclick={() => openEdit(j)} />
		<button class="btn btn-sm btn-merge" onclick={() => openMerge(j)}>Fusionner…</button>
	{/if}
{/snippet}

{#if tab.current === 'same-titles'}
	<SerialDuplicatesList
		url="/api/serials/same-titles"
		intro="Deux publications en série de même titre qui ont chacune un ISSN sont des homonymes probables : elles n'apparaissent pas ici."
		onchange={loadQueueCounts}
	/>
{:else if tab.current === 'likely-proceedings'}
	<LikelyProceedingsList onchange={loadQueueCounts} />
{:else if tab.current === 'doi-namespace-conflicts'}
	<DoiNamespaceConflictsList onchange={loadQueueCounts} />
{:else}
	<SerialsListView {apiKey} urlSync actionCell={isAdmin() ? actionCell : undefined} />
{/if}

{#if editModal}
<Modal title="Modifier la publication en série" maxWidth="720px" onclose={() => editModal = null} onsubmit={saveEdit}>
		<label>Titre <input bind:value={editModal.title} /></label>
		<div style="display:flex;gap:8px">
			<div style="flex:1">
				<label>Modèle OA <select bind:value={editModal.oa_model}>
					<option value="">(non renseigné)</option>
					{#each oaModels as opt (opt.value)}
						<option value={opt.value}>{opt.label_fr}</option>
					{/each}
				</select></label>
			</div>
			<div style="flex:1">
				<label>Type <select bind:value={editModal.serial_type}>
					{#each serialTypes as opt (opt.value)}
						<option value={opt.value}>{opt.label_fr}</option>
					{/each}
				</select></label>
			</div>
		</div>
		<div style="display:flex;gap:12px;margin-top:8px">
			<label class="checkbox-row"><input type="checkbox" bind:checked={editModal.is_academic} /> Académique</label>
		</div>
		{#snippet actions()}
			<button class="btn" onclick={() => editModal = null}>Annuler</button>
			<button class="btn btn-primary" onclick={saveEdit}>Enregistrer</button>
		{/snippet}
</Modal>
{/if}

<style>


	.muted { color: var(--muted); }
</style>
