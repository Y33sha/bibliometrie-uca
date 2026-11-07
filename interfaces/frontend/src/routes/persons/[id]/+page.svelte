<script lang="ts">
	import EntityBreadcrumb from '#lib/components/EntityBreadcrumb.svelte';
	import EntityStatus from '#lib/components/EntityStatus.svelte';
	import { columnLabels } from '#lib/labels.js';
	import { page } from '$app/state';
	import { resolve } from '$app/paths';
	import { onMount } from 'svelte';
	import { api, apiDetail, contributions } from '#lib/api/index.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { formatCount, plural } from '#lib/plural.js';
	import { titleCase, formatDate } from '#lib/utils.js';
	import { structureLabel } from '#lib/structureLabels.js';
	import PublicationsDashboard from '#lib/components/PublicationsDashboard.svelte';
	import SubjectsCard from '#lib/components/SubjectsCard.svelte';
	import IdentifiersCell from '#lib/components/IdentifiersCell.svelte';
	import TabNav from '#lib/components/TabNav.svelte';
	import { activeTabId, type TabDef } from '#lib/tabs.js';
	import ListStatus from '#lib/components/ListStatus.svelte';
	import Pagination from '#lib/components/Pagination.svelte';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import PublicationTitle from '#lib/components/PublicationTitle.svelte';
	import AddressPublications from '#lib/components/AddressPublications.svelte';
	import PublicationCountButton from '#lib/components/PublicationCountButton.svelte';
	import BarChart, { BAR_LABEL_SPACE } from '#lib/components/charts/BarChart.svelte';
	import YearSlider, { YEAR_TRACK_INSET } from '#lib/components/YearSlider.svelte';
	import { confirmDialog } from '#lib/dialogs.svelte.js';
	import TitleRow from '#lib/components/TitleRow.svelte';
	import PersonCurationDrawer from '#lib/components/persons/PersonCurationDrawer.svelte';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';
	import { usePaginatedFetch } from '#lib/composables/usePaginatedFetch.svelte.js';
	import type { components } from '#lib/api/schema.js';

	const personId = $derived(page.params.id);
	// --- Types ---
	type Person = components['schemas']['PersonProfileCore'];
	type Identifier = components['schemas']['PersonIdentifierOut'];
	type ProfileResponse = components['schemas']['PersonProfileResponse'];
	type Address = components['schemas']['PersonAddressOut'];
	type AddressSummary = components['schemas']['PersonAddressSummary'];
	type AddressPublication = components['schemas']['AddressPublicationItem'];
	type AddressPublicationsResponse = components['schemas']['AddressPublicationsResponse'];
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

	// Addresses tab : adresses et structures reconnues sur les publications d'une année.
	const currentYear = new Date().getFullYear();
	let addrYear = $state(currentYear);
	let addrSummary = $state<AddressSummary | null>(null);
	const addrYearMin = $derived(Math.min(addrSummary?.first_year_with_address ?? currentYear, currentYear));
	const addrYearMax = $derived(Math.min(addrSummary?.last_year_with_address ?? currentYear, currentYear));
	const addresses = usePaginatedFetch<Address>({
		endpoint: () => `/api/persons/${personId}/addresses`,
		itemsKey: 'addresses',
		apiKey: 'person-detail-addresses',
		buildParams: () => new URLSearchParams({ year: String(addrYear) }),
		pageParam: null,
	});
	// Publications avec adresse où figure chaque structure, et leur part.
	const addrStructures = $derived(addrSummary?.structures ?? []);
	const addrShare = (publications: number) =>
		`${Math.round((100 * publications) / (addrSummary?.publications_with_address || 1))} %`;
	const publicationCount = (n: number) => formatCount(n, 'publication');
	// Largeur réservée aux libellés des structures, à gauche de l'axe du graphique.
	const ADDR_AXIS_WIDTH = 120;
	let expandedAddrId = $state<number | null>(null);
	let addrPublications = $state<AddressPublication[]>([]);
	let addrPublicationsLoading = $state(false);

	async function loadAddressSummary() {
		addrSummary = await api<AddressSummary>(
			`/api/persons/${personId}/address-summary?year=${addrYear}`,
			{ key: 'person-detail-address-summary' }
		);
	}

	function loadAddressTab() {
		expandedAddrId = null;
		addresses.page = 1;
		loadAddressSummary();
		addresses.load();
	}

	// Ouverture de l'onglet : bornes du curseur lues, puis année la plus récente du curseur.
	async function openAddressTab() {
		await loadAddressSummary();
		if (addrYear === addrYearMax) {
			addresses.load();
			return;
		}
		addrYear = addrYearMax;
		loadAddressTab();
	}

	async function toggleAddressPublications(addrId: number) {
		if (expandedAddrId === addrId) {
			expandedAddrId = null;
			return;
		}
		expandedAddrId = addrId;
		addrPublications = [];
		addrPublicationsLoading = true;
		const params = new URLSearchParams({ person_id: String(personId), year: String(addrYear), limit: '500' });
		const data = await api<AddressPublicationsResponse>(`/api/addresses/${addrId}/publications?${params}`, {
			key: 'person-detail-address-publications',
		});
		addrPublications = data.publications;
		addrPublicationsLoading = false;
	}

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

	function onTabSwitch(tab: string) {
		// L'onglet "publications" est géré par <PublicationsListView> qui charge ses données dans son propre onMount à chaque (re)montage.
		if (tab === 'theses' && !thesesLoaded) loadTheses();
		if (tab === 'addresses' && !addresses.loaded) openAddressTab();
	}

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
		if (activeTab === 'addresses') openAddressTab();
		else if (activeTab === 'theses') loadTheses();
		// publications : géré par <PublicationsListView> qui charge tout seul.
	}

	onMount(async () => {
		if (personId) await loadProfile(personId);
	});

