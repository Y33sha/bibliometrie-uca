<script lang="ts">
	import EntityMetaItem from '#lib/components/EntityMetaItem.svelte';
	import EntityBreadcrumb from '#lib/components/EntityBreadcrumb.svelte';
	import EntityStatus from '#lib/components/EntityStatus.svelte';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { onMount, tick } from 'svelte';
	import { api, apiDetail } from '#lib/api/index.js';
	import { issnLabel, serialRelationLabels } from '#lib/labels.js';
	import TabNav from '#lib/components/TabNav.svelte';
	import { activeTabId, type TabDef } from '#lib/tabs.js';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import MonographsListView from '#lib/components/MonographsListView.svelte';
	import PublicationsDashboard from '#lib/components/PublicationsDashboard.svelte';
	import SubjectsCard from '#lib/components/SubjectsCard.svelte';
	import TitleRow from '#lib/components/TitleRow.svelte';
	import SerialDrawer from '#lib/components/serials/SerialDrawer.svelte';
	import { issnPortalUrl } from '#lib/utils.js';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import type { components } from '#lib/api/schema.js';

	type SerialDetail = components['schemas']['SerialDetailResponse'];
	type EnumOption = components['schemas']['EnumOption'];

	const serialId = $derived(Number(page.params.id));

	// Volet d'édition de la publication en série, en session admin : ouvert tant que `?serial=<id>` figure dans l'URL.
	const drawer = useDrawerParam('serial', isAdmin);
	let journal = $state<SerialDetail | null>(null);

	// Onglet des monographies, selon le type de la revue : volumes d'une série d'actes, livres d'une collection.
	const MONOGRAPHS_TAB_LABELS: Record<string, string> = { proceedings: 'Volumes', book_series: 'Livres' };
	const monographsTabLabel = $derived(journal?.serial_type ? MONOGRAPHS_TAB_LABELS[journal.serial_type] : undefined);
	const tabs: TabDef[] = $derived([
		{ id: 'dashboard', label: 'Dashboard' },
		...(monographsTabLabel ? [{ id: 'monographs', label: monographsTabLabel }] : []),
		{ id: 'publications', label: 'Publications' },
	]);
	const activeTab = $derived(activeTabId(tabs, page.url.searchParams));
	let error = $state(false);

	let showRawDoaj = $state(false);

	let oaModelLabels: Record<string, string> = $state({});

	// Sélection des champs DOAJ « lisibles ». Le payload complet est exposé via le toggle (« Voir payload brut ») pour permettre l'exploration au-delà de cette sélection.
	const READABLE_DOAJ_FIELDS: { key: string; label: string }[] = [
		{ key: 'Journal license', label: 'Licence' },
		{ key: 'Country of publisher', label: 'Pays' },
		{ key: 'Publisher', label: 'Éditeur (DOAJ)' },
		{ key: 'Languages in which the journal accepts manuscripts', label: 'Langues' },
		{ key: 'Subjects', label: 'Sujets (DOAJ)' },
		{ key: 'When did the journal start to publish all content using an open license?', label: 'OA depuis' },
		{ key: 'Journal article processing charges (APCs)', label: 'APC' },
		{ key: 'APC amount', label: 'Montant APC' },
		{ key: 'APC currency', label: 'Devise APC' }
	];

	async function loadSerial() {
		try {
			journal = await apiDetail<SerialDetail>(`/api/serials/${serialId}`);
		} catch {
			error = true;
		}
	}

	onMount(async () => {
		const labelMap = (opts: EnumOption[]) => Object.fromEntries(opts.map((o) => [o.value, o.label_fr]));
		const oaModelLabelsP = api<EnumOption[]>('/api/serials/oa-models').then((opts) => {
			oaModelLabels = labelMap(opts);
		});
		await Promise.all([loadSerial(), oaModelLabelsP]);
		await tick();
	});

	function formatDate(iso: string | null): string {
		if (!iso) return '';
		return new Date(iso).toLocaleDateString('fr-FR');
	}

	/** Filtre de la liste des revues qui retient les revues d'une liste, ou d'un niveau de classement. */
	function listQuery(list: { code: string; is_level: boolean }): string {
		return list.is_level ? `list_level=${list.code}` : `list_filter=${list.code}_yes`;
	}

	/** Organisme et édition d'une liste, pour l'info-bulle de son lien. */
	function listTitle(list: { maintainer: string | null; edition: string | null }): string {
		return [list.maintainer, list.edition ? `édition du ${formatDate(list.edition)}` : null]
			.filter(Boolean)
			.join(', ');
	}
</script>

<EntityBreadcrumb section={{ label: 'Publications en série', path: 'journals' }} name={journal?.title} fallback="Publication en série" />

