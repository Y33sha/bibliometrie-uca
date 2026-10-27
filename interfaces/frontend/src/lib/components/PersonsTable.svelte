<script lang="ts">
	import SortChevron from '#lib/components/SortChevron.svelte';
	import { columnLabels } from '#lib/labels.js';
	import RhCheck from '#lib/components/RhCheck.svelte';
	import { resolve } from '$app/paths';
	import { titleCase } from '#lib/utils.js';
	import { institution } from '#lib/institution.svelte.js';
	import IdentifiersCell from './IdentifiersCell.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import IconButton from '#lib/components/IconButton.svelte';
	import { nextSort, sortDirection, type SortDirection } from '#lib/sort.js';
	import type { components } from '#lib/api/schema.js';

	export type PersonRow = components['schemas']['PersonOut'];

	let {
		persons,
		loading = false,
		error = null,
		sort,
		onSortChange,
		perimeterCount = false,
		onopen,
		activeId = null,
	}: {
		persons: PersonRow[];
		loading?: boolean;
		/** Message du chargement en échec. */
		error?: string | null;
		sort: string;
		onSortChange: (newSort: string) => void;
		/** Ajoute la colonne des publications dans le périmètre de l'établissement. */
		perimeterCount?: boolean;
		/** Ouvre le volet de la personne dans la page hôte. Fourni, il ajoute en tête de ligne une icône qui l'appelle ; le nom mène toujours à la fiche. */
		onopen?: (personId: number) => void;
		/** Personne ouverte par la page hôte, dont la ligne est mise en évidence. */
		activeId?: number | null;
	} = $props();

	// Colonnes numériques triables, placées après les colonnes descriptives.
	const countColumns = $derived([
		{ label: columnLabels.publications, sortKey: 'contributions', value: (p: PersonRow) => p.contribution_count },
		...(perimeterCount
			? [
					{
						label: institution.name,
						sortKey: 'in_perimeter_contributions',
						value: (p: PersonRow) => p.in_perimeter_contribution_count
					}
				]
			: [])
	]);

	// Les colonnes de texte se trient d'abord dans l'ordre alphabétique, les décomptes d'abord du plus grand au plus petit.
	function toggleSort(col: string, first: SortDirection = 'asc') {
		onSortChange(nextSort(sort, col, first));
	}
</script>

<div class="table-scroll">
<table class="data-table persons-table">
	<thead>
		<tr>
			{#if onopen}<th class="panel-col"></th>{/if}
			<th class="rh-col" title="Présente dans le SI RH">RH</th>
			<th
				class="sortable"
				class:active={sortDirection(sort, 'name') !== null}
				onclick={() => toggleSort('name')}>Nom<SortChevron direction={sortDirection(sort, 'name')} /></th
			>
			<th>Identifiants</th>
			<th
				class="sortable"
				class:active={sortDirection(sort, 'role') !== null}
				onclick={() => toggleSort('role')}>Fonction<SortChevron direction={sortDirection(sort, 'role')} /></th
			>
			<th
				class="sortable"
				class:active={sortDirection(sort, 'dept') !== null}
				onclick={() => toggleSort('dept')}>Département<SortChevron direction={sortDirection(sort, 'dept')} /></th
			>
			{#each countColumns as col (col.sortKey)}
				<th
					class="sortable num"
					style="width:80px"
					class:active={sortDirection(sort, col.sortKey) !== null}
					onclick={() => toggleSort(col.sortKey, 'desc')}>{col.label}<SortChevron direction={sortDirection(sort, col.sortKey)} /></th
				>
			{/each}
		</tr>
	</thead>
	<tbody>
		{#if persons.length === 0}
			<TableStatusRow {loading} {error} colspan={5 + countColumns.length + (onopen ? 1 : 0)} emptyText="Aucune personne trouvée" />
		{:else}
			{#each persons as p (p.id)}
				<tr class:excluded={!!p.exclusion} class:active-row={activeId === p.id}>
					{#if onopen}
						<td class="panel-col row-actions">
							<IconButton icon="panel" label="Ouvrir le volet" onclick={() => onopen(p.id)} />
						</td>
					{/if}
					<td class="rh-col">{#if p.has_rh}<RhCheck />{/if}</td>
					<td>
						<a href={resolve(`persons/${p.id}`)} class="entity-link person-link">
							<span class="person-last">{titleCase(p.last_name)}</span>
							{titleCase(p.first_name)}
						</a>
					</td>
					<td>
						<IdentifiersCell identifiers={p.identifiers} />
					</td>
					<td class="secondary-cell">{p.role_title || ''}</td>
					<td class="secondary-cell">{p.department_name || ''}</td>
					{#each countColumns as col (col.sortKey)}
						<td class="num">{col.value(p)}</td>
					{/each}
				</tr>
			{/each}
		{/if}
	</tbody>
</table>
</div>

<style>
	.persons-table { min-width: 620px; }
	.persons-table td { vertical-align: middle; }
	.rh-col { width: 28px; padding-right: 0; text-align: center; }
	.rh-col :global(.rh-check) { margin-left: 0; }
	.panel-col { width: 28px; padding-right: 0; }
	tr.active-row td { background: var(--accent-light); }
	tr.excluded { opacity: 0.45; }
	tr.excluded:hover { opacity: 0.7; }
	tr.excluded .person-link { text-decoration: line-through; }
	.person-last { font-weight: 600; }
	.secondary-cell { font-size: 0.9rem; color: var(--text-secondary); }
</style>
