<script lang="ts" module>
	/** Un ISSN de la revue dans le formulaire d'édition. `replaced_by` repart tel que lu. */
	export type EditedIssn = {
		issn: string;
		support: string;
		linking: boolean;
		status: string;
		replaced_by: string;
	};
</script>

<script lang="ts">
	import { issnStatusLabels, issnSupportNames } from '$lib/labels';

	let { issns = $bindable() }: { issns: EditedIssn[] } = $props();

	const supports = Object.entries(issnSupportNames);
	const statuses = Object.entries(issnStatusLabels);

	/** Ligne en cours d'édition : son rang, sa copie de travail, et si elle vient d'être ajoutée. */
	let editing = $state<{ index: number; draft: EditedIssn; added: boolean } | null>(null);

	function edit(index: number) {
		editing = { index, draft: { ...issns[index] }, added: false };
	}

	function add() {
		issns.push({ issn: '', support: '', linking: false, status: 'active', replaced_by: '' });
		editing = { index: issns.length - 1, draft: { ...issns[issns.length - 1] }, added: true };
	}

	function validate() {
		if (!editing) return;
		const { index, draft } = editing;
		if (!draft.issn.trim()) return;
		if (draft.linking) issns.forEach((row, i) => (row.linking = i === index));
		issns[index] = { ...draft, issn: draft.issn.trim() };
		editing = null;
	}

	function cancel() {
		if (editing?.added) issns.splice(editing.index, 1);
		editing = null;
	}

	function remove() {
		if (!editing) return;
		issns.splice(editing.index, 1);
		editing = null;
	}
</script>

<fieldset class="issns">
	<legend>ISSN</legend>
	<table>
		<thead><tr><th>Valeur</th><th>Support</th><th>Statut</th><th></th><th></th></tr></thead>
		<tbody>
			{#each issns as row, index (index)}
				{#if editing?.index === index}
					<tr class="editing">
						<td>
							{#if editing.added}
								<input bind:value={editing.draft.issn} placeholder="1234-5678" />
							{:else}
								{row.issn}
							{/if}
						</td>
						<td><select bind:value={editing.draft.support}>
							<option value="">(inconnu)</option>
							{#each supports as [value, label] (value)}<option {value}>{label}</option>{/each}
						</select></td>
						<td><select bind:value={editing.draft.status}>
							{#each statuses as [value, label] (value)}<option {value}>{label}</option>{/each}
						</select></td>
						<td><label class="linking"><input type="checkbox" bind:checked={editing.draft.linking} /> ISSN-L</label></td>
						<td class="actions">
							<button type="button" class="btn btn-sm btn-primary" onclick={validate}>Valider</button>
							<button type="button" class="btn btn-sm" onclick={cancel}>Annuler</button>
							{#if !editing.added}<button type="button" class="btn btn-sm btn-danger" onclick={remove}>Retirer</button>{/if}
						</td>
					</tr>
				{:else}
					<tr>
						<td class="value">{row.issn}</td>
						<td>{row.support ? issnSupportNames[row.support] : '(inconnu)'}</td>
						<td>{issnStatusLabels[row.status] ?? row.status}</td>
						<td>{#if row.linking}<span class="badge-issnl">ISSN-L</span>{/if}</td>
						<td class="actions">
							<button type="button" class="icon-btn" title="Modifier l'ISSN" aria-label="Modifier l'ISSN {row.issn}" disabled={editing !== null} onclick={() => edit(index)}>
								<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /><path d="m15 5 4 4" /></svg>
							</button>
						</td>
					</tr>
				{/if}
			{:else}
				<tr><td colspan="5" class="muted">Aucun ISSN</td></tr>
			{/each}
		</tbody>
	</table>
	<button type="button" class="btn btn-sm" disabled={editing !== null} onclick={add}>Ajouter un ISSN</button>
</fieldset>

<style>
	.issns { border: 1px solid var(--border); border-radius: 4px; padding: 6px 8px; margin: 8px 0; }
	.issns table { width: 100%; border-collapse: collapse; margin-bottom: 6px; }
	.issns th { font-size: 0.8rem; text-align: left; font-weight: normal; color: var(--muted); }
	.issns td { padding: 3px 6px 3px 0; font-size: 0.9rem; }
	.value { font-family: var(--mono, monospace); }
	.actions { text-align: right; white-space: nowrap; }
	.linking { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
	.badge-issnl { font-size: 0.75rem; padding: 1px 6px; border: 1px solid var(--border); border-radius: 3px; }
	.muted { color: var(--muted); }
	.icon-btn { background: none; border: none; cursor: pointer; padding: 3px; color: var(--muted); border-radius: 3px; }
	.icon-btn:hover:not(:disabled) { color: var(--accent); background: #f0f0f0; }
	.icon-btn:disabled { opacity: 0.4; cursor: default; }
</style>
