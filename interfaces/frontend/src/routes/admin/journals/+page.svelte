<script lang="ts">
	import { pageTitle } from '$lib/institution.svelte';
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { api, ApiError, journals as journalsApi } from '$lib/api';
	import { useDebouncedSearch } from '$lib/composables/useDebouncedSearch.svelte';
	import HubTabs from '$lib/components/HubTabs.svelte';
	import JournalsListView from '$lib/components/JournalsListView.svelte';
	import JournalDuplicatesList from './JournalDuplicatesList.svelte';
	import LikelyProceedingsList from './LikelyProceedingsList.svelte';
	import DoiNamespaceConflictsList from './DoiNamespaceConflictsList.svelte';
	import { mergeJournal } from './mergeJournal';
	import Modal from '$lib/components/Modal.svelte';
	import JournalIssnsEditor, { type EditedIssn } from './JournalIssnsEditor.svelte';
	import Picker from '$lib/components/Picker.svelte';
	import { confirmDialog, toast } from '$lib/dialogs.svelte';
	import type { components } from '$lib/api/schema';

	type Journal = components['schemas']['JournalListItem'];
	type JournalDetail = components['schemas']['JournalDetailResponse'];
	type JournalListResponse = components['schemas']['JournalListResponse'];
	type EnumOption = components['schemas']['EnumOption'];

	let journalTypes: EnumOption[] = $state([]);
	let oaModels: EnumOption[] = $state([]);

	// Onglets : la liste des revues, une file par type de doublon potentiel, la file des recueils d'actes probables, puis celle des revues que contredit l'espace de noms DOI. L'onglet ouvert se garde dans l'URL (`?tab=`).
	type TabKey = 'all' | 'same-titles' | 'shared-issns' | 'likely-proceedings' | 'doi-namespace-conflicts';
	const QUEUES: TabKey[] = ['same-titles', 'shared-issns', 'likely-proceedings', 'doi-namespace-conflicts'];
	let tab = $state<TabKey>('all');
	let sameTitleCount = $state(0);
	let sharedIssnCount = $state(0);
	let likelyProceedingsCount = $state(0);
	let doiNamespaceConflictsCount = $state(0);

	async function queueCount(queue: Exclude<TabKey, 'all'>): Promise<number> {
		try {
			return (await api<{ total: number }>(`/api/journals/${queue}/count`)).total;
		} catch {
			return 0;
		}
	}

	async function loadQueueCounts() {
		[sameTitleCount, sharedIssnCount, likelyProceedingsCount, doiNamespaceConflictsCount] = await Promise.all([
			queueCount('same-titles'),
			queueCount('shared-issns'),
			queueCount('likely-proceedings'),
			queueCount('doi-namespace-conflicts'),
		]);
	}

	function selectTab(t: TabKey) {
		tab = t;
		const url = new URL(window.location.href);
		if (t === 'all') url.searchParams.delete('tab');
		else url.searchParams.set('tab', t);
		replaceState(url, {});
	}

	// Clé d'API utilisée pour invalider le cache de JournalsListView après une édition ou fusion (force un reload via incrément).
	let viewVersion = $state(0);
	const apiKey = $derived(`admin-journals-${viewVersion}`);
	function reload() { viewVersion += 1; }

	// Merge state : recherche avec debounce + cible en cours de fusion
	let mergeTargetId: number | null = $state(null);
	let mergeTargetType = $state('journal');
	const mergeSearch = useDebouncedSearch<Journal>({
		search: async (q) => {
			const data = await api<JournalListResponse>(
				// Les revues les plus fournies en publications d'abord, comme pour la fusion d'éditeurs.
				`/api/journals?search=${encodeURIComponent(q)}&sort=pubs_desc&per_page=10`,
			);
			return data.journals;
		},
		transform: (results) => results.filter((j) => j.id !== mergeTargetId),
	});

	// Modal édition
	let editModal: {
		id: number; title: string; issns: EditedIssn[];
		oa_model: string;
		journal_type: string; original_journal_type: string;
		is_academic: boolean; is_in_doaj: boolean;
		apc_amount: string;
	} | null = $state(null);

	async function openEdit(j: Journal) {
		// La ligne de liste ne porte que le résumé ; on charge le détail pour pré-remplir le formulaire.
		let detail: JournalDetail;
		try {
			detail = await api<JournalDetail>(`/api/journals/${j.id}`);
		} catch (e: any) {
			const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
			toast('Erreur lors du chargement de la revue : ' + msg, 'error');
			return;
		}
		const jt = detail.journal_type || 'journal';
		editModal = {
			id: detail.id, title: detail.title,
			issns: detail.issn_details.map((i) => ({
				issn: i.issn, support: i.support ?? '', linking: i.linking,
				status: i.status, replaced_by: i.replaced_by ?? '',
			})),
			oa_model: detail.oa_model || '',
			journal_type: jt, original_journal_type: jt,
			is_academic: detail.is_academic ?? true,
			is_in_doaj: detail.is_in_doaj,
			apc_amount: detail.apc_amount ? String(detail.apc_amount) : '',
		};
	}

	async function saveEdit() {
		if (!editModal) return;

		// Si le journal_type change, prévisualiser l'impact et demander confirmation.
		// Le message reste générique : le compte est exact (publications dont le doc_type change), mais la nouvelle valeur dépend de l'agrégation complète des sources de chaque publication, pas seulement du journal_type — on ne peut pas la prédire ici.
		if (editModal.journal_type !== editModal.original_journal_type) {
			try {
				const impact = await journalsApi.typeChangeImpact(editModal.id, editModal.journal_type);
				if (impact.count > 0) {
					const plural = impact.count > 1 ? 's' : '';
					const msg = `Ce changement entraînera un recalcul de la métadonnée « type de document » sur ${impact.count} publication${plural}. Continuer ?`;
					if (!(await confirmDialog({ message: msg }))) return;
				}
			} catch (e: any) {
				const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
				toast('Erreur lors du calcul d\'impact : ' + msg, 'error');
				return;
			}
		}

		const body: Record<string, any> = {};
		body.title = editModal.title.trim();
		body.issns = editModal.issns
			.filter((i) => i.issn.trim())
			.map((i) => ({
				issn: i.issn.trim(), support: i.support || null, linking: i.linking,
				status: i.status, replaced_by: i.replaced_by.trim() || null,
			}));
		body.oa_model = editModal.oa_model || null;
		body.journal_type = editModal.journal_type;
		body.is_academic = editModal.is_academic;
		body.is_in_doaj = editModal.is_in_doaj;
		body.apc_amount = editModal.apc_amount ? parseFloat(editModal.apc_amount) : null;
		try {
			await journalsApi.update(editModal.id, body);
			editModal = null;
			reload();
			// Une modification d'ISSN, de titre ou de type fait entrer ou sortir la revue des files.
			loadQueueCounts();
		} catch (e: any) {
			const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
			toast('Erreur : ' + msg, 'error');
		}
	}

	// Merge
	function openMerge(j: Journal) {
		mergeTargetId = j.id;
		mergeTargetType = j.journal_type || 'journal';
		mergeSearch.clear();
	}

	function closeMerge() {
		mergeTargetId = null;
		mergeSearch.clear();
	}

	async function doMerge(sourceId: number) {
		if (!mergeTargetId) return;
		if (await mergeJournal({ id: mergeTargetId, journal_type: mergeTargetType }, sourceId)) {
			closeMerge();
			reload();
			loadQueueCounts();
		}
	}

	onMount(async () => {
		const t = new URLSearchParams(window.location.search).get('tab');
		if (QUEUES.includes(t as TabKey)) tab = t as TabKey;
		loadQueueCounts();
		[journalTypes, oaModels] = await Promise.all([
			api<EnumOption[]>('/api/journals/types'),
			api<EnumOption[]>('/api/journals/oa-models')
		]);
	});