{#if error || !journal}
	<EntityStatus {error} notFound="Publication en série introuvable" />
{:else}
	<!-- Header -->
	<div class="entity-header">
		<TitleRow onopen={isAdmin() ? () => drawer.open(serialId) : undefined}>
			<h1 class="entity-title">{journal.title}</h1>
			{#snippet identifierLinks()}
				<span class="serial-issns">
					{#each journal!.issn_details.filter((i) => i.status === 'active' || i.linking) as issn (issn.issn)}
						<span><span class="issn-label">{issnLabel(issn)}</span> <a href={issnPortalUrl(issn.issn)} target="_blank" rel="noopener" title="Portail ISSN (nouvel onglet)">{issn.issn}</a></span>
					{/each}
				</span>
			{/snippet}
		</TitleRow>
		{#if journal.publisher_name || journal.oa_model}
			<div class="entity-meta">
				{#if journal.publisher_id}
					<a href={resolve(`publishers/${journal.publisher_id}`)}>{journal.publisher_name}</a>
				{:else if journal.publisher_name}
					<span>{journal.publisher_name}</span>
				{/if}
				{#if journal.oa_model}
					<span>Modèle {oaModelLabels[journal.oa_model] ?? journal.oa_model}</span>
				{/if}
			</div>
		{/if}
		{#if journal.relations.length}
			<div class="entity-meta">
				{#each journal.relations as relation (`${relation.kind}-${relation.serial_id ?? relation.issn}`)}
					<EntityMetaItem label={serialRelationLabels[relation.kind]}>
						{#if relation.serial_id}
							<a href={resolve(`journals/${relation.serial_id}`)}>{relation.title}</a>
						{:else if relation.issn}
							<a href={issnPortalUrl(relation.issn)} target="_blank" rel="noopener" title="Portail ISSN (nouvel onglet)">{relation.issn}</a>
						{/if}
					</EntityMetaItem>
				{/each}
			</div>
		{/if}
		{#if journal.lists.length}
			<div class="entity-meta">
				<EntityMetaItem label="Listes">
					{#each journal.lists as list (list.code)}
						<a class="list-link" href={resolve(`journals?${listQuery(list)}`)} title={listTitle(list)}>{list.label}</a>
					{/each}
				</EntityMetaItem>
			</div>
		{/if}
	</div>

	<!-- Tabs -->
	<TabNav {tabs} />

	<!-- Tab: Dashboard -->
	{#if activeTab === 'dashboard'}
		<div class="tab-content">
			<PublicationsDashboard
				context={{ kind: 'serial', id: serialId }}
				apiKey="serial-dashboard"
				countries={false}
				oaBreakdown="oa_voie"
			>
				{#snippet subjects()}
					<SubjectsCard endpoint="/api/serials/{serialId}/subjects" />
				{/snippet}
			</PublicationsDashboard>
			{#if journal.doaj_payload}
				<div class="dash-grid doaj-grid">
						<div class="dash-card dash-card-wide">
							<h2>
								Données DOAJ
								{#if journal.doaj_imported_at}
									<span class="muted small">(import {formatDate(journal.doaj_imported_at)})</span>
								{/if}
								{#if journal.doaj_url}
									<a class="small" href={journal.doaj_url} target="_blank" rel="noopener">Fiche DOAJ</a>
								{/if}
							</h2>
							<dl class="doaj-fields">
								{#each READABLE_DOAJ_FIELDS as f (f.key)}
									{#if journal.doaj_payload[f.key]}
										<dt>{f.label}</dt>
										<dd>{journal.doaj_payload[f.key]}</dd>
									{/if}
								{/each}
							</dl>
							<button class="btn-text" onclick={() => (showRawDoaj = !showRawDoaj)}>
								{showRawDoaj ? 'Masquer' : 'Voir'} le payload DOAJ brut <span class="chevron" class:up={showRawDoaj} aria-hidden="true"></span>
							</button>
							{#if showRawDoaj}
								<pre class="raw-payload">{JSON.stringify(journal.doaj_payload, null, 2)}</pre>
							{/if}
						</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- Tab: Monographies -->
	{#if activeTab === 'monographs'}
		<div class="tab-content">
			<MonographsListView apiKey={`journal-${serialId}-monographs`} externalFilters={{ serialId }} />
		</div>
	{/if}

	<!-- Tab: Publications -->
	{#if activeTab === 'publications'}
		<div class="tab-content">
			<PublicationsListView
				apiKey={`journal-${serialId}-publications`}
				context={{ kind: 'serial', id: serialId }}
				basePath={`/journals/${serialId}`}
				perPage={50}
			/>
		</div>
	{/if}
{/if}

{#if drawer.id !== null}
	<SerialDrawer id={drawer.id} onclose={() => drawer.open(null)} onchange={loadSerial} />
{/if}

<style>
	/* ISSN de la revue, à la suite du titre : texte discret, libellé du support en retrait. */
	.serial-issns {
		display: inline-flex;
		flex-wrap: wrap;
		gap: 4px 14px;
		font-size: var(--fs-sm);
		color: var(--text-secondary);
	}
	.issn-label {
		color: var(--muted);
	}
	/* Listes de la revue : liens texte discrets, séparés par un point médian. */
	.list-link {
		color: var(--text-secondary);
	}
	/* En bloc en ligne, le point échappe au soulignement du lien survolé. */
	.list-link + .list-link::before {
		content: '·';
		display: inline-block;
		margin-right: 8px;
		color: var(--muted);
	}

	.doaj-grid { margin-top: 24px; }
	.small { font-size: var(--fs-sm); font-weight: 400; }

	.doaj-fields {
		display: grid; grid-template-columns: max-content 1fr;
		gap: 4px 16px; margin: 0 0 12px;
	}
	.doaj-fields dt { font-weight: 600; color: var(--muted); font-size: var(--fs-sm); }
	.doaj-fields dd { margin: 0; font-size: var(--fs-md); }
	.raw-payload {
		background: var(--surface); padding: 12px; border-radius: var(--radius);
		font-size: var(--fs-sm); max-height: 400px; overflow: auto;
		white-space: pre-wrap; word-break: break-word;
	}
</style>
