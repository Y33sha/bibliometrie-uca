<script lang="ts">
	import PageHeader from '#lib/components/PageHeader.svelte';
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import ActiveFilterBar from '#lib/components/ActiveFilterBar.svelte';
	import FilterPanel from '#lib/components/filters/FilterPanel.svelte';
	import FilterLayout from '#lib/components/filters/FilterLayout.svelte';
	import FilterPanelToggle from '#lib/components/filters/FilterPanelToggle.svelte';
	import PivotControls from '#lib/components/stats/PivotControls.svelte';
	import PivotChart from '#lib/components/stats/PivotChart.svelte';
	import { useFilterPanel } from '#lib/composables/useFilterPanel.svelte.js';
	import { usePivotChart, type ChartMode, type PivotSettings } from '#lib/composables/usePivotChart.svelte.js';
	import { defaultYears } from '#lib/defaultYears.js';
	import { paramsToQuery } from '#lib/utils.js';
	import { publicationsDocTypes } from '#lib/docTypes.svelte.js';
	import { toast } from '#lib/dialogs.svelte.js';
	import {
		activeCount,
		appendFilterParams,
		clearValue,
		ignoredFilters,
		initialValues,
		restoreValues,
		transferParams,
		urlFilterDefs,
		urlState,
	} from '#lib/filterRegistry.js';
	import { PUBLICATION_FILTER_GROUPS, publicationFilters } from '#lib/publicationFilters.js';
	import { PUBLICATION_FACETS_ENDPOINT, usePublicationFacets } from '#lib/composables/usePublicationFacets.svelte.js';
	import { useUrlFilters } from '#lib/composables/useUrlFilters.svelte.js';

	// Filtres de la liste des publications, hors contexte. La famille « Publications » est présélectionnée (cf. onMount).
	const FILTERS = publicationFilters({ kind: 'all' }, publicationsDocTypes());
	let values = $state(initialValues(FILTERS));
	const filterPanel = useFilterPanel();

	// --- Filter params (partagés par le graphe et les facettes) ---
	function chartParams(): URLSearchParams {
		const p = new URLSearchParams();
		appendFilterParams(FILTERS, values, p);
		return p;
	}

	// --- Composable: facets ---
	const facets = usePublicationFacets({
		filters: FILTERS,
		apiKey: () => 'stats-facets',
		buildParams: chartParams,
	});

	// --- Graphique ---
	const pivot = usePivotChart({
		buildParams: chartParams,
		// Libellés servis par la facette, y compris celui des publications sans licence.
		licenseLabel: (value) => facets.options.license?.find((o) => o.value === value)?.text,
		onsettingchange: () => syncUrl(),
	});

	// --- Composable: URL filters ---
	const urlFilters = useUrlFilters({
		basePath: '/stats',
		filters: {
			...urlFilterDefs(FILTERS),
			// La page a ses années par défaut : « toutes les années » s'écrit donc dans l'URL.
			years: { type: 'single', urlKey: 'year', defaultValue: '' },
			indicator: { type: 'single', urlKey: 'indicator', defaultValue: 'doc_type_grouped' },
			groupBy: { type: 'single', urlKey: 'group_by', defaultValue: 'year' },
			chartMode: { type: 'single', urlKey: 'mode', defaultValue: 'absolu' },
			chartPage: { type: 'page', urlKey: 'chart_page' },
			chartSort: { type: 'single', urlKey: 'sort', defaultValue: '' },
			chartSortDir: { type: 'single', urlKey: 'sort_dir', defaultValue: 'desc' },
		},
	});

	function syncUrl() {
		urlFilters.syncUrl(() => ({
			...urlState(FILTERS, values),
			...pivot.settings,
		}));
	}

	// --- Derived: publications link ---
	// Les filtres passent tels quels : les deux pages partagent le registre des filtres.
	const pubsUrl = $derived(resolve('publications') + '?' + paramsToQuery(transferParams(FILTERS, values)));

	// --- Data loading ---
	async function refresh() {
		await Promise.all([pivot.load(), facets.load()]);
	}

	function onFilterChange() {
		syncUrl();
		refresh();
	}

	onMount(async () => {
		// Restore state from URL params
		const u = new URLSearchParams(window.location.search);
		const restored = urlFilters.restoreFromUrl(u);
		restoreValues(FILTERS, restored, values);
		const settings: Partial<PivotSettings> = {};
		if (restored.indicator !== undefined) settings.indicator = restored.indicator as string;
		if (restored.groupBy !== undefined) settings.groupBy = restored.groupBy as string;
		if (restored.chartMode !== undefined) settings.chartMode = restored.chartMode as ChartMode;
		if (restored.chartPage) settings.chartPage = restored.chartPage as number;
		if (restored.chartSort !== undefined) settings.chartSort = restored.chartSort as string;
		if (restored.chartSortDir !== undefined) settings.chartSortDir = restored.chartSortDir as 'desc' | 'asc';
		pivot.restore(settings);

		// Un lien venu de la liste peut contenir une recherche, ou un filtre propre à un laboratoire ou à une personne : ils sont annoncés, puis retirés.
		const ignored = ignoredFilters(FILTERS, values);
		const term = u.get('search')?.trim();
		const lost = [
			...ignored.map((f) => `filtre « ${f.label} »`),
			...(term ? [`recherche « ${term} »`] : []),
		];
		if (lost.length) {
			toast(`Non pris en compte dans les statistiques : ${lost.join(', ')}`, 'warning', 6000);
			for (const f of ignored) clearValue(f, values);
			syncUrl();
		}

		// Vocabulaire du pivot : dimensions graphables (faible cardinalité, hors l'axe année) proposées au sélecteur de découpage. Ajouter une dimension au registre l'y fait apparaître.
		await pivot.loadSchema();

		// Défaut du type de document : la famille « Publications ». Appliqué uniquement quand l'URL ne porte pas de filtre de types ; le jeton `all` (sélection vide explicite) le laisse vide.
		if (!u.has('doc_type')) {
			values.checkbox.docTypes = publicationsDocTypes();
		}

		await facets.load();
		// Années par défaut : les années récentes, seulement quand l'URL ne fixe pas les années. Le jeton `all` (toutes les années, par exemple depuis la liste) les laisse vides.
		const yearOptions = facets.options.years ?? [];
		if (!u.has('year') && yearOptions.length > 0) {
			values.checkbox.years = defaultYears(yearOptions.map((o) => o.value), new Date().getFullYear());
			syncUrl();
		}
		refresh();
	});