</script>

<EntityBreadcrumb section={{ label: 'Chercheurs', path: 'persons' }} name={displayName} fallback="Personne" />

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
	<TabNav {tabs} onswitch={onTabSwitch} />

	<!-- Tab: Dashboard -->
	{#if activeTab === 'dashboard'}
		<div class="tab-content">
			{#if profile}
				<PublicationsDashboard
					context={{ kind: 'person', id: profile.id }}
					apiKey="person-detail-dashboard"
					thesesFigure={false}
					citationFigure={false}
					countries={false}
					figures={thesesCount > 0
						? [
								{
									value: thesesCount.toLocaleString('fr-FR'),
									label: plural(thesesCount, 'thèse liée', 'thèses liées'),
									icon: 'graduation-cap',
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
			<div class="addr-overview">
				<h2>Structures reconnues dans les adresses</h2>
				<div class="addr-year">
					<div class="addr-year-label">Année <strong>{addrYear}</strong></div>
					<YearSlider min={addrYearMin} max={addrYearMax} bind:value={addrYear} onchange={loadAddressTab} />
				</div>
				{#if addrStructures.length}
					<!-- Axe des valeurs aligné sur la piste du curseur ; libellés des structures et pourcentages en débord. -->
					<div
						style:margin-left="{YEAR_TRACK_INSET - ADDR_AXIS_WIDTH}px"
						style:width="calc(100% + {ADDR_AXIS_WIDTH + BAR_LABEL_SPACE - 2 * YEAR_TRACK_INSET}px)"
					>
						<BarChart
							labels={addrStructures.map((s) => structureLabel(s))}
							values={addrStructures.map((s) => s.publications)}
							datasetLabel="Publications avec adresse"
							barLabel={addrShare}
							tooltipLabel={publicationCount}
							max={addrSummary?.publications_with_address}
							horizontal
							prominentLabels
							categoryAxisWidth={ADDR_AXIS_WIDTH}
							height={32 * addrStructures.length + 40}
						/>
					</div>
				{:else if addrSummary}
					<p class="addr-counts">Aucune structure reconnue.</p>
				{/if}
			</div>
			<ListStatus list={addresses} emptyText="Aucune adresse">
				<table class="data-table">
					<thead>
						<tr>
							<th>{columnLabels.address}</th>
							<th style="width:160px">Structures</th>
							<th style="width:120px">Publications</th>
						</tr>
					</thead>
					<tbody>
						{#each addresses.items as a (a.id)}
							<tr>
								<td class="addr-cell">{a.raw_text}</td>
								<td>
									{#if a.structures?.length}
										{#each a.structures as s (s.id)}
											<span class="tag tag-accent">{structureLabel(s)}</span>
										{/each}
									{/if}
								</td>
								<td>
									<PublicationCountButton
										count={a.publication_count}
										expanded={expandedAddrId === a.id}
										onclick={() => toggleAddressPublications(a.id)}
									/>
								</td>
							</tr>
							{#if expandedAddrId === a.id}
								<tr>
									<td colspan="3" class="addr-publications">
										<AddressPublications publications={addrPublications} loading={addrPublicationsLoading} />
									</td>
								</tr>
							{/if}
						{/each}
					</tbody>
				</table>
				<Pagination page={addresses.page} pages={addresses.pages} onchange={(p) => { addresses.page = p; expandedAddrId = null; addresses.load(); }} />
			</ListStatus>
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


	/* Addresses tab */
	.addr-overview {
		width: 300px;
		margin: 0 auto 16px;
	}
	.addr-overview h2 { font-size: var(--fs-base); font-weight: 600; margin: 0 0 8px; }
	.addr-year {
		display: flex;
		flex-direction: column;
		gap: 4px;
		margin-bottom: 20px;
	}
	.addr-year-label { font-size: var(--fs-md); }
	.addr-counts { font-size: var(--fs-sm); color: var(--text-secondary); margin: 0; }
	.addr-cell { font-size: var(--fs-sm); color: var(--muted); word-break: break-all; }
	.addr-publications { padding: 0 12px 12px 24px; }
</style>
