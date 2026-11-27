<script lang="ts">
	import GraduationCap from '@lucide/svelte/icons/graduation-cap';
	import User from '@lucide/svelte/icons/user';
	import { sectionLabels } from '#lib/labels.js';
	import { formatNumber } from '#lib/utils.js';
	import EntityBreadcrumb from '#lib/components/EntityBreadcrumb.svelte';
	import EntityStatus from '#lib/components/EntityStatus.svelte';
	import { page } from '$app/state';
	import { onMount, untrack } from 'svelte';
	import { api } from '#lib/api/index.js';
	import { plural } from '#lib/plural.js';
	import IdentifierLink from '#lib/components/IdentifierLink.svelte';
	import { structureLabel } from '#lib/structureLabels.js';
	import PublicationsDashboard from '#lib/components/PublicationsDashboard.svelte';
	import SubjectsCard from '#lib/components/SubjectsCard.svelte';
	import PersonsListView from '#lib/components/PersonsListView.svelte';
	import TabNav from '#lib/components/TabNav.svelte';
	import { activeTabId, type TabDef } from '#lib/tabs.js';
	import ThesesListView from '#lib/components/ThesesListView.svelte';
	import PublicationsListView from '#lib/components/PublicationsListView.svelte';
	import ScopedAddresses from '#lib/components/ScopedAddresses.svelte';
	import PartnersTab from './PartnersTab.svelte';
	import StructureDrawer from '#lib/components/structures/StructureDrawer.svelte';
	import TitleRow from '#lib/components/TitleRow.svelte';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { isAdmin } from '#lib/session.svelte.js';

	const labId = $derived(page.params.id);
	// --- Types ---
	import type { components } from '#lib/api/schema.js';
	type Structure = components['schemas']['StructureOut'];
	type LabProfile = components['schemas']['StructureDetailResponse'];

	// Volet d'édition de la structure, en session admin : ouvert tant que `?structure=<id>` figure dans l'URL.
	const drawer = useDrawerParam('structure', isAdmin);

	// --- State ---
	let lab: Structure | null = $state(null);
	let thesesCount = $state(0);
	let membersCount = $state(0);
	let hasPartners = $state(false);
	let hasAddresses = $state(false);
	let error = $state(false);

	// Les onglets Thèses, Collaborations et Adresses s'affichent seulement quand leur liste est non vide. L'onglet « Adresses » est réservé à la session admin.
	const tabs: TabDef[] = $derived([
		{ id: 'dashboard', label: 'Dashboard' },
		{ id: 'publications', label: 'Publications' },
		...(thesesCount > 0 ? [{ id: 'theses', label: 'Thèses' }] : []),
		{ id: 'persons', label: 'Personnes' },
		...(hasPartners ? [{ id: 'collaborations', label: 'Collaborations' }] : []),
		...(isAdmin() && hasAddresses ? [{ id: 'addresses', label: 'Adresses' }] : []),
	]);
	const activeTab = $derived(activeTabId(tabs, page.url.searchParams));

	// Dashboard tab : les publications passent par `PublicationsDashboard` ; la page ajoute les thèses en cours, les personnes rattachées au laboratoire et les sujets.
	let dashboardLoaded = $state(false);
	let ongoingThesesCount = $state(0);

	async function loadDashboard() {
		// Le décompte des thèses en cours reprend le filtre « En cours » de l'onglet Thèses.
		const ongoingTheses = new URLSearchParams({ lab_id: String(labId), doc_type: 'ongoing_thesis', per_page: '1' });
		const ongoingThesesPage = await api<{ total: number }>(`/api/publications?${ongoingTheses}`, { key: 'lab-ongoing-theses' });
		ongoingThesesCount = ongoingThesesPage.total;
		dashboardLoaded = true;
	}

	// En-tête de la fiche : la structure et son nombre de thèses.
	async function loadProfile(): Promise<boolean> {
		try {
			const profileData = await api<LabProfile>(`/api/structures/${labId}`);
			lab = profileData.structure;
			thesesCount = profileData.theses_count;
			membersCount = profileData.members_count;
			hasPartners = profileData.has_partners;
			hasAddresses = profileData.has_addresses;
			return true;
		} catch {
			error = true;
			return false;
		}
	}

	// Chargement de l'onglet affiché, à sa première ouverture, d'où que vienne le changement d'onglet : barre d'onglets, lien, retour arrière. Les onglets-listes chargent leurs données au montage.
	$effect(() => {
		if (!lab) return;
		if (activeTab === 'dashboard' && !dashboardLoaded) untrack(loadDashboard);
	});

	onMount(() => {
		void loadProfile();
	});
