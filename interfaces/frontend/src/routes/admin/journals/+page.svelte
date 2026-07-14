<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError, journals as journalsApi } from '$lib/api';
	import { useDebouncedSearch } from '$lib/composables/useDebouncedSearch.svelte';
	import JournalsListView from '$lib/components/JournalsListView.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import { autofocus } from '$lib/actions/focus';
	import { confirmDialog, toast } from '$lib/dialogs.svelte';
	import type { components } from '$lib/api/schema';

	type Journal = components['schemas']['JournalOut'];
	type JournalListResponse = components['schemas']['JournalListResponse'];
	type EnumOption = components['schemas']['EnumOption'];

	let journalTypes: EnumOption[] = $state([]);

	// Clé d'API utilisée pour invalider le cache de JournalsListView après
	// une édition ou fusion (force un reload via incrément).
	let viewVersion = $state(0);
	const apiKey = $derived(`admin-journals-${viewVersion}`);
	function reload() { viewVersion += 1; }

	// Merge state : recherche avec debounce + cible en cours de fusion
	let mergeTargetId: number | null = $state(null);
	let mergeTargetType = $state('journal');
	const mergeSearch = useDebouncedSearch<Journal>({
		search: async (q) => {
			const data = await api<JournalListResponse>(
				`/api/journals?search=${encodeURIComponent(q)}&per_page=10`,
			);
			return data.journals;
		},
		transform: (results) => results.filter((j) => j.id !== mergeTargetId),
	});

	// Modal édition
	let editModal: {
		id: number; title: string; issn: string; eissn: string; issnl: string;
		doi_prefix: string; oa_model: string;
		journal_type: string; original_journal_type: string;
		is_academic: boolean; is_in_doaj: boolean;
		apc_amount: string;
	} | null = $state(null);

	function openEdit(j: Journal) {
		const jt = j.journal_type || 'journal';
		editModal = {
			id: j.id, title: j.title,
			issn: j.issn || '', eissn: j.eissn || '', issnl: j.issnl || '',
			doi_prefix: j.doi_prefix || '', oa_model: j.oa_model || '',
			journal_type: jt, original_journal_type: jt,
			is_academic: j.is_academic ?? true,
			is_in_doaj: j.is_in_doaj,
			apc_amount: j.apc_amount ? String(j.apc_amount) : '',
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
		body.issn = editModal.issn.trim() || null;
		body.eissn = editModal.eissn.trim() || null;
		body.issnl = editModal.issnl.trim() || null;
		body.doi_prefix = editModal.doi_prefix.trim() || null;
		body.oa_model = editModal.oa_model || null;
		body.journal_type = editModal.journal_type;
		body.is_academic = editModal.is_academic;
		body.is_in_doaj = editModal.is_in_doaj;
		body.apc_amount = editModal.apc_amount ? parseFloat(editModal.apc_amount) : null;
		try {
			await journalsApi.update(editModal.id, body);
			editModal = null;
			reload();
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
		// Prévisualiser la requalification : fusionner dans un journal d'un autre
		// type re-dérive le doc_type des publications absorbées contre le type de la
		// cible (cf. merge_journals). Compte exact via le même endpoint que le
		// changement de type, appliqué au journal source avec le type de la cible
		// (count = 0 si même type → pas de confirmation).
		try {
			const impact = await journalsApi.typeChangeImpact(sourceId, mergeTargetType);
			if (impact.count > 0) {
				const plural = impact.count > 1 ? 's' : '';
				const msg = `Cette fusion entraînera un recalcul de la métadonnée « type de document » sur ${impact.count} publication${plural} du journal absorbé. Continuer ?`;
				if (!(await confirmDialog({ message: msg, danger: true }))) return;
			}
		} catch (e: any) {
			const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
			toast('Erreur lors du calcul d\'impact : ' + msg, 'error');
			return;
		}
		try {
			await journalsApi.merge(mergeTargetId, sourceId);
			closeMerge();
			reload();
		} catch (e: any) {
			if (e instanceof ApiError) {
				const detail = (e.detail as { detail?: string })?.detail;
				toast(detail || `Erreur ${e.status}: ${JSON.stringify(e.detail)}`, 'error');
				return;
			}
			toast('Erreur réseau : ' + e.message, 'error');
		}
	}

	onMount(async () => {
		journalTypes = await api<EnumOption[]>('/api/journal-types');
	});
</script>

<svelte:head><title>Revues — Bibliométrie UCA</title></svelte:head>

<h2>Revues</h2>

<JournalsListView {apiKey}>
	{#snippet actionCell(j: Journal)}
		{#if mergeTargetId === j.id}
			<div class="merge-search">
				<input type="search" placeholder="Fusionner avec…" value={mergeSearch.query} use:autofocus onkeydown={(e) => { if (e.key === 'Escape') { e.preventDefault(); closeMerge(); } }}
					oninput={(e) => mergeSearch.setQuery((e.target as HTMLInputElement).value)}
					class="merge-input" />
				<button class="btn btn-sm" onclick={closeMerge}>Annuler</button>
				{#if mergeSearch.loading}
					<div class="merge-results"><span class="muted">Recherche…</span></div>
				{:else if mergeSearch.results.length > 0}
					<div class="merge-results">
						{#each mergeSearch.results as r (r.id)}
							<button class="merge-result" onclick={() => doMerge(r.id)}>
								{r.title}
								{#if r.pub_name}<span class="muted"> — {r.pub_name}</span>{/if}
								<span class="muted"> ({r.pub_count} publis)</span>
							</button>
						{/each}
					</div>
				{:else if mergeSearch.query.length >= 2}
					<div class="merge-results"><span class="muted">Aucun résultat</span></div>
				{/if}
			</div>
		{:else}
			<button class="btn btn-sm" onclick={() => openEdit(j)}>Modifier</button>
			<button class="btn btn-sm btn-merge" onclick={() => openMerge(j)}>Fusionner…</button>
		{/if}
	{/snippet}
</JournalsListView>

{#if editModal}
<Modal title="Modifier la revue" maxWidth="520px" onclose={() => editModal = null} onsubmit={saveEdit}>
		<label>Titre <input bind:value={editModal.title} /></label>
		<div style="display:flex;gap:8px">
			<div style="flex:1"><label>ISSN <input bind:value={editModal.issn} placeholder="1234-5678" /></label></div>
			<div style="flex:1"><label>eISSN <input bind:value={editModal.eissn} /></label></div>
			<div style="flex:1"><label>ISSN-L <input bind:value={editModal.issnl} /></label></div>
		</div>
		<label>DOI prefix <input bind:value={editModal.doi_prefix} placeholder="ex: 10.1038/s41586" /></label>
		<div style="display:flex;gap:8px">
			<div style="flex:1">
				<label>Modèle OA <select bind:value={editModal.oa_model}>
					<option value="">(non renseigné)</option>
					<option value="subscription">Abonnement</option>
					<option value="full_oa">Full OA (gold/diamond)</option>
					<option value="repository">Archive/dépôt</option>
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
	h2 { font-size: 1.2rem; font-weight: 600; margin: 0 0 12px; }

	.btn-merge { font-size: 0.8rem; color: var(--accent); background: none; border: 1px solid var(--border); border-radius: 3px; cursor: pointer; padding: 2px 8px; }
	.btn-merge:hover { background: var(--accent-light); }

	.merge-search { display: inline-block; position: relative; }
	.merge-input { width: 160px; padding: 3px 6px; font-size: 0.85rem; border: 1px solid var(--accent); border-radius: 3px; font-family: inherit; }
	.merge-results { position: absolute; right: 0; top: 100%; z-index: 10; border: 1px solid var(--border); border-radius: 4px; margin-top: 2px; max-height: 200px; overflow-y: auto; background: white; min-width: 350px; max-width: 600px; box-shadow: 0 2px 8px rgba(0,0,0,0.12); }
	.merge-result { display: block; width: 100%; padding: 5px 8px; font-size: 0.85rem; cursor: pointer; background: none; border: none; text-align: left; font-family: inherit; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.merge-result:hover, .merge-result:focus-visible { background: var(--accent-light); outline: none; }
	.muted { color: var(--muted); }
</style>
