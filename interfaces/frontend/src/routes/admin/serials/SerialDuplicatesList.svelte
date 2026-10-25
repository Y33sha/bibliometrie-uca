<script lang="ts">
	import { untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import { api, ApiError } from '#lib/api/index.js';
	import { confirmDialog, toast } from '#lib/dialogs.svelte.js';
	import type { components } from '#lib/api/schema.js';
	import { mergeSerial } from './mergeSerial';

	type DuplicatesResponse = components['schemas']['SerialDuplicatesResponse'];
	type Group = components['schemas']['SerialDuplicateGroup'];
	type Serial = components['schemas']['SerialListItem'];

	let {
		url,
		valueLabel,
		intro,
		onchange,
	}: {
		/** Route de la file : `/api/serials/same-titles` ou `/api/serials/shared-issns`. */
		url: string;
		/** Libellé de la valeur partagée, affiché en tête de chaque groupe (« ISSN ») ; sans libellé, les groupes se suivent sans en-tête. */
		valueLabel?: string;
		intro?: string;
		/** Appelé après chaque fusion, pour rafraîchir les compteurs des onglets. */
		onchange: () => void;
	} = $props();

	let groups: Group[] = $state([]);
	let loading = $state(true);
	let busy = $state(false);

	async function load() {
		loading = true;
		try {
			groups = (await api<DuplicatesResponse>(url)).groups;
		} catch (e: any) {
			const msg = e instanceof ApiError ? JSON.stringify(e.detail) : e.message;
			toast('Erreur lors du chargement de la file : ' + msg, 'error');
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		untrack(load);
	});

	async function keep(group: Group, target: Serial) {
		const sources = group.serials.filter((j) => j.id !== target.id);
		const plural = sources.length > 1 ? 's' : '';
		const message = `Garder « ${target.title} » et y fusionner ${sources.length} publication${plural} en série ?`;
		if (!(await confirmDialog({ message, danger: true }))) return;
		busy = true;
		try {
			for (const source of sources) {
				if (!(await mergeSerial(target, source.id))) break;
			}
		} finally {
			busy = false;
			await load();
			onchange();
		}
	}

	function issns(j: Serial): string {
		return j.issns.join(' / ') || 'sans ISSN';
	}
</script>

{#if loading}
	<p class="muted">Chargement…</p>
{:else if groups.length === 0}
	<p class="muted">Aucun groupe.</p>
{:else}
	{#if intro}<p class="muted intro">{intro}</p>{/if}
	<table class="data-table triage-table">
		<colgroup>
			<col class="col-title" />
			<col class="col-publisher" />
			<col class="col-issn" />
			<col class="col-publications" />
			<col class="col-action" />
		</colgroup>
		<thead>
			<tr><th>Publication en série</th><th>Éditeur</th><th>ISSN</th><th class="num">Publications</th><th></th></tr>
		</thead>
		{#each groups as group (group.value)}
			<tbody class="group">
				{#if valueLabel}
					<tr class="group-head"><th colspan="5">{valueLabel} {group.value}</th></tr>
				{/if}
				{#each group.serials as j (j.id)}
					<tr>
						<td><a href={resolve(`journals/${j.id}`)}>{j.title}</a> <span class="muted">#{j.id}</span></td>
						<td>{j.publisher_name ?? '—'}</td>
						<td>{issns(j)}</td>
						<td class="num">{j.publication_count}</td>
						<td class="action">
							<button class="btn btn-sm" disabled={busy} onclick={() => keep(group, j)}>
								Garder celle-ci
							</button>
						</td>
					</tr>
				{/each}
			</tbody>
		{/each}
	</table>
{/if}

<style>
	.intro { margin: 0 0 12px; }
	.col-title { width: 38%; }
	.col-publisher { width: 24%; }
	.col-issn { width: 16%; }
	.col-publications { width: 9%; }
	.col-action { width: 13%; }
	.group-head th { font-weight: 600; }
	.muted { color: var(--muted); }
</style>
