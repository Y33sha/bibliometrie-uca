<script lang="ts">
	import { onMount } from 'svelte';
	import { api, ApiError, journals as journalsApi } from '$lib/api';
	import { useDebouncedSearch } from '$lib/composables/useDebouncedSearch.svelte';
	import JournalsListView from '$lib/components/JournalsListView.svelte';
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
		is_academic: boolean; is_predatory: boolean; is_in_doaj: boolean;
		apc_amount: string;
	} | null = $state(null);

	// Libellé du doc_type cible pour chaque règle de requalification journal-dépendante.
	// Sert au texte de la confirmation avant d'appliquer le changement de journal_type.
	// Étendre quand de nouvelles règles produisent un doc_type sur changement de journal_type.
	const REQUALIF_TARGET_LABEL: Record<string, string> = {
		media: 'intervention média',
	};

	function openEdit(j: Journal) {
		const jt = j.journal_type || 'journal';
		editModal = {
			id: j.id, title: j.title,
			issn: j.issn || '', eissn: j.eissn || '', issnl: j.issnl || '',
			doi_prefix: j.doi_prefix || '', oa_model: j.oa_model || '',
			journal_type: jt, original_journal_type: jt,
			is_academic: j.is_academic ?? true,
			is_predatory: j.is_predatory, is_in_doaj: j.is_in_doaj,
			apc_amount: j.apc_amount ? String(j.apc_amount) : '',
		};
	}

	async function saveEdit() {
		if (!editModal) return;

		// Si le journal_type change, prévisualiser l'impact et demander confirmation.
		if (editModal.journal_type !== editModal.original_journal_type) {
			try {
				const impact = await journalsApi.typeChangeImpact(editModal.id, editModal.journal_type);
				if (impact.count > 0) {
					const target = REQUALIF_TARGET_LABEL[editModal.journal_type] ?? editModal.journal_type;
					const plural = impact.count > 1 ? 's' : '';
					const msg = `Ce changement entraînera la requalification de ${impact.count} publication${plural} en « ${target} ». Continuer ?`;
					if (!confirm(msg)) return;
				}
			} catch (e: any) {
				const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
				alert('Erreur lors du calcul d\'impact : ' + msg);
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
		body.is_predatory = editModal.is_predatory;
		body.is_in_doaj = editModal.is_in_doaj;
		body.apc_amount = editModal.apc_amount ? parseFloat(editModal.apc_amount) : null;
		try {
			await journalsApi.update(editModal.id, body);
			editModal = null;
			reload();
		} catch (e: any) {
			const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
			alert('Erreur : ' + msg);
		}
	}

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
			await journalsApi.merge(mergeTargetId, sourceId);
			closeMerge();
			reload();
		} catch (e: any) {
			if (e instanceof ApiError) {
				const detail = (e.detail as { detail?: string })?.detail;
				alert(detail || `Erreur ${e.status}: ${JSON.stringify(e.detail)}`);
				return;
			}
			alert('Erreur réseau : ' + e.message);
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
			<button class="btn btn-sm btn-merge" onclick={() => openMerge(j.id)}>Fusionner…</button>
		{/if}
	{/snippet}
</JournalsListView>

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
					{#each journalTypes as opt (opt.value)}
						<option value={opt.value}>{opt.label_fr}</option>
					{/each}
				</select>
			</div>
		</div>
		<div style="display:flex;gap:12px;margin-top:8px">
			<label class="checkbox-row"><input type="checkbox" bind:checked={editModal.is_academic} /> Académique</label>
			<label class="checkbox-row"><input type="checkbox" bind:checked={editModal.is_predatory} /> Prédateur</label>
			<label class="checkbox-row"><input type="checkbox" bind:checked={editModal.is_in_doaj} /> DOAJ</label>
		</div>
		<label>APC (€)</label>
		<input bind:value={editModal.apc_amount} placeholder="ex: 2500" type="number" />
		<div class="modal-actions">
			<button class="btn" onclick={() => editModal = null}>Annuler</button>
			<button class="btn btn-primary" onclick={saveEdit}>Enregistrer</button>
		</div>
	</div>
</div>
{/if}

<style>
	h2 { font-size: 1.2rem; font-weight: 600; margin: 0 0 12px; }

	.btn-merge { font-size: 0.8rem; color: var(--accent); background: none; border: 1px solid var(--border); border-radius: 3px; cursor: pointer; padding: 2px 8px; }
	.btn-merge:hover { background: var(--accent-light); }

	.merge-search { display: inline-block; position: relative; }
	.merge-input { width: 160px; padding: 3px 6px; font-size: 0.85rem; border: 1px solid var(--accent); border-radius: 3px; font-family: inherit; }
	.merge-results { position: absolute; right: 0; top: 100%; z-index: 10; border: 1px solid var(--border); border-radius: 4px; margin-top: 2px; max-height: 200px; overflow-y: auto; background: white; min-width: 350px; max-width: 600px; box-shadow: 0 2px 8px rgba(0,0,0,0.12); }
	.merge-result { display: block; width: 100%; padding: 5px 8px; font-size: 0.85rem; cursor: pointer; background: none; border: none; text-align: left; font-family: inherit; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.merge-result:hover { background: var(--warning-light, #fff3e0); }
	.muted { color: var(--muted); }
</style>
