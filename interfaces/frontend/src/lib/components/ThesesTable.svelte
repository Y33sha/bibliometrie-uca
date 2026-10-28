<script lang="ts" module>
	import { columnLabels } from '#lib/labels.js';
	import { useColumnVisibility, type ColumnVisibility } from '#lib/composables/useColumnVisibility.svelte.js';

	/** Visibilité des colonnes du tableau, tenue par la vue qui l'affiche : l'export CSV émet les mêmes colonnes. */
	export function useThesisColumns(showLabsColumn: boolean): ColumnVisibility {
		const columnDefs = [
			{ key: 'inscription', label: 'Inscription' },
			{ key: 'soutenance',  label: 'Soutenance' },
			{ key: 'author',      label: columnLabels.author },
			{ key: 'doi',         label: columnLabels.doi },
			{ key: 'title',       label: columnLabels.title,       fixed: true },
			{ key: 'status',      label: 'Statut' },
			...(showLabsColumn ? [{ key: 'labs', label: columnLabels.labs }] : []),
			{ key: 'sources',     label: columnLabels.sources },
			{ key: 'access',      label: columnLabels.access,       fixed: true },
		];
		return useColumnVisibility('thesis-table-columns', columnDefs, ['sources']);
	}
</script>

<script lang="ts">
	import TableScroll from '#lib/components/TableScroll.svelte';
	import SourceLinks from '#lib/components/SourceLinks.svelte';
	import AccessButton from '#lib/components/AccessButton.svelte';
	import IconButton from '#lib/components/IconButton.svelte';
	import ColumnMenu from '#lib/components/ColumnMenu.svelte';
	import DoiLink from '#lib/components/DoiLink.svelte';
	import SortChevron from '#lib/components/SortChevron.svelte';
	import { resolve } from '$app/paths';
	import { titleCase } from '#lib/utils.js';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { sortDirection } from '#lib/sort.js';
	import type { components, operations } from '#lib/api/schema.js';

	// Ligne servie par `/api/publications` (mode thèses) : le sous-ensemble de `PublicationListItem` que ce tableau consomme.
	export type ThesisRow = Pick<
		components['schemas']['PublicationListItem'],
		| 'id'
		| 'title'
		| 'doi'
		| 'doc_type'
		| 'oa_status'
		| 'access_url'
		| 'hal_id'
		| 'openalex_id'
		| 'scanr_id'
		| 'theses_id'
		| 'record_urls'
		| 'date_soutenance'
		| 'date_inscription'
		| 'thesis_author_name'
		| 'thesis_author_person_id'
		| 'lab_items'
	>;

	// Tri accepté par `/api/publications`.
	export type PublicationSort = NonNullable<
		NonNullable<operations['list_publications_api_publications_get']['parameters']['query']>['sort']
	>;

	export type ThesisSortColumn = 'inscription' | 'soutenance' | 'author' | 'title' | 'labs';

	let {
		items,
		loading = false,
		error = null,
		sort,
		onToggleSort,
		columns: cv,
		onopen,
		activeId = null,
	}: {
		items: ThesisRow[];
		loading?: boolean;
		/** Message du chargement en échec. */
		error?: string | null;
		sort: PublicationSort;
		onToggleSort: (column: ThesisSortColumn) => void;
		/** Visibilité des colonnes, créée par `useThesisColumns`. */
		columns: ColumnVisibility;
		/** Ouvre le volet de la thèse. Fourni, il ajoute en tête de ligne une icône qui l'appelle. */
		onopen?: (publicationId: number) => void;
		/** Thèse dont le volet est ouvert, dont la ligne est mise en évidence. */
		activeId?: number | null;
	} = $props();

	const MONTHS = [
		'janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin',
		'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.',
	];

	function formatDate(iso: string | null): { month: string; year: string } | null {
		if (!iso) return null;
		const [y, m] = iso.split('-');
		return { month: MONTHS[parseInt(m, 10) - 1] || '', year: y };
	}

	const col = (key: string) => cv.col(key);

	const inscrSort = $derived(sortDirection(sort, 'inscription'));
	const soutSort = $derived(sortDirection(sort, 'soutenance'));
	const authorSort = $derived(sortDirection(sort, 'author'));
	const titleSort = $derived(sortDirection(sort, 'title'));
	const labsSort = $derived(sortDirection(sort, 'labs'));
</script>

