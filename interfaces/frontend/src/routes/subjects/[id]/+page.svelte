<script lang="ts">
  import TableScroll from '#lib/components/TableScroll.svelte';
  import EntityBreadcrumb from "#lib/components/EntityBreadcrumb.svelte";
  import EntityStatus from "#lib/components/EntityStatus.svelte";
  import { page } from "$app/state";
  import { resolve } from "$app/paths";
  import { latestRequest } from "#lib/api/index.js";
  import type { components } from "#lib/api/schema.js";
  import SubjectGraph from "./SubjectGraph.svelte";
  import { specificity, specificityPercent } from "./specificity";
  import PublicationsListView from "#lib/components/PublicationsListView.svelte";
  import TabNav from "#lib/components/TabNav.svelte";
  import { activeTabId, type TabDef } from "#lib/tabs.js";
  import SortChevron from "#lib/components/SortChevron.svelte";
  import ClampedBlock from "#lib/components/ClampedBlock.svelte";
  import { subjectVocabularyLabels } from "#lib/labels.js";

  type SubjectDetailResponse = components["schemas"]["SubjectDetailResponse"];

  // Libellé normalisé du sujet : il l'identifie, tous vocabulaires confondus.
  const subjectKey = $derived(page.params.id ?? "");

  const tabs: TabDef[] = [
    { id: "graph", label: "Sujets associés" },
    { id: "publications", label: "Publications" },
  ];
  const activeTab = $derived(activeTabId(tabs, page.url.searchParams));

  const NEIGHBORS_LIMIT = 15;
  const MIN_COOCCURRENCE = 3;

  let data = $state<SubjectDetailResponse | null>(null);
  let loading = $state(false);
  let error = $state(false);
  // Chaque changement de sujet relance la fiche : la requête précédente, encore en vol, est annulée.
  const request = latestRequest();

  async function loadFor(key: string, limit: number, min: number) {
    loading = true;
    error = false;
    try {
      const qs = new URLSearchParams();
      qs.set("neighbors_limit", String(limit));
      qs.set("min_cooccurrence", String(min));
      data = await request<SubjectDetailResponse>(`/api/subjects/${encodeURIComponent(key)}?${qs}`);
    } catch {
      error = true;
      data = null;
    } finally {
      loading = false;
    }
  }

  // Charge le sujet de la page et ses voisins.
  $effect(() => {
    loadFor(subjectKey, NEIGHBORS_LIMIT, MIN_COOCCURRENCE);
  });

  // Tableau des sujets associés, trié par spécificité par défaut.
  type NeighborSort = "common" | "specificity" | "total";
  let neighborSort = $state<NeighborSort>("specificity");
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

<EntityBreadcrumb section={{ label: "Sujets", path: "subjects" }} name={data?.subject.label} fallback="Sujet" />

  {#if error || !data}
    <EntityStatus {error} notFound="Sujet introuvable" />
  {:else}
    <div class="entity-header">
      <h1 class="entity-title">{data.subject.label}</h1>
      <div class="entity-meta">
        {data.subject.usage_count.toLocaleString("fr-FR")} publications
      </div>
    </div>

    <!-- Place du sujet dans chaque vocabulaire : ancêtres, nombre de publications quand le sujet figure dans plusieurs vocabulaires, sous-sujets. -->
    <div class="vocabularies">
      {#each data.vocabulary_subjects as v (`${v.vocabulary}:${v.code}`)}
        <div class="vocabulary">
          <div class="vocabulary-line">
            <span class="entity-meta-label">{subjectVocabularyLabels[v.vocabulary]}</span>
            <span class="lineage">
              {#each v.ancestors as a (a.label_normalized)}
                <a class="entity-link" href={resolve(`subjects/${a.label_normalized}`)}>{a.label}</a>
                <span class="muted">›</span>
              {/each}
              <span class="current">{data.subject.label}</span>
            </span>
            {#if data.vocabulary_subjects.length > 1}
              <span class="muted-num">{v.usage_count.toLocaleString("fr-FR")} publications</span>
            {/if}
          </div>
          {#if v.children.length > 0}
            <div class="detail-sublabel">Sous-sujets</div>
            <!-- Deux lignes et demie de pastilles. -->
            {#key `${data.subject.label_normalized}:${v.vocabulary}:${v.code}`}
              <ClampedBlock maxHeight="4.5rem" moreLabel={`Voir les ${v.children.length} sous-sujets`}>
                <div class="detail-tags">
                  {#each v.children as c (c.label_normalized)}
                    <a href={resolve(`subjects/${c.label_normalized}`)} class="tag">{c.label} <span class="muted-num">{c.usage_count.toLocaleString("fr-FR")}</span></a>
                  {/each}
                </div>
              </ClampedBlock>
            {/key}
          {/if}
        </div>
      {/each}
    </div>

    <TabNav {tabs} />

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
          {#key data.subject.label_normalized}
            <SubjectGraph
              subject={data.subject}
              neighbors={data.neighbors}
              links={data.neighbor_links}
            />
          {/key}

          <h2 class="section-title">Sujets associés</h2>
          <TableScroll>
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
                {#each sortedNeighbors as n (n.label_normalized)}
                  <tr>
                    <td><a class="entity-link" href={resolve(`subjects/${n.label_normalized}`)}>{n.label}</a></td>
                    <td class="num">{n.cooccurrence_count.toLocaleString("fr-FR")}</td>
                    <td class="num">
                      <span class="spec-cell">
                        <span class="spec-bar" style="width: {(specificity(n) / maxSpecificity) * 60}px"></span>
                        <span><span class="spec-value">{specificityPercent(n)}</span>&nbsp;%</span>
                      </span>
                    </td>
                    <td class="num muted-num">{n.usage_count.toLocaleString("fr-FR")}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </TableScroll>
        {/if}
      </div>
    {:else}
      {#key data.subject.label_normalized}
        <PublicationsListView
          apiKey={`subject-${data.subject.label_normalized}-publications`}
          context={{ kind: 'subject', id: data.subject.label_normalized }}
          urlSync={false}
        />
      {/key}
    {/if}
  {/if}

<style>
  .vocabularies {
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin-bottom: 16px;
  }
  .vocabulary {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .vocabulary-line {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 6px 12px;
  }
  .lineage {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 4px 6px;
  }
  .current {
    font-weight: 600;
  }
  .graph-wrapper {
    width: 100%;
  }
  .graph-wrapper.loading-overlay {
    opacity: 0.6;
  }
  .graph-legend {
    margin: 0 0 8px;
    font-size: var(--fs-sm);
    color: var(--text-secondary);
  }
  .spec-cell {
    display: inline-flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
  }
  /* Largeur de trois chiffres : les barres s'alignent quel que soit le nombre de chiffres. */
  .spec-value {
    display: inline-block;
    min-width: 3ch;
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
</style>
