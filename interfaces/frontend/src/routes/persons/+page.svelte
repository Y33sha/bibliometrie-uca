<script lang="ts">
	import PageHeader from '#lib/components/PageHeader.svelte';
	import { institution } from '#lib/institution.svelte.js';
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import { api, ApiError, persons as personsApi } from '#lib/api/index.js';
	import { toast } from '#lib/dialogs.svelte.js';
	import { isAdmin } from '#lib/session.svelte.js';
	import { useDebouncedSearch } from '#lib/composables/useDebouncedSearch.svelte.js';
	import { setQueryParam } from '#lib/url.js';
	import HubTabs from '#lib/components/HubTabs.svelte';
	import PersonsListView from '#lib/components/PersonsListView.svelte';
	import type {
		DetachModalState,
		DetachPublication,
		IdFormState,
		OtherPerson,
		Person,
		PersonExclusion,
		PersonSearchResult,
	} from './types';
	import type { components } from '#lib/api/schema.js';
	import DetachNameFormModal from './DetachNameFormModal.svelte';
	import PersonDrawer from './PersonDrawer.svelte';
	import AmbiguousFormsList from './AmbiguousFormsList.svelte';
	import IdentifierConflictsList from './IdentifierConflictsList.svelte';
	import NameDuplicatesList from './NameDuplicatesList.svelte';
	import { confirmMerge } from './confirmMerge';

	type NameFormContributionRef = components['schemas']['NameFormContributionRef'];

	/* ── Onglets de la session admin : la liste, puis les files de triage ── */

	type TabKey = 'all' | 'ambiguous-forms' | 'identifier-conflicts' | 'name-duplicates';
	const QUEUES: TabKey[] = ['ambiguous-forms', 'identifier-conflicts', 'name-duplicates'];
	let tab = $state<TabKey>('all');
	let ambiguousCount = $state(0);
	let identifierConflictCount = $state(0);
	let nameDuplicateCount = $state(0);
	let orphanCount = $state(0);
	// Incrémenté après chaque action du volet : recharge la file de triage affichée.
	let reloadFiles = $state(0);
	// Incrémenté après chaque action du volet : la clé d'API de la liste change, la liste et ses facettes se rechargent.
	let listVersion = $state(0);

	// Volet d'une personne : ouvert tant que `?person=<id>` figure dans l'URL.
	let selectedPersonId: number | null = $state(null);
	let selectedPerson: Person | null = $state(null);

	let idForms: Record<number, IdFormState> = $state({});
	let detachModal: DetachModalState | null = $state(null);

	let activeMergePersonId: number | null = $state(null);
	const mergeSearch = useDebouncedSearch<PersonSearchResult>({
		search: (q, request) =>
			request<PersonSearchResult[]>(`/api/persons/search?search=${encodeURIComponent(q)}`),
		// Une personne RH est toujours conservée : elle ne figure pas parmi les personnes à absorber.
		transform: (results) => results.filter((r) => r.id !== activeMergePersonId && !r.has_rh),
	});

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
		tab = t;
		// Compteur « Doublons par nom » paresseux : sa détection (4 self-joins sur les personnes) coûte ~3 s, on ne la paie qu'à l'ouverture de l'onglet.
		if (t === 'name-duplicates') loadNameDuplicateCount();
		void setQueryParam('tab', t === 'all' ? null : t);
	}

	/* ── Volet ── */

	async function openDrawer(personId: number) {
		selectedPersonId = personId;
		void setQueryParam('person', String(personId));
		selectedPerson = await api<Person>(`/api/persons/${personId}/curation`);
	}

	function closeDrawer() {
		selectedPersonId = null;
		selectedPerson = null;
		closeMergeSearch();
		void setQueryParam('person', null);
	}

	// Après une mutation : relit la personne du volet, la liste et la file de triage affichée.
	async function refreshAfterChange() {
		listVersion++;
		reloadFiles++;
		if (selectedPersonId !== null) {
			selectedPerson = await api<Person>(`/api/persons/${selectedPersonId}/curation`);
		}
	}

	/* ── Identifiants ── */

	function toggleIdForm(personId: number) {
		if (personId in idForms) {
			const next = { ...idForms };
			delete next[personId];
			idForms = next;
		} else {
			idForms = { ...idForms, [personId]: { id_type: 'orcid', id_value: '', error: '' } };
		}
	}

	async function addIdentifier(personId: number) {
		const form = idForms[personId];
		if (!form || !form.id_value.trim()) return;
		try {
			await personsApi.addIdentifier(personId, {
				id_type: form.id_type,
				id_value: form.id_value.trim(),
			});
		} catch (e) {
			const detail = e instanceof ApiError ? (e.detail as { detail?: string })?.detail : null;
			idForms = { ...idForms, [personId]: { ...form, error: detail || 'Erreur inconnue' } };
			return;
		}
		const next = { ...idForms };
		delete next[personId];
		idForms = next;
		await refreshAfterChange();
	}

	async function setIdentifierStatus(identId: number, status: string) {
		const { propagated } = await personsApi.setIdentifierStatus(identId, status);
		if (propagated > 0) {
			toast(
				`${propagated} identifiant${propagated > 1 ? 's' : ''} du même compte HAL ${propagated > 1 ? 'ont' : 'a'} reçu le même statut`,
			);
		}
		await refreshAfterChange();
	}

	/* ── Nom et exclusion ── */

	async function renamePerson(personId: number, lastName: string, firstName: string): Promise<boolean> {
		try {
			await personsApi.rename(personId, lastName, firstName);
		} catch (e) {
			const status = e instanceof ApiError ? e.status : '?';
			const detail = e instanceof ApiError ? (e.detail as { detail?: string })?.detail : null;
			toast(detail || `Erreur ${status}`, 'error');
			return false;
		}
		await refreshAfterChange();
		return true;
	}

	async function setPersonExclusion(personId: number, exclusion: PersonExclusion | null) {
		await personsApi.setExclusion(personId, exclusion);
		await refreshAfterChange();
	}

	/* ── Formes de nom et détachement ── */

	async function openDetachModal(personId: number, nameForm: string) {
		detachModal = { personId, nameForm, publications: [], otherPersons: [], loading: true };
		const data = await api<{ contributions: NameFormContributionRef[]; other_persons: OtherPerson[] }>(
			`/api/persons/${personId}/name-form-contributions?name_form=${encodeURIComponent(nameForm)}`,
		);
		// Le rejet porte sur la publication entière : on regroupe les sources par publication pour n'afficher qu'une ligne par publication.
		const byPub = new Map<number, DetachPublication>();
		for (const r of data.contributions) {
			let pub = byPub.get(r.publication_id);
			if (!pub) {
				pub = { publication_id: r.publication_id, title: r.title, publication_year: r.publication_year, sources: [], checked: true };
				byPub.set(r.publication_id, pub);
			}
			pub.sources.push({ source: r.source, source_contribution_id: r.source_contribution_id });
		}
		detachModal = {
			personId,
			nameForm,
			loading: false,
			publications: [...byPub.values()],
			otherPersons: data.other_persons,
		};
	}

	async function confirmDetach() {
		if (!detachModal) return;
		const toDetach = detachModal.publications.filter((p) => p.checked);
		if (toDetach.length === 0) {
			detachModal = null;
			return;
		}
		// Une référence de source par publication suffit : le backend détache toutes les sources de la publication.
		await personsApi.detachContributions(detachModal.personId, {
			contributions: toDetach.map((p) => p.sources[0]),
		});
		detachModal = null;
		await refreshAfterChange();
	}

	async function setNameFormStatus(personId: number, nameForm: string, status: string) {
		await personsApi.updateNameFormStatus(personId, nameForm, status as 'pending' | 'confirmed' | 'rejected');
		await refreshAfterChange();
	}

	/* ── Fusion ── */

	function openMergeSearch(personId: number) {
		activeMergePersonId = personId;
		mergeSearch.clear();
	}

	function closeMergeSearch() {
		activeMergePersonId = null;
		mergeSearch.clear();
	}

	async function mergeInto(targetId: number, sourceId: number) {
		if (!(await confirmMerge(sourceId))) return;
		await personsApi.merge(targetId, sourceId);
		closeMergeSearch();
		await refreshAfterChange();
		loadAmbiguousCount();
		loadIdentifierConflictCount();
	}

	// Absorbe une autre personne (otherId) dans celle du volet (la cible).
	async function absorbPerson(otherId: number) {
		if (selectedPersonId === null) return;
		if (!(await confirmMerge(otherId))) return;
		try {
			await personsApi.merge(selectedPersonId, otherId);
		} catch (e) {
			const detail = e instanceof ApiError ? (e.detail as { detail?: string })?.detail : null;
			toast(detail || 'Fusion impossible', 'error');
			return;
		}
		await refreshAfterChange();
		loadAmbiguousCount();
		loadIdentifierConflictCount();
	}

	async function mergeFromModal(sourceId: number) {
		if (!detachModal) return;
		if (!(await confirmMerge(sourceId))) return;
		await personsApi.merge(detachModal.personId, sourceId);
		detachModal = null;
		await refreshAfterChange();
	}

	onMount(() => {
		if (!isAdmin()) return;
		const params = new URLSearchParams(window.location.search);
		const t = params.get('tab');
		if (QUEUES.includes(t as TabKey)) tab = t as TabKey;
		loadOrphanCount();
		loadAmbiguousCount();
		loadIdentifierConflictCount();
		// Compteur « Doublons par nom » : seulement si l'onglet est l'onglet courant ; sinon il se charge à l'ouverture de l'onglet (cf. `selectTab`).
		if (tab === 'name-duplicates') loadNameDuplicateCount();
		const personId = parseInt(params.get('person') ?? '', 10);
		if (personId) openDrawer(personId);
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
		active={tab}
		onselect={(key) => selectTab(key as TabKey)}
	/>
{/if}

{#if tab === 'ambiguous-forms'}
	<AmbiguousFormsList onopenPerson={openDrawer} onchange={loadAmbiguousCount} reloadKey={reloadFiles} />
{:else if tab === 'identifier-conflicts'}
	<IdentifierConflictsList onopenPerson={openDrawer} onchange={loadIdentifierConflictCount} reloadKey={reloadFiles} />
{:else if tab === 'name-duplicates'}
	<NameDuplicatesList onopenPerson={openDrawer} onchange={loadNameDuplicateCount} reloadKey={reloadFiles} />
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
		onopen={isAdmin() ? openDrawer : undefined}
		activeId={selectedPersonId}
	/>
{/if}

{#if selectedPerson}
	<PersonDrawer
		person={selectedPerson}
		idForm={idForms[selectedPerson.id] ?? null}
		mergeActive={activeMergePersonId === selectedPerson.id}
		{mergeSearch}
		onclose={closeDrawer}
		onrename={renamePerson}
		onsetExclusion={setPersonExclusion}
		onaddIdentifier={addIdentifier}
		ontoggleIdForm={toggleIdForm}
		onsetIdentifierStatus={setIdentifierStatus}
		onopenDetach={openDetachModal}
		onsetFormStatus={setNameFormStatus}
		onmergeOpen={openMergeSearch}
		onmergeClose={closeMergeSearch}
		onmerge={mergeInto}
		onabsorb={absorbPerson}
		onopenPerson={openDrawer}
	/>
{/if}

{#if detachModal}
	<DetachNameFormModal
		bind:state={detachModal}
		onclose={() => {
			detachModal = null;
		}}
		onconfirmDetach={confirmDetach}
		onmerge={mergeFromModal}
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
		font-size: 0.9rem;
		font-weight: 500;
		cursor: pointer;
		text-align: left;
		transition: background 0.15s;
	}
	.orphan-link:hover {
		background: color-mix(in srgb, var(--attention) 25%, white);
	}
</style>
