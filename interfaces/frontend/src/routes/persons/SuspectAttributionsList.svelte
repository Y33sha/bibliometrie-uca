<script lang="ts">
  import { tooltip } from "#lib/actions/tooltip.svelte.js";
  import IconButton from "#lib/components/IconButton.svelte";
  import RhCheck from "#lib/components/RhCheck.svelte";
  import PublicationTitle from "#lib/components/PublicationTitle.svelte";
  import { untrack } from "svelte";
  import { resolve } from "$app/paths";
  import { errorMessage, orphanContributions, persons as personsApi } from "#lib/api/index.js";
  import { titleCase } from "#lib/utils.js";
  import { formatCount } from "#lib/plural.js";
  import { resolutionModeLabels } from "#lib/labels.js";
  import { usePaginatedFetch } from "#lib/composables/usePaginatedFetch.svelte.js";
  import ListStatus from "#lib/components/ListStatus.svelte";
  import Pagination from "#lib/components/Pagination.svelte";
  import type { components } from "#lib/api/schema.js";

  type Group = components["schemas"]["SuspectGroupOut"];
  type Publication = components["schemas"]["SuspectPublicationOut"];

  let {
    onopenPerson,
    onchange,
    reloadKey,
  }: {
    /** Ouvre le drawer d'une personne. */
    onopenPerson: (personId: number) => void;
    /** Notifie le parent après une mutation (rafraîchir le badge de l'onglet). */
    onchange: () => void;
    /** Incrémenté par le parent après une action dans le drawer → recharge la file. */
    reloadKey: number;
  } = $props();

  const list = usePaginatedFetch<Group>({
    endpoint: "/api/persons/suspect-attributions",
    itemsKey: "groups",
    apiKey: "suspect-attributions",
    buildParams: () => new URLSearchParams(),
    pageParam: null,
  });
  let acting = $state(false);
  let error = $state("");

  async function act(action: () => Promise<unknown>, failure: string) {
    acting = true;
    error = "";
    try {
      await action();
      await list.load();
      onchange();
    } catch (e) {
      error = `${failure} : ${errorMessage(e)}`;
    }
    acting = false;
  }

  function reject(group: Group, publications: Publication[]) {
    return act(
      () =>
        personsApi.detachContributions(
          group.person.person_id,
          publications.map((p) => p.publication_id),
        ),
      "Rejet impossible",
    );
  }

  function confirm(group: Group, publications: Publication[]) {
    return act(
      () =>
        orphanContributions.batchAssign({
          person_id: group.person.person_id,
          contribution_ids: publications.map((p) => p.contribution_id),
        }),
      "Confirmation impossible",
    );
  }

  function reasonLabel(group: Group): string {
    return group.reason === "cluster"
      ? "Cluster isolé"
      : "Proches des publications rejetées";
  }

  // Charge au montage et à chaque incrément de `reloadKey` (action dans le drawer).
  $effect(() => {
    void reloadKey;
    untrack(list.load);
  });
</script>

<p class="triage-intro">
  Publications rattachées à une personne et probablement signées par un <strong>homonyme</strong> :
  <em>cluster isolé</em> de ses publications, sans lien avec les autres, ou publications
  <em>proches des publications rejetées</em> pour elle. Rejeter détache la publication de la personne ;
  confirmer l'épingle sur elle, et le groupe n'est plus signalé.
</p>

{#if error}<p class="info-box info-box-danger">{error}</p>{/if}

<ListStatus {list} emptyText="Aucune attribution suspecte à trancher.">
  <div class="triage-list">
    {#each list.items as group (`${group.person.person_id}-${group.reason}-${group.cluster}`)}
      <div class="triage-item">
        <div class="group-head">
          <button class="triage-person" onclick={() => onopenPerson(group.person.person_id)}>
            <span class="triage-person-last">{titleCase(group.person.last_name)}</span>
            {titleCase(group.person.first_name)}
          </button>
          {#if group.person.has_rh}<RhCheck />{/if}
          <span class="muted-small">Fiche RH :</span>
          {#each group.hr_units as unit (unit)}<span class="tag tag-pill tag-accent">{unit}</span>{:else}<span class="muted-small">aucune unité</span>{/each}
          <span class="tag">{reasonLabel(group)}</span>
          <span class="muted-small">{formatCount(group.publications.length, "publication")}</span>
          <span class="group-actions">
            <button
              class="btn btn-sm"
              disabled={acting}
              use:tooltip={"Détacher toutes les publications du groupe"}
              onclick={() => reject(group, group.publications)}>Rejeter le groupe</button
            >
            <button
              class="btn btn-sm"
              disabled={acting}
              use:tooltip={"Épingler toutes les publications du groupe sur la personne"}
              onclick={() => confirm(group, group.publications)}>Confirmer le groupe</button
            >
          </span>
        </div>
        <ul class="publications">
          {#each group.publications as publication (publication.contribution_id)}
            <li>
              <IconButton
                icon="reject"
                small
                label="Rejeter : détacher la publication"
                disabled={acting}
                onclick={() => reject(group, [publication])}
              />
              <IconButton
                icon="confirm"
                small
                label="Confirmer : épingler la publication"
                disabled={acting}
                onclick={() => confirm(group, [publication])}
              />
              <span class="year">{publication.publication_year ?? "—"}</span>
              <a
                class="title"
                href={resolve(`publications/${publication.publication_id}`)}
                target="_blank"
                rel="noopener"><PublicationTitle titre={publication.title} /></a
              >
              {#if publication.container_title}<span class="muted-small">{publication.container_title}</span>{/if}
              <span class="tag">{resolutionModeLabels[publication.resolution_mode] ?? publication.resolution_mode}</span>
              {#each publication.address_structures as structure (structure)}
                <span class="tag tag-pill" use:tooltip={"Structure rattachée à une adresse de la publication"}>{structure}</span>
              {/each}
            </li>
          {/each}
        </ul>
      </div>
    {/each}
  </div>

  <Pagination page={list.page} pages={list.pages} onchange={list.goToPage} />
</ListStatus>

<style>
  .group-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
  }
  .group-actions {
    display: inline-flex;
    gap: 4px;
    margin-left: auto;
  }
  .publications {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .publications li {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 6px;
    font-size: var(--fs-sm);
  }
  .year {
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }
  .title {
    color: inherit;
  }
</style>
