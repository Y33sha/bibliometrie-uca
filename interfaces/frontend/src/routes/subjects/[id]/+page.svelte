<script lang="ts">
  import Breadcrumb from "#lib/components/Breadcrumb.svelte";
  import { pageTitle } from "#lib/institution.svelte.js";
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { resolve } from "$app/paths";
  import { latestRequest } from "#lib/api/index.js";
  import type { components } from "#lib/api/schema.js";
  import SubjectGraph from "./SubjectGraph.svelte";
  import PublicationsListView from "#lib/components/PublicationsListView.svelte";
  import TabNav from "#lib/components/TabNav.svelte";
  import SortChevron from "#lib/components/SortChevron.svelte";

  type SubjectDetailResponse = components["schemas"]["SubjectDetailResponse"];

  const subjectId = $derived(Number(page.params.id));

  // Onglet actif synchronisé avec `?tab=...` (graphe par défaut). TabNav gère lui-même la lecture de l'URL et la navigation via goto.
  const activeTab = $derived(
    page.url.searchParams.get("tab") === "publications" ? "publications" : "graph",
  );

  const NEIGHBORS_LIMIT = 15;
  const MIN_COOCCURRENCE = 3;

  let data = $state<SubjectDetailResponse | null>(null);
  let loading = $state(false);
  let error = $state(false);
  // Chaque changement de sujet relance la fiche : la requête précédente, encore en vol, est annulée.
  const request = latestRequest();

  async function loadFor(id: number, limit: number, min: number) {
    loading = true;
    error = false;
    try {
      const qs = new URLSearchParams();
      qs.set("neighbors_limit", String(limit));
      qs.set("min_cooccurrence", String(min));
      data = await request<SubjectDetailResponse>(`/api/subjects/${id}?${qs}`);
    } catch {
      error = true;
      data = null;
    } finally {
      loading = false;
    }
  }

  // Charge le sujet de l'identifiant de la page et ses voisins.
  $effect(() => {
    const id = subjectId;
    loadFor(id, NEIGHBORS_LIMIT, MIN_COOCCURRENCE);
  });

  function onNeighborSelect(id: number) {
    goto(resolve(`subjects/${id}`));
  }

  // Tableau des sujets associés, trié par publications en commun par défaut. Spécificité : part des publications du sujet associé qui portent aussi le sujet de la page.
  type NeighborSort = "common" | "specificity" | "total";
  let neighborSort = $state<NeighborSort>("common");
  const specificity = (n: { cooccurrence_count: number; usage_count: number }) =>
    Math.min(1, n.cooccurrence_count / Math.max(n.usage_count, 1));
  const sortedNeighbors = $derived(
    [...(data?.neighbors ?? [])].sort((a, b) =>
      neighborSort === "common"
        ? b.cooccurrence_count - a.cooccurrence_count
        : neighborSort === "specificity"
          ? specificity(b) - specificity(a)
          : b.usage_count - a.usage_count,
    ),
  );
  const maxSpecificity = $derived(Math.max(...(data?.neighbors ?? []).map(specificity), 0.0001));

</script>

<svelte:head>
  <title>{pageTitle(data?.subject.label ?? "Sujet")}</title>
</svelte:head>

<Breadcrumb trail={[{ label: "Sujets", path: "subjects" }]} current={data?.subject.label} />

  {#if error}
    <div class="error">Sujet introuvable.</div>
  {:else if !data}
    <p class="loading">Chargement…</p>
  {:else}
    <div class="entity-header">
      <h1 class="entity-title">{data.subject.label}</h1>
      <div class="entity-meta">
        {data.subject.usage_count.toLocaleString("fr-FR")} publications
      </div>
    </div>
    <TabNav
      tabs={[
        { id: "graph", label: "Sujets associés" },
        { id: "publications", label: "Publications" },
      ]}
    />

    {#if activeTab === "graph"}
      <div class="graph-wrapper" class:loading-overlay={loading}>
        {#if data.neighbors.length === 0}
          <p class="empty">Aucun sujet associé.</p>
        {:else}
          <h2 class="section-title">Graphe des co-occurrences</h2>
          <p class="graph-legend">
            Taille du cercle : nombre de publications du sujet · Épaisseur du lien : publications en commun ·
            Distance au centre : spécificité de l'association. Un clic sur un sujet ouvre sa page.
          </p>
          {#key data.subject.id}
            <SubjectGraph
              subject={data.subject}
              neighbors={data.neighbors}
              links={data.neighbor_links}
              onSelect={onNeighborSelect}
            />
          {/key}

          <h2 class="section-title">Sujets associés</h2>
          <table class="data-table">
            <thead>
              <tr>
                <th>Sujet</th>
                <th class="num sortable" class:active={neighborSort === "common"} onclick={() => (neighborSort = "common")}>
                  En commun <SortChevron direction={neighborSort === "common" ? "desc" : null} />
                </th>
                <th
                  class="num sortable"
                  class:active={neighborSort === "specificity"}
                  onclick={() => (neighborSort = "specificity")}
                  title="Part des publications du sujet associé qui portent aussi « {data.subject.label} »"
                >
                  Spécificité <SortChevron direction={neighborSort === "specificity" ? "desc" : null} />
                </th>
                <th class="num sortable" class:active={neighborSort === "total"} onclick={() => (neighborSort = "total")}>
                  Total <SortChevron direction={neighborSort === "total" ? "desc" : null} />
                </th>
              </tr>
            </thead>
            <tbody>
              {#each sortedNeighbors as n (n.id)}
                <tr>
                  <td><a class="entity-link" href={resolve(`subjects/${n.id}`)}>{n.label}</a></td>
                  <td class="num">{n.cooccurrence_count.toLocaleString("fr-FR")}</td>
                  <td class="num">
                    <span class="spec-cell">
                      <span class="spec-bar" style="width: {(specificity(n) / maxSpecificity) * 60}px"></span>
                      {(specificity(n) * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %
                    </span>
                  </td>
                  <td class="num muted-num">{n.usage_count.toLocaleString("fr-FR")}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        {/if}
      </div>
    {:else}
      {#key data.subject.id}
        <PublicationsListView
          apiKey={`subject-${data.subject.id}-publications`}
          context={{ kind: 'subject', id: data.subject.id }}
          urlSync={false}
        />
      {/key}
    {/if}
  {/if}

<style>
  .graph-wrapper {
    width: 100%;
  }
  .graph-wrapper.loading-overlay {
    opacity: 0.6;
  }
  .empty {
    color: var(--muted);
    font-style: italic;
  }
  .graph-legend {
    margin: 0 0 8px;
    font-size: 0.85rem;
    color: var(--text-secondary);
  }
  .spec-cell {
    display: inline-flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
  }
  .spec-bar {
    display: inline-block;
    height: 8px;
    border-radius: 2px;
    background: var(--accent-mid);
  }
  .muted-num {
    color: var(--text-secondary);
  }
  .loading {
    color: var(--muted);
  }
  .error {
    color: var(--danger);
    font-style: italic;
  }
</style>
