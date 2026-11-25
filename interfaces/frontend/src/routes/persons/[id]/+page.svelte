<script lang="ts">
	import GraduationCap from '@lucide/svelte/icons/graduation-cap';
	import EntityBreadcrumb from '#lib/components/EntityBreadcrumb.svelte';
	import EntityStatus from '#lib/components/EntityStatus.svelte';
	import { columnLabels, sectionLabels } from '#lib/labels.js';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { onMount, untrack } from 'svelte';
	import { api, apiDetail, contributions } from '#lib/api/index.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { formatCount, plural } from '#lib/plural.js';
	import { formatDate, formatNumber, formatPercent, titleCase } from '#lib/utils.js';
	import { structureLabel } from '#lib/structureLabels.js';
	import PublicationsDashboard from '#lib/components/PublicationsDashboard.svelte';
	import SubjectsCard from '#lib/components/SubjectsCard.svelte';
	import IdentifiersCell from '#lib/components/IdentifiersCell.svelte';
	import TabNav from '#lib/components/TabNav.svelte';
	import { activeTabId, type TabDef } from '#lib/tabs.js';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import ScopedAddresses from '#lib/components/ScopedAddresses.svelte';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import { confirmDialog } from '#lib/dialogs.svelte.js';
	import TitleRow from '#lib/components/TitleRow.svelte';
	import PersonCurationDrawer from '#lib/components/persons/PersonCurationDrawer.svelte';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';
	import type { components } from '#lib/api/schema.js';

	const personId = $derived(page.params.id);
	// --- Types ---
	type Person = components['schemas']['PersonProfileCore'];
	type Identifier = components['schemas']['PersonIdentifierOut'];
	type ProfileResponse = components['schemas']['PersonProfileResponse'];
	type ThesisSection = components['schemas']['PersonThesesSection'];
	type ThesisStructInfo = components['schemas']['StructureRef'];
	type ThesesResponse = components['schemas']['PersonThesesResponse'];

	// Volet de curation de la personne, en session admin : ouvert tant que `?person=<id>` figure dans l'URL.
	const drawer = useDrawerParam('person', isAdmin);

	// --- State ---
	let profile = $state<Person | null>(null);
	let identifiers = $state<Identifier[]>([]);
	let thesesCount = $state(0);
	let error = $state(false);

	// L'onglet « Adresses » est réservé à la session admin.
	const tabs: TabDef[] = $derived([
		{ id: 'dashboard', label: 'Dashboard' },
		{ id: 'publications', label: 'Publications' },
		...(thesesCount > 0 ? [{ id: 'theses', label: 'Thèses' }] : []),
		...(isAdmin() ? [{ id: 'addresses', label: 'Adresses' }] : []),
	]);
	const activeTab = $derived(activeTabId(tabs, page.url.searchParams));

	// Theses tab
	let thesesSections: ThesisSection[] = $state([]);
	let thesesTotal = $state(0);
	let thesesStructures = $state<Record<string, ThesisStructInfo>>({});
	let thesesLoaded = $state(false);

	// Dashboard tab : les publications passent par `PublicationsDashboard` ; la page ajoute les thèses dirigées ou jugées et les sujets.

	const displayName = $derived(
		profile
			? `${titleCase(profile.first_name)} ${titleCase(profile.last_name)}`
			: ''
	);

	async function loadTheses() {
		const res = await api<ThesesResponse>(
			`/api/persons/${personId}/theses`, { key: 'person-detail-theses' }
		);
		thesesSections = res.sections;
		thesesTotal = res.total;
		thesesStructures = res.structures;
		thesesLoaded = true;
	}

	async function excludeContribution(contributionId: number) {
		if (!(await confirmDialog({ message: 'Exclure ce lien auteur–publication ? Il ne sera pas recréé automatiquement.', danger: true }))) {
			return false;
		}
		await contributions.exclude(contributionId);
		return true;
	}

	// Chargement de l'onglet affiché, à sa première ouverture, d'où que vienne le changement d'onglet : barre d'onglets, lien, retour arrière. L'onglet des publications charge ses données au montage.
	$effect(() => {
		if (!profile) return;
		if (activeTab === 'theses' && !thesesLoaded) untrack(loadTheses);
	});

	async function loadProfile(id: string) {
		try {
			const profileData = await apiDetail<ProfileResponse>(`/api/persons/${id}`);
			profile = profileData.person;
			identifiers = profileData.identifiers;
			thesesCount = profileData.theses_count;
		} catch {
			error = true;
			return;
		}
	}

	onMount(async () => {
		if (personId) await loadProfile(personId);
	});

</script>

<EntityBreadcrumb section={{ label: sectionLabels.persons, path: 'persons' }} name={displayName} fallback="Personne" />