<TableScroll>
<table class="data-table theses-table">
	<thead>
		<tr>
			{#if onopen}<th class="panel-col"></th>{/if}
			{#if col('inscription')}<th
				class="col-date sortable"
				class:active={inscrSort !== null}
				onclick={() => onToggleSort('inscription')}
			>Inscription <SortChevron direction={inscrSort} /></th>{/if}
			{#if col('soutenance')}<th
				class="col-date sortable"
				class:active={soutSort !== null}
				onclick={() => onToggleSort('soutenance')}
			>Soutenance <SortChevron direction={soutSort} /></th>{/if}
			{#if col('author')}<th
				class="col-author sortable"
				class:active={authorSort !== null}
				onclick={() => onToggleSort('author')}
			>{columnLabels.author} <SortChevron direction={authorSort} /></th>{/if}
			{#if col('doi')}<th class="col-doi">{columnLabels.doi}</th>{/if}
			<th
				class="col-title sortable"
				class:active={titleSort !== null}
				onclick={() => onToggleSort('title')}
			>{columnLabels.title} <SortChevron direction={titleSort} /></th>
			{#if col('status')}<th class="col-status">Statut</th>{/if}
			{#if col('labs')}<th
				class="col-labs sortable"
				class:active={labsSort !== null}
				onclick={() => onToggleSort('labs')}
			>{columnLabels.labs} <SortChevron direction={labsSort} /></th>{/if}
			{#if col('sources')}<th class="col-sources">{columnLabels.sources}</th>{/if}
			<th class="col-access col-menu-th">
				<ColumnMenu label={columnLabels.access} columns={cv.columns} visibleColumns={cv.visibleColumns}
					showMenu={cv.showMenu}
					onToggle={cv.toggle}
					onClose={() => cv.showMenu = false}
					onOpen={() => cv.showMenu = !cv.showMenu} />
			</th>
		</tr>
	</thead>
	<tbody>
		{#if items.length === 0}
			<TableStatusRow {loading} {error} colspan={cv.visibleColumns.length + (onopen ? 1 : 0)} emptyText="Aucune thèse" />
		{/if}
		{#each items as t (t.id)}
			{@const insc = formatDate(t.date_inscription)}
			{@const sout = formatDate(t.date_soutenance)}
			<tr class:active-row={t.id === activeId}>
				{#if onopen}
					<td class="panel-col row-actions">
						<IconButton icon="panel" label="Ouvrir le volet" onclick={() => onopen(t.id)} />
					</td>
				{/if}
				{#if col('inscription')}<td class="col-date">
					{#if insc}<span class="date-month">{insc.month}</span> {insc.year}{/if}
				</td>{/if}
				{#if col('soutenance')}<td class="col-date">
					{#if sout}<span class="date-month">{sout.month}</span> {sout.year}{/if}
				</td>{/if}
				{#if col('author')}<td class="col-author">
					{#if t.thesis_author_person_id}
						<a href={resolve(`persons/${t.thesis_author_person_id}`)}>{titleCase(t.thesis_author_name)}</a>
					{:else if t.thesis_author_name}
						{titleCase(t.thesis_author_name)}
					{/if}
				</td>{/if}
				{#if col('doi')}<td class="col-doi">
					{#if t.doi}<DoiLink doi={t.doi} />{/if}
				</td>{/if}
				<td class="col-title">
					<a href={resolve(`publications/${t.id}`)}><PublicationTitle titre={t.title} /></a>
				</td>
				{#if col('status')}<td class="col-status">
					{#if t.doc_type === 'thesis'}
						<span class="status-badge soutenue">Soutenue</span>
					{:else if t.doc_type === 'ongoing_thesis'}
						<span class="status-badge en-cours">En cours</span>
					{/if}
				</td>{/if}
				{#if col('labs')}
					<td class="col-labs">
						{#each t.lab_items || [] as lab}
							<a href={resolve(`structures/${lab.id}?tab=theses`)} class="lab-tag">{lab.label}</a>
						{/each}
					</td>
				{/if}
				{#if col('sources')}<td class="links-cell">
					<SourceLinks ids={[['hal', t.hal_id], ['openalex', t.openalex_id], ['scanr', t.scanr_id], ['theses', t.theses_id]]} urls={t.record_urls} />
				</td>{/if}
				<td class="col-access"><AccessButton accessUrl={t.access_url} oaStatus={t.oa_status} compact /></td>
			</tr>
		{/each}
	</tbody>
</table>
</TableScroll>

<style>
	.panel-col { width: 28px; padding-right: 0; }
	.theses-table {
		min-width: 720px;
		font-size: var(--fs-md);
	}

	.col-author {
		width: 160px;
	}
	.col-date {
		width: 85px;
		text-align: center;
		white-space: nowrap;
	}
	/* Taille propre aux cellules : l'en-tête garde la typographie commune des tableaux. */
	td.col-author {
		font-size: var(--fs-md);
	}
	td.col-date {
		font-size: var(--fs-sm);
	}
	.col-date .date-month {
		font-size: var(--fs-sm);
		color: var(--muted);
	}
	.col-title {
		min-width: 300px;
	}
	.col-status {
		width: 90px;
		text-align: center;
	}
	.col-labs {
		width: 180px;
	}
	.col-sources {
		width: 120px;
		text-align: center;
	}
	.col-doi {
		width: 28px;
	}
	.col-access {
		width: 120px;
		white-space: nowrap;
	}
	.status-badge {
		font-size: var(--fs-sm);
		padding: 2px 6px;
		border-radius: var(--radius);
	}
	.status-badge.soutenue {
		background: var(--success-light);
		color: var(--success);
	}
	.status-badge.en-cours {
		background: var(--attention-light);
		color: var(--attention);
	}
</style>
