<script lang="ts">
	import { untrack } from 'svelte';
	import { resolve } from '$app/paths';
	import { api, serials as serialsApi, errorMessage } from '#lib/api/index.js';
	import { confirmDialog, toast } from '#lib/dialogs.svelte.js';
	import type { components } from '#lib/api/schema.js';

	type Response = components['schemas']['LikelyProceedingsResponse'];
	type Item = components['schemas']['LikelyProceedingsItem'];

	let {
		onchange,
	}: {
		/** Appelé après chaque typage, pour rafraîchir les compteurs des onglets. */
		onchange: () => void;
	} = $props();

	let items: Item[] = $state([]);
	let loading = $state(true);
	let busy = $state(false);

	async function load() {
		loading = true;
		try {
			items = (await api<Response>('/api/serials/likely-proceedings')).serials;
		} catch (e) {
			toast('Erreur lors du chargement de la file : ' + errorMessage(e), 'error');
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		untrack(load);
	});

	async function markProceedings(item: Item) {
		const j = item.serial;
		busy = true;
		try {
			const impact = await serialsApi.typeChangeImpact(j.id, 'proceedings');
			const plural = impact.count > 1 ? 's' : '';
			const recalcul = impact.count
				? ` Le type de document de ${impact.count} publication${plural} sera recalculé.`
				: '';
			const message = `Typer « ${j.title} » en recueil d'actes ?${recalcul}`;
			if (!(await confirmDialog({ message }))) return;
			await serialsApi.update(j.id, { serial_type: 'proceedings' });
			await load();
			onchange();
		} catch (e) {
			toast('Erreur : ' + errorMessage(e), 'error');
		} finally {
			busy = false;
		}
	}

	function issns(item: Item): string {
		const j = item.serial;
		return j.issns.join(' / ') || 'sans ISSN';
	}
</script>

{#if loading}
	<p class="muted">Chargement…</p>
{:else if items.length === 0}
	<p class="muted">Aucune publication en série.</p>
{:else}
	<p class="muted intro">
		Publications en série typées « revue » dont la majorité des documents sont des articles de congrès, d'après le type donné par chaque source. Les publications en série sans ISSN viennent en tête.
	</p>
	<table class="data-table triage-table">
		<colgroup>
			<col class="col-title" />
			<col class="col-publisher" />
			<col class="col-issn" />
			<col class="col-share" />
			<col class="col-action" />
		</colgroup>
		<thead>
			<tr>
				<th>Publication en série</th><th>Éditeur</th><th>ISSN</th><th class="num">Articles de congrès</th><th></th>
			</tr>
		</thead>
		<tbody>
			{#each items as item (item.serial.id)}
				<tr>
					<td>
						<a href={resolve(`journals/${item.serial.id}`)}>{item.serial.title}</a>
						<span class="muted">#{item.serial.id}</span>
					</td>
					<td>{item.serial.publisher_name ?? '—'}</td>
					<td>{issns(item)}</td>
					<td class="num">{item.conference_papers} / {item.records}</td>
					<td class="action">
						<button class="btn btn-sm" disabled={busy} onclick={() => markProceedings(item)}>
							Recueil d'actes
						</button>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
{/if}

<style>
	.intro { margin: 0 0 12px; }
	.col-title { width: 40%; }
	.col-publisher { width: 22%; }
	.col-issn { width: 14%; }
	.col-share { width: 11%; }
	.col-action { width: 13%; }
	.muted { color: var(--muted); }
</style>
