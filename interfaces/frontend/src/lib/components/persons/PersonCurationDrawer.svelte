<script lang="ts">
	import { untrack } from 'svelte';
	import { api, ApiError, persons as personsApi } from '#lib/api/index.js';
	import { toast } from '#lib/dialogs.svelte.js';
	import { useDebouncedSearch } from '#lib/composables/useDebouncedSearch.svelte.js';
	import type { components } from '#lib/api/schema.js';
	import type {
		DetachModalState,
		DetachPublication,
		IdFormState,
		OtherPerson,
		Person,
		PersonExclusion,
		PersonSearchResult,
	} from './types';
	import DetachNameFormModal from './DetachNameFormModal.svelte';
	import PersonDrawer from './PersonDrawer.svelte';
	import { confirmMerge } from './confirmMerge';

	type NameFormContributionRef = components['schemas']['NameFormContributionRef'];

	// Volet de curation d'une personne, réservé à la session admin : il charge la personne et porte ses écritures (nom, exclusion, identifiants, formes de nom, fusions).
	let {
		personId,
		onclose,
		onchange,
		onopenPerson,
	}: {
		personId: number;
		onclose: () => void;
		/** Appelé après chaque écriture, pour que la page hôte recharge ses listes. */
		onchange?: () => void;
		/** Ouvre le volet d'une autre personne. */
		onopenPerson: (personId: number) => void;
	} = $props();

	let person: Person | null = $state(null);
	let idForms: Record<number, IdFormState> = $state({});
	let detachModal: DetachModalState | null = $state(null);

	let activeMergePersonId: number | null = $state(null);
	const mergeSearch = useDebouncedSearch<PersonSearchResult>({
		search: (q, request) =>
			request<PersonSearchResult[]>(`/api/persons/search?search=${encodeURIComponent(q)}`),
		// Une personne RH est toujours conservée : elle ne figure pas parmi les personnes à absorber.
		transform: (results) => results.filter((r) => r.id !== activeMergePersonId && !r.has_rh),
	});

	async function loadPerson() {
		person = await api<Person>(`/api/persons/${personId}/curation`);
	}

	// Chaque personne ouverte repart d'une recherche de fusion fermée.
	$effect(() => {
		void personId;
		untrack(() => {
			closeMergeSearch();
			void loadPerson();
		});
	});

	// Après une écriture : relit la personne du volet et prévient la page hôte.
	async function refreshAfterChange() {
		onchange?.();
		await loadPerson();
	}

	/* ── Identifiants ── */

	function toggleIdForm(id: number) {
		if (id in idForms) {
			const next = { ...idForms };
			delete next[id];
			idForms = next;
		} else {
			idForms = { ...idForms, [id]: { id_type: 'orcid', id_value: '', error: '' } };
		}
	}

	async function addIdentifier(id: number) {
		const form = idForms[id];
		if (!form || !form.id_value.trim()) return;
		try {
			await personsApi.addIdentifier(id, {
				id_type: form.id_type,
				id_value: form.id_value.trim(),
			});
		} catch (e) {
			const detail = e instanceof ApiError ? (e.detail as { detail?: string })?.detail : null;
			idForms = { ...idForms, [id]: { ...form, error: detail || 'Erreur inconnue' } };
			return;
		}
		const next = { ...idForms };
		delete next[id];
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

	async function renamePerson(id: number, lastName: string, firstName: string): Promise<boolean> {
		try {
			await personsApi.rename(id, lastName, firstName);
		} catch (e) {
			const status = e instanceof ApiError ? e.status : '?';
			const detail = e instanceof ApiError ? (e.detail as { detail?: string })?.detail : null;
			toast(detail || `Erreur ${status}`, 'error');
			return false;
		}
		await refreshAfterChange();
		return true;
	}

	async function setPersonExclusion(id: number, exclusion: PersonExclusion | null) {
		await personsApi.setExclusion(id, exclusion);
		await refreshAfterChange();
	}

	/* ── Formes de nom et détachement ── */

	async function openDetachModal(id: number, nameForm: string) {
		detachModal = { personId: id, nameForm, publications: [], otherPersons: [], loading: true };
		const data = await api<{ contributions: NameFormContributionRef[]; other_persons: OtherPerson[] }>(
			`/api/persons/${id}/name-form-contributions?name_form=${encodeURIComponent(nameForm)}`,
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
			personId: id,
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

	async function setNameFormStatus(id: number, nameForm: string, status: string) {
		await personsApi.updateNameFormStatus(id, nameForm, status as 'pending' | 'confirmed' | 'rejected');
		await refreshAfterChange();
	}

	/* ── Fusion ── */

	function openMergeSearch(id: number) {
		activeMergePersonId = id;
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
	}

	// Absorbe une autre personne (otherId) dans celle du volet (la cible).
	async function absorbPerson(otherId: number) {
		if (!(await confirmMerge(otherId))) return;
		try {
			await personsApi.merge(personId, otherId);
		} catch (e) {
			const detail = e instanceof ApiError ? (e.detail as { detail?: string })?.detail : null;
			toast(detail || 'Fusion impossible', 'error');
			return;
		}
		await refreshAfterChange();
	}

	/* ── Personnes distinctes ── */

	async function unmarkDistinct(otherId: number) {
		await personsApi.unmarkDistinct(personId, otherId);
		await refreshAfterChange();
	}

	async function mergeFromModal(sourceId: number) {
		if (!detachModal) return;
		if (!(await confirmMerge(sourceId))) return;
		await personsApi.merge(detachModal.personId, sourceId);
		detachModal = null;
		await refreshAfterChange();
	}
</script>

{#if person}
	<PersonDrawer
		{person}
		idForm={idForms[person.id] ?? null}
		mergeActive={activeMergePersonId === person.id}
		{mergeSearch}
		{onclose}
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
		onunmarkDistinct={unmarkDistinct}
		{onopenPerson}
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