</script>

<EntityBreadcrumb
	section={{ label: sectionLabels.structures, path: 'structures' }}
	name={lab?.acronym || lab?.name}
	title={lab ? structureLabel(lab) : null}
	fallback="Structure"
/>

{#if error || !lab}
	<EntityStatus {error} notFound="Structure introuvable" />
{:else}
	<!-- Header -->
	<div class="entity-header">
		<TitleRow onopen={isAdmin() ? () => drawer.open(lab!.id) : undefined}>
			<h1 class="entity-title">
				{lab.name}
				{#if lab.acronym}
					<span class="entity-acronym">{lab.acronym}</span>
				{/if}
			</h1>
			{#snippet identifierLinks()}
				{#if lab!.ror_id}<IdentifierLink id_type="ror" id_value={lab!.ror_id} />{/if}
			{/snippet}
		</TitleRow>
	</div>

	<!-- Tabs -->
	<TabNav
		{tabs}
		keep={['structure']}
	/>

	<!-- Tab: Dashboard -->
	{#if activeTab === 'dashboard'}
		<div class="tab-content">
			{#if lab}
				<PublicationsDashboard
					context={{ kind: 'lab', id: lab.id }}
					apiKey="lab-dashboard"
					thesesFigure={false}
					citationScatter
					figures={dashboardLoaded
						? [
								...(ongoingThesesCount > 0
									? [
											{
												value: formatNumber(ongoingThesesCount),
												label: plural(ongoingThesesCount, 'thèse en cours', 'thèses en cours'),
												icon: GraduationCap,
												link: { tab: 'theses', params: { doc_type: 'ongoing_thesis' } },
												hoverColor: 'var(--key-figure-theses)',
											},
										]
									: []),
								...(membersCount > 0
									? [{ value: formatNumber(membersCount), label: plural(membersCount, 'personne'), icon: User, link: { tab: 'persons' }, hoverColor: 'var(--key-figure-persons)' }]
									: []),
							]
						: []}
				>
					{#snippet subjects()}
						<SubjectsCard endpoint="/api/structures/{labId}/subjects" />
					{/snippet}
				</PublicationsDashboard>
			{/if}
		</div>
	{/if}

	<!-- Tab: Publications -->
	{#if activeTab === 'publications'}
		<div class="tab-content">
			<PublicationsListView
				apiKey={`lab-${lab.id}-publications`}
				context={{ kind: 'lab', id: lab.id }}
				basePath={`/structures/${labId}`}
				perPage={50}
			/>
		</div>
	{/if}

	<!-- Tab: Thèses -->
	{#if activeTab === 'theses'}
		<div class="tab-content">
			<ThesesListView labId={lab.id} basePath={`/structures/${labId}`} apiKey={`lab-${lab.id}-theses`} />
		</div>
	{/if}

	<!-- Tab: Personnes -->
	{#if activeTab === 'persons'}
		<div class="tab-content">
			<PersonsListView
				labId={lab.id}
				labHasMembers={membersCount > 0}
				basePath={`/structures/${labId}`}
				apiKey={`lab-${lab.id}-persons`}
			/>
		</div>
	{/if}

	<!-- Tab: Collaborations -->
	{#if activeTab === 'collaborations'}
		<div class="tab-content">
			<PartnersTab labId={lab.id} />
		</div>
	{/if}

	<!-- Tab: Adresses -->
	{#if activeTab === 'addresses'}
		<div class="tab-content">
			<ScopedAddresses endpoint={`/api/structures/${labId}`} scope={{ lab_id: String(labId) }} preferredStructureId={lab.id} apiKey="lab" />
		</div>
	{/if}

{/if}

{#if drawer.id !== null}
	<StructureDrawer
		id={drawer.id}
		onclose={() => drawer.open(null)}
		onchange={loadProfile}
		onopenStructure={drawer.open}
		ondeleted={() => goto(resolve('structures'))}
	/>
{/if}


