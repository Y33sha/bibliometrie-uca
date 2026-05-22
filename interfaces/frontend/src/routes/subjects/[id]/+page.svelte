<script lang="ts">
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";
  import { base } from "$app/paths";
  import { api } from "$lib/api";
  import type { components } from "$lib/api/schema";
  import SubjectGraph from "./SubjectGraph.svelte";
  import PublicationsListView from "$lib/components/PublicationsListView.svelte";
  import TabNav from "$lib/components/TabNav.svelte";

  type SubjectDetailResponse = components["schemas"]["SubjectDetailResponse"];

  const subjectId = $derived(Number($page.params.id));

  // Onglet actif synchronisé avec `?tab=...` (graphe par défaut). TabNav
  // gère lui-même la lecture de l'URL et la navigation via goto.
  const activeTab = $derived(
    $page.url.searchParams.get("tab") === "publications" ? "publications" : "graph",
  );

  const NEIGHBORS_LIMIT = 20;
  const MIN_COOCCURRENCE = 3;

  let data = $state<SubjectDetailResponse | null>(null);
  let loading = $state(false);
  let error = $state(false);
  // Total publications du tableau (post-filtrage des doc_type exclus côté
  // API), remonté par PublicationsListView via callback. Si null, on
  // affiche `usage_count` par défaut (avant ouverture de l'onglet).
  let pubsTotal = $state<number | null>(null);
  // Compteur incrémenté à chaque appel : on ignore les réponses obsolètes
  // si l'utilisateur a re-cliqué entre-temps.
  let requestId = 0;

  async function loadFor(id: number, limit: number, min: number) {
    const myId = ++requestId;
    loading = true;
    error = false;
    try {
      const qs = new URLSearchParams();
      qs.set("neighbors_limit", String(limit));
      qs.set("min_cooccurrence", String(min));
      const result = await api<SubjectDetailResponse>(`/api/subjects/${id}?${qs}`);
      if (myId === requestId) data = result;
    } catch {
      if (myId === requestId) {
        error = true;
        data = null;
      }
    } finally {
      if (myId === requestId) loading = false;
    }
  }

  // Recharge à chaque changement d'id.
  $effect(() => {
    const id = subjectId;
    pubsTotal = null; // reset pour ne pas afficher l'ancien compte
    loadFor(id, NEIGHBORS_LIMIT, MIN_COOCCURRENCE);
  });

  function onNeighborSelect(id: number) {
    goto(`${base}/subjects/${id}`);
  }

  // Libellés courts d'ontologies pour les badges sous le titre.
  const ONTOLOGY_LABELS: Record<string, string> = {
    openalex_topic: "OpenAlex",
    openalex_keyword: "OpenAlex",
    hal_domain: "HAL",
    wos_subject: "WoS",
    wos_heading: "WoS",
    rameau: "RAMEAU",
    theses_discipline: "Thèse",
    scanr_domain: "ScanR",
  };
</script>

<svelte:head>
  <title>{data?.subject.label ?? "Sujet"} — Bibliométrie UCA</title>
</svelte:head>

<a href="{base}/subjects" class="back">← Retour à la liste</a>

  {#if error}
    <div class="error">Sujet introuvable.</div>
  {:else if !data}
    <p class="loading">Chargement…</p>
  {:else}
    <div class="header">
      <h1>{data.subject.label}</h1>
      <div class="badges">
        {#if Object.keys(data.subject.ontologies).length === 0}
          <span class="badge free">Mot-clé libre</span>
        {:else}
          {#each Object.entries(data.subject.ontologies) as [ont, entry] (ont)}
            {@const label = ONTOLOGY_LABELS[ont] ?? ont}
            {@const codes = entry.codes ?? []}
            <span
              class="badge concept"
              title={codes.length ? `Codes : ${codes.join(", ")}` : ont}
            >
              {label}
            </span>
          {/each}
        {/if}
      </div>
    </div>
    <TabNav
      tabs={[
        { id: "graph", label: "Graphe des co-occurrences" },
        {
          id: "publications",
          label: "Publications",
          count: pubsTotal ?? data.subject.usage_count,
        },
      ]}
    />

    {#if activeTab === "graph"}
      <div class="graph-wrapper" class:loading-overlay={loading}>
        {#if data.neighbors.length === 0}
          <p class="empty">
            Aucun voisin avec ces critères.
          </p>
        {:else}
          {#key data.subject.id}
            <SubjectGraph
              subject={data.subject}
              neighbors={data.neighbors}
              onSelect={onNeighborSelect}
            />
          {/key}
        {/if}
      </div>
    {:else}
      {#key data.subject.id}
        <PublicationsListView
          apiKey={`subject-${data.subject.id}-pubs`}
          externalFilters={{
            subjectId: data.subject.id,
            subjectLabel: data.subject.label,
          }}
          urlSync={false}
          showFilterBanner={false}
          onTotalChange={(t) => (pubsTotal = t)}
        />
      {/key}
    {/if}
  {/if}

<style>
  .back {
    color: var(--muted, #6b7280);
    text-decoration: none;
    font-size: 0.9rem;
    margin-bottom: 8px;
  }
  .back:hover {
    text-decoration: underline;
  }
  .header {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 12px;
  }
  h1 {
    margin: 0;
    font-size: 1.4rem;
  }
  .badges {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.8rem;
  }
  .badge.concept {
    background: #e0f2fe;
    color: #075985;
    border: 1px solid #bae6fd;
  }
  .badge.free {
    background: #fef3c7;
    color: #92400e;
    border: 1px solid #fde68a;
  }
  .graph-wrapper {
    width: 100%;
  }
  .graph-wrapper.loading-overlay {
    opacity: 0.6;
  }
  .empty {
    color: var(--muted, #6b7280);
    font-style: italic;
  }
  .loading {
    color: var(--muted, #6b7280);
  }
  .error {
    color: var(--danger, #dc2626);
    font-style: italic;
  }
</style>