</script>

<svelte:head><title>{pageTitle("Revues")}</title></svelte:head>

<HubTabs
	tabs={[
		{ key: 'all', label: 'Toutes les revues' },
		{ key: 'same-titles', label: 'Titres identiques', count: sameTitleCount },
		{ key: 'shared-issns', label: 'ISSN partagés', count: sharedIssnCount },
		{ key: 'likely-proceedings', label: "Recueils d'actes probables", count: likelyProceedingsCount },
		{ key: 'doi-namespace-conflicts', label: 'Contredites par le DOI', count: doiNamespaceConflictsCount },
	]}
	active={tab}
	onselect={(key) => selectTab(key as TabKey)}
/>

{#if tab === 'same-titles'}
<JournalDuplicatesList
	url="/api/journals/same-titles"
	intro="Deux revues de même titre qui ont chacune un ISSN sont des homonymes probables : elles n'apparaissent pas ici."
	onchange={loadQueueCounts}
/>
{:else if tab === 'shared-issns'}
<JournalDuplicatesList url="/api/journals/shared-issns" valueLabel="ISSN" onchange={loadQueueCounts} />
{:else if tab === 'likely-proceedings'}
<LikelyProceedingsList onchange={loadQueueCounts} />
{:else if tab === 'doi-namespace-conflicts'}
<DoiNamespaceConflictsList onchange={loadQueueCounts} />
{:else}
<JournalsListView {apiKey}>
	{#snippet actionCell(j: Journal)}
		{#if mergeTargetId === j.id}
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
					{r.title}
					{#if r.pub_name}<span class="muted"> — {r.pub_name}</span>{/if}
					<span class="muted"> ({r.pub_count} publis)</span>
				{/snippet}
			</Picker>
		{:else}
			<button class="btn btn-sm" onclick={() => openEdit(j)}>Modifier</button>
			<button class="btn btn-sm btn-merge" onclick={() => openMerge(j)}>Fusionner…</button>
		{/if}
	{/snippet}
</JournalsListView>
{/if}

{#if editModal}
<Modal title="Modifier la revue" maxWidth="720px" onclose={() => editModal = null} onsubmit={saveEdit}>
		<label>Titre <input bind:value={editModal.title} /></label>
		<JournalIssnsEditor bind:issns={editModal.issns} />
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
				<label>Type <select bind:value={editModal.journal_type}>
					{#each journalTypes as opt (opt.value)}
						<option value={opt.value}>{opt.label_fr}</option>
					{/each}
				</select></label>
			</div>
		</div>
		<div style="display:flex;gap:12px;margin-top:8px">
			<label class="checkbox-row"><input type="checkbox" bind:checked={editModal.is_academic} /> Académique</label>
			<label class="checkbox-row"><input type="checkbox" bind:checked={editModal.is_in_doaj} /> DOAJ</label>
		</div>
		<label>APC (€) <input bind:value={editModal.apc_amount} placeholder="ex: 2500" type="number" /></label>
		{#snippet actions()}
			<button class="btn" onclick={() => editModal = null}>Annuler</button>
			<button class="btn btn-primary" onclick={saveEdit}>Enregistrer</button>
		{/snippet}
</Modal>
{/if}

<style>
	.btn-merge { font-size: 0.8rem; color: var(--accent); background: none; border: 1px solid var(--border); border-radius: 3px; cursor: pointer; padding: 2px 8px; }
	.btn-merge:hover { background: var(--accent-light); }

	.muted { color: var(--muted); }
</style>
