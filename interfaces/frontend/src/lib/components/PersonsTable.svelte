<script lang="ts">
	import { resolve } from '$app/paths';
	import { titleCase } from '#lib/utils.js';
	import { institution } from '#lib/institution.svelte.js';
	import IdentifiersCell from './IdentifiersCell.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import type { components } from '#lib/api/schema.js';

	export type PersonRow = components['schemas']['PersonOut'];

	let {
		persons,
		loading = false,
		sort,
		onSortChange,
		perimeterCount = false,
		onopen,
		activeId = null,
	}: {
		persons: PersonRow[];
		loading?: boolean;
		sort: string;
		onSortChange: (newSort: string) => void;
		/** Ajoute la colonne des publications dans le périmètre de l'établissement. */
		perimeterCount?: boolean;
		/** Si fourni, le nom ouvre la personne via ce callback au lieu de lier vers sa fiche. */
		onopen?: (personId: number) => void;
		activeId?: number | null;
	} = $props();

	// Colonnes numériques triables, placées après les colonnes descriptives.
	const countColumns = $derived([
		{ label: 'Publications', sortKey: 'contributions', value: (p: PersonRow) => p.contribution_count },
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

	function toggleSort(col: string) {
		onSortChange(sort === `${col}_asc` ? `${col}_desc` : `${col}_asc`);
	}

	function sortIndicator(col: string): string {
		if (sort === `${col}_asc`) return ' ▲';
		if (sort === `${col}_desc`) return ' ▼';
		return '';
	}
</script>

<div class="table-scroll">
<table class="data-table persons-table">
	<thead>
		<tr>
			<th
				class="sortable"
				class:active={sort === 'name_asc' || sort === 'name_desc'}
				onclick={() => toggleSort('name')}>Nom{sortIndicator('name')}</th
			>
			<th>Identifiants</th>
			<th
				class="sortable"
				class:active={sort === 'role_asc' || sort === 'role_desc'}
				onclick={() => toggleSort('role')}>Fonction{sortIndicator('role')}</th
			>
			<th
				class="sortable"
				class:active={sort === 'dept_asc' || sort === 'dept_desc'}
				onclick={() => toggleSort('dept')}>Département{sortIndicator('dept')}</th
			>
			{#each countColumns as col (col.sortKey)}
				<th
					class="sortable num"
					style="width:80px"
					class:active={sort === `${col.sortKey}_asc` || sort === `${col.sortKey}_desc`}
					onclick={() => toggleSort(col.sortKey)}>{col.label}{sortIndicator(col.sortKey)}</th
				>
			{/each}
		</tr>
	</thead>
	<tbody>
		{#if persons.length === 0}
			<TableStatusRow {loading} colspan={4 + countColumns.length} emptyText="Aucune personne trouvée" />
		{:else}
			{#each persons as p (p.id)}
				<tr class:excluded={!!p.exclusion}>
					<td>
						{#if onopen}
							<button
								type="button"
								class="entity-link person-link"
								class:active={activeId === p.id}
								onclick={() => onopen(p.id)}
							>
								<span class="person-last">{titleCase(p.last_name)}</span>
								{titleCase(p.first_name)}
							</button>
						{:else}
							<a href={resolve(`persons/${p.id}`)} class="entity-link person-link">
								<span class="person-last">{titleCase(p.last_name)}</span>
								{titleCase(p.first_name)}
							</a>
						{/if}
						{#if p.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
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
	button.person-link.active { text-decoration: underline; }
	tr.excluded { opacity: 0.45; }
	tr.excluded:hover { opacity: 0.7; }
	tr.excluded .person-link { text-decoration: line-through; }
	.person-last { font-weight: 600; }
	.secondary-cell { font-size: 0.9rem; color: var(--text-secondary); }
</style>