{#if error || !profile}
	<EntityStatus {error} notFound="Personne introuvable" />
{:else}
	<!-- Profile header -->
	<div class="entity-header">
		<TitleRow onopen={isAdmin() ? () => drawer.open(profile!.id) : undefined}>
			<h1 class="entity-title">
				{titleCase(profile.first_name)}
				<span>{titleCase(profile.last_name)}</span>
			</h1>
			{#snippet identifierLinks()}
				<IdentifiersCell {identifiers} aligned={false} />
			{/snippet}
		</TitleRow>
		{#if profile.periods.length}
			<ul class="hr-periods">
				{#each profile.periods as period, i (i)}
					<li class:past-period={!period.current}>
						{#if period.structure_id != null}
							<a href={resolve(`structures/${period.structure_id}`)} class="entity-link">{period.structure_label}</a>
							{#if period.structure_label !== period.unit_label}<span class="period-unit">({period.unit_label})</span>{/if}
						{:else}
							<span class="period-structure">{period.unit_label}</span>
						{/if}
						<span class="period-dates">
							{period.start_date ? formatDate(period.start_date) : '?'}
							— {period.end_date ? formatDate(period.end_date) : 'en poste'}
						</span>
					</li>
				{/each}
			</ul>
		{/if}
	</div>

	<!-- Tabs -->
	<TabNav {tabs} keep={['person']} />

	<!-- Tab: Dashboard -->
	{#if activeTab === 'dashboard'}
		<div class="tab-content">
			{#if profile}
				<PublicationsDashboard
					context={{ kind: 'person', id: profile.id }}
					apiKey="person-detail-dashboard"
					thesesFigure={false}
					citationFigure={false}
					figures={thesesCount > 0
						? [
								{
									value: formatNumber(thesesCount),
									label: plural(thesesCount, 'thèse liée', 'thèses liées'),
									icon: GraduationCap,
									link: { tab: 'theses' },
									hoverColor: 'var(--key-figure-theses)',
								},
							]
						: []}
				>
					{#snippet subjects()}
						<SubjectsCard endpoint="/api/persons/{personId}/subjects" />
					{/snippet}
				</PublicationsDashboard>
			{/if}
		</div>
	{/if}

	<!-- Tab: Publications -->
	{#if activeTab === 'publications'}
		<div class="tab-content">
			<PublicationsListView
				apiKey={`person-${personId}-publications`}
				context={{ kind: 'person', id: Number(personId) }}
				basePath={`/persons/${personId}`}
				showAdminExclude={isAdmin()}
				onExcludeContribution={excludeContribution}
				perPage={50}
			/>
		</div>
	{/if}

	<!-- Tab: Thèses -->
	{#if activeTab === 'theses'}
		<div class="tab-content">
			{#if !thesesLoaded}
				<div class="loading">Chargement…</div>
			{:else if thesesSections.length === 0}
				<div class="no-results">Aucune thèse liée</div>
			{:else}
				{#each thesesSections as section (section.role)}
					<h2 class="thesis-role-heading">{section.label}</h2>
					<table class="data-table">
						<thead>
							<tr>
								<th style="width:160px">{columnLabels.author}</th>
								<th>{columnLabels.title}</th>
								<th style="width:100px">{columnLabels.labs}</th>
								<th style="width:50px">{columnLabels.year}</th>
							</tr>
						</thead>
						<tbody>
							{#each section.theses as t (t.id)}
								<tr>
									<td>{#if t.author_person_id}<a href={resolve(`persons/${t.author_person_id}`)}>{titleCase(t.author_name)}</a>{:else}{t.author_name ? titleCase(t.author_name) : ''}{/if}</td>
									<td><a href={resolve(`publications/${t.id}`)}><PublicationTitle titre={t.title} /></a></td>
									<td>{#each t.structure_ids as sid}<a href={resolve(`structures/${sid}`)} class="structure-link">{thesesStructures[String(sid)]?.acronym || thesesStructures[String(sid)]?.name || `#${sid}`}</a>{/each}</td>
									<td>{t.publication_year ?? ''}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/each}
			{/if}
		</div>
	{/if}

	<!-- Tab: Adresses -->
	{#if activeTab === 'addresses'}
		<div class="tab-content">
			<ScopedAddresses endpoint={`/api/persons/${personId}`} scope={{ person_id: String(personId) }} apiKey="person-detail" />
		</div>
	{/if}
{/if}

{#if drawer.id !== null}
	<PersonCurationDrawer
		personId={drawer.id}
		onclose={() => drawer.open(null)}
		onchange={() => personId && loadProfile(personId)}
		onopenPerson={drawer.open}
	/>
{/if}

<style>
	.hr-periods { list-style: none; margin: 0; padding: 0; font-size: var(--fs-md); }
	.hr-periods li { margin: 2px 0; }
	.past-period { color: var(--text-faint); }
	.past-period .entity-link { color: inherit; }
	/* Structure sans fiche : même graisse que le lien vers une fiche. */
	.period-structure { font-weight: 500; }
	.period-unit, .period-dates { color: var(--text-secondary); margin-left: 6px; }
	.past-period .period-unit, .past-period .period-dates { color: inherit; }
	.thesis-role-heading {
		font-size: var(--fs-base);
		font-weight: 600;
		margin: 20px 0 8px;
		color: var(--text);
	}
	.thesis-role-heading:first-child { margin-top: 0; }


</style>