</script>

<PageHeader title="Statistiques" hidden />

<div class="stats-page">
<!-- Ligne 1 : panneau des filtres, réglages du graphique, lien vers les publications -->
<div class="toolbar controls-row">
	<FilterPanelToggle bind:open={filterPanel.open} active={activeCount(FILTERS, values)} />
	<span class="toolbar-sep" aria-hidden="true"></span>
	<PivotControls chart={pivot} />
	<a class="btn btn-primary pubs-link" href={pubsUrl}>Voir les publications &rarr;</a>
</div>
<!-- Ligne 2 : filtres actifs, ceux de la liste des publications. -->
<div class="stats-filters">
	<ActiveFilterBar filters={FILTERS} bind:values options={facets.options} onchange={onFilterChange} />
</div>

<FilterLayout bind:open={filterPanel.open} fill>
{#snippet panel()}
	<FilterPanel filters={FILTERS} groups={PUBLICATION_FILTER_GROUPS} bind:values options={facets.options} sourceCounts={facets.sourceCounts} entityEndpoint={PUBLICATION_FACETS_ENDPOINT} buildParams={chartParams} panel={filterPanel} onchange={onFilterChange} />
{/snippet}
<PivotChart chart={pivot} />
</FilterLayout>
</div>


<style>
	.pubs-link { margin-left: auto; }

	.stats-filters {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin-bottom: 16px;
	}

	/* Colonne pleine hauteur : barres d'outils, légende et pagination gardent leur hauteur naturelle, le diagramme occupe l'espace restant du viewport. Hauteur = viewport moins l'en-tête fixe et le padding vertical du conteneur. */
	.stats-page {
		display: flex;
		flex-direction: column;
		height: calc(100vh - var(--header-height) - 48px);
	}
</style>
