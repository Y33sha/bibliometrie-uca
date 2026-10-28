<script lang="ts">
	import PageHeader from '#lib/components/PageHeader.svelte';
	import { institution } from '#lib/institution.svelte.js';
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { api } from '#lib/api/index.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import HubTabs from '#lib/components/HubTabs.svelte';
	import PersonsListView from '#lib/components/PersonsListView.svelte';
	import PersonCurationDrawer from '#lib/components/persons/PersonCurationDrawer.svelte';
	import { useDrawerParam } from '#lib/composables/useDrawerParam.svelte.js';
	import { useTabParam } from '#lib/composables/useTabParam.svelte.js';
	import AmbiguousFormsList from './AmbiguousFormsList.svelte';
	import IdentifierConflictsList from './IdentifierConflictsList.svelte';
	import NameDuplicatesList from './NameDuplicatesList.svelte';

	/* ── Onglets de la session admin : la liste, puis les files de triage ── */

	type TabKey = 'all' | 'ambiguous-forms' | 'identifier-conflicts' | 'name-duplicates';
	const QUEUES: TabKey[] = ['ambiguous-forms', 'identifier-conflicts', 'name-duplicates'];
	const tab = useTabParam(QUEUES, isAdmin);
	let ambiguousCount = $state(0);
	let identifierConflictCount = $state(0);
	let nameDuplicateCount = $state(0);
	let orphanCount = $state(0);
	// Incrémenté après chaque action du volet : recharge la file de triage affichée.
	let reloadFiles = $state(0);
	// Incrémenté après chaque action du volet : la clé d'API de la liste change, la liste et ses facettes se rechargent.
	let listVersion = $state(0);

	// Volet d'une personne, partagé par la liste et les files de triage.
	const drawer = useDrawerParam('person', isAdmin);

	/* ── Compteurs ── */

	async function queueCount(path: string): Promise<number> {
		return (await api<{ total: number }>(path)).total;
	}

	async function loadAmbiguousCount() {
		ambiguousCount = await queueCount('/api/persons/ambiguous-name-forms/count');
	}

	async function loadIdentifierConflictCount() {
		identifierConflictCount = await queueCount('/api/persons/identifier-conflicts/count');
	}

	async function loadNameDuplicateCount() {
		nameDuplicateCount = await queueCount('/api/persons/name-duplicates/count');
	}

	async function loadOrphanCount() {
		orphanCount = await queueCount('/api/contributions/orphans/count');
	}

	function selectTab(t: TabKey) {
		tab.select(t);
		// Compteur « Doublons par nom » paresseux : sa détection (4 self-joins sur les personnes) coûte ~3 s, on ne la paie qu'à l'ouverture de l'onglet.
		if (t === 'name-duplicates') loadNameDuplicateCount();
	}

	/* ── Volet ── */

	// Après une écriture du volet : recharge la liste, la file de triage affichée et les compteurs des files.
	function onDrawerChange() {
		listVersion++;
		reloadFiles++;
		loadAmbiguousCount();
		loadIdentifierConflictCount();
	}

	onMount(() => {
		if (!isAdmin()) return;
		loadOrphanCount();
		loadAmbiguousCount();
		loadIdentifierConflictCount();
		// Compteur « Doublons par nom » : seulement si l'onglet est l'onglet courant ; sinon il se charge à l'ouverture de l'onglet (cf. `selectTab`).
		if (tab.current === 'name-duplicates') loadNameDuplicateCount();
	});
</script>

<PageHeader title="Chercheurs" hidden />

{#if isAdmin()}
	<HubTabs
		tabs={[
			{ key: 'all', label: 'Toutes les personnes' },
			{ key: 'ambiguous-forms', label: 'Formes ambiguës', count: ambiguousCount },
			{ key: 'identifier-conflicts', label: "Conflits d'identifiant", count: identifierConflictCount },
			{ key: 'name-duplicates', label: 'Doublons par nom', count: nameDuplicateCount },
		]}
		active={tab.current}
		onselect={(key) => selectTab(key as TabKey)}
	/>
{/if}

{#if tab.current === 'ambiguous-forms'}
	<AmbiguousFormsList onopenPerson={drawer.open} onchange={loadAmbiguousCount} reloadKey={reloadFiles} />
{:else if tab.current === 'identifier-conflicts'}
	<IdentifierConflictsList onopenPerson={drawer.open} onchange={loadIdentifierConflictCount} reloadKey={reloadFiles} />
{:else if tab.current === 'name-duplicates'}
	<NameDuplicatesList onopenPerson={drawer.open} onchange={loadNameDuplicateCount} reloadKey={reloadFiles} />
{:else}
	{#if isAdmin() && orphanCount > 0}
		<a href={resolve('admin/orphan-contributions')} class="orphan-link">
			{orphanCount} contribution{orphanCount > 1 ? 's' : ''} {institution.name} orpheline{orphanCount > 1 ? 's' : ''}
			(non reliée{orphanCount > 1 ? 's' : ''} à une personne)
		</a>
	{/if}
	<PersonsListView
		apiKey={`persons-dir-${listVersion}`}
		basePath="/persons"
		onopen={isAdmin() ? drawer.open : undefined}
		activeId={drawer.id}
	/>
{/if}

{#if drawer.id !== null}
	<PersonCurationDrawer
		personId={drawer.id}
		onclose={() => drawer.open(null)}
		onchange={onDrawerChange}
		onopenPerson={drawer.open}
	/>
{/if}

<style>
	.orphan-link {
		display: block;
		width: 100%;
		padding: 10px 16px;
		margin-bottom: 12px;
		background: var(--attention-light);
		border: 1px solid color-mix(in srgb, var(--attention) 40%, white);
		border-radius: var(--radius);
		color: var(--attention);
		font-size: var(--fs-md);
		font-weight: 500;
		cursor: pointer;
		text-align: left;
		transition: background 0.15s;
	}
	.orphan-link:hover {
		background: color-mix(in srgb, var(--attention) 25%, white);
	}
</style>
