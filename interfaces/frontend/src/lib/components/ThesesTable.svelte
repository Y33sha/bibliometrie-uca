<script lang="ts">
	import AccessButton from '#lib/components/AccessButton.svelte';
	import ColumnMenu from '#lib/components/ColumnMenu.svelte';
	import DoiLink from '#lib/components/DoiLink.svelte';
	import SortChevron from '#lib/components/SortChevron.svelte';
	import { asset, resolve } from '$app/paths';
	import { titleCase } from '#lib/utils.js';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import TableStatusRow from '#lib/components/TableStatusRow.svelte';
	import { useColumnVisibility } from '#lib/composables/useColumnVisibility.svelte.js';
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

	export type ThesisSortColumn = 'inscription' | 'soutenance' | 'title';

	let {
		items,
		loading = false,
		sort,
		onToggleSort,
		showLabsColumn = false,
	}: {
		items: ThesisRow[];
		loading?: boolean;
		sort: PublicationSort;
		onToggleSort: (column: ThesisSortColumn) => void;
		showLabsColumn?: boolean;
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

	// La visibilité des colonnes est partagée avec la liste des publications : seules DOI et Sources sont optionnelles.
	const columnDefs = [
		{ key: 'inscription', label: 'Inscription', fixed: true },
		{ key: 'soutenance',  label: 'Soutenance',  fixed: true },
		{ key: 'author',      label: 'Auteur',      fixed: true },
		{ key: 'doi',         label: 'DOI' },
		{ key: 'title',       label: 'Titre',       fixed: true },
		{ key: 'status',      label: 'Statut',      fixed: true },
		// svelte-ignore state_referenced_locally
		...(showLabsColumn ? [{ key: 'labs', label: 'Laboratoire(s)', fixed: true }] : []),
		{ key: 'sources',     label: 'Sources' },
		{ key: 'access',      label: 'Accès',       fixed: true },
	];
	const cv = useColumnVisibility(columnDefs, ['sources']);
	const col = cv.col;

	const inscrSort = $derived(sortDirection(sort, 'inscription'));
	const soutSort = $derived(sortDirection(sort, 'soutenance'));
	const titleSort = $derived(sortDirection(sort, 'title'));
</script>

<div class="table-scroll">
<table class="data-table theses-table">
	<thead>
		<tr>
			<th
				class="col-date sortable"
				class:active={inscrSort !== null}
				onclick={() => onToggleSort('inscription')}
			>Inscription <SortChevron direction={inscrSort} /></th>
			<th
				class="col-date sortable"
				class:active={soutSort !== null}
				onclick={() => onToggleSort('soutenance')}
			>Soutenance <SortChevron direction={soutSort} /></th>
			<th class="col-author">Auteur</th>
			{#if col('doi')}<th class="col-doi">DOI</th>{/if}
			<th
				class="col-title sortable"
				class:active={titleSort !== null}
				onclick={() => onToggleSort('title')}
			>Titre <SortChevron direction={titleSort} /></th>
			<th class="col-status">Statut</th>
			{#if showLabsColumn}
				<th class="col-labs">Laboratoire(s)</th>
			{/if}
			{#if col('sources')}<th class="col-sources">Sources</th>{/if}
			<th class="col-access col-menu-th">
				Accès
				<ColumnMenu columns={cv.columns} visibleColumns={cv.visibleColumns}
					showMenu={cv.showMenu}
					onToggle={cv.toggle}
					onClose={() => cv.showMenu = false}
					onOpen={() => cv.showMenu = !cv.showMenu} />
			</th>
		</tr>
	</thead>
	<tbody>
		{#if items.length === 0}
			<TableStatusRow {loading} colspan={cv.visibleColumns.length} emptyText="Aucune thèse" />
		{/if}
		{#each items as t (t.id)}
			{@const insc = formatDate(t.date_inscription)}
			{@const sout = formatDate(t.date_soutenance)}
			<tr>
				<td class="col-date">
					{#if insc}<span class="date-month">{insc.month}</span> {insc.year}{/if}
				</td>
				<td class="col-date">
					{#if sout}<span class="date-month">{sout.month}</span> {sout.year}{/if}
				</td>
				<td class="col-author">
					{#if t.thesis_author_person_id}
						<a href={resolve(`persons/${t.thesis_author_person_id}`)}>{titleCase(t.thesis_author_name)}</a>
					{:else if t.thesis_author_name}
						{titleCase(t.thesis_author_name)}
					{/if}
				</td>
				{#if col('doi')}<td class="col-doi">
					{#if t.doi}<DoiLink doi={t.doi} />{/if}
				</td>{/if}
				<td class="col-title">
					<a href={resolve(`publications/${t.id}`)}><PublicationTitle titre={t.title} /></a>
				</td>
				<td class="col-status">
					{#if t.doc_type === 'thesis'}
						<span class="status-badge soutenue">Soutenue</span>
					{:else if t.doc_type === 'ongoing_thesis'}
						<span class="status-badge en-cours">En cours</span>
					{/if}
				</td>
				{#if showLabsColumn}
					<td class="col-labs">
						{#each t.lab_items || [] as lab}
							<a href={resolve(`structures/${lab.id}?tab=theses`)} class="lab-tag">{lab.label}</a>
						{/each}
					</td>
				{/if}
				{#if col('sources')}<td class="links-cell">
					{#if t.hal_id}
						<a
							href={t.record_urls.hal}
							target="_blank"
							rel="noopener"
							class="source-tag source-hal"
							title="HAL: {t.hal_id}"
						>
							<img src={asset('icons/hal.ico')} alt="HAL" />
						</a>
					{:else}
						<span class="source-tag source-placeholder"></span>
					{/if}
					{#if t.openalex_id}
						<a
							href={t.record_urls.openalex}
							target="_blank"
							rel="noopener"
							class="source-tag source-openalex"
							title="OpenAlex: {t.openalex_id}"
						>
							<img src={asset('icons/openalex.png')} alt="OA" />
						</a>
					{:else}
						<span class="source-tag source-placeholder"></span>
					{/if}
					{#if t.scanr_id}
						<a
							href={t.record_urls.scanr}
							target="_blank"
							rel="noopener"
							class="source-tag source-scanr"
							title="ScanR: {t.scanr_id}"
						>
							<img src={asset('scanr-icon.svg')} alt="ScanR" />
						</a>
					{:else}
						<span class="source-tag source-placeholder"></span>
					{/if}
					{#if t.theses_id}
						<a
							href={t.record_urls.theses}
							target="_blank"
							rel="noopener"
							class="source-tag source-theses"
							title="theses.fr: {t.theses_id}"
						>
							<img src={asset('icons/theses.ico')} alt="theses.fr" />
						</a>
					{:else}
						<span class="source-tag source-placeholder"></span>
					{/if}
				</td>{/if}
				<td class="col-access"><AccessButton url={t.access_url} oaStatus={t.oa_status} compact /></td>
			</tr>
		{/each}
	</tbody>
</table>
</div>

<style>
	.theses-table {
		min-width: 720px;
		font-size: 0.9rem;
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
		font-size: 0.9rem;
	}
	td.col-date {
		font-size: 0.85rem;
	}
	.col-date .date-month {
		font-size: 0.75rem;
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
	.col-menu-th {
		position: relative;
	}

	.status-badge {
		font-size: 0.75rem;
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
