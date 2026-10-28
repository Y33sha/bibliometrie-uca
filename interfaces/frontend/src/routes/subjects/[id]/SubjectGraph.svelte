<script lang="ts">
  import { resolve } from "$app/paths";
  import type { components } from "#lib/api/schema.js";
  import { CX, CY, subjectGraphLayout, type GraphNode } from "./subjectGraphLayout";

  type SubjectListItem = components["schemas"]["SubjectListItem"];
  type SubjectNeighbor = components["schemas"]["SubjectNeighborOut"];
  type SubjectNeighborLink = components["schemas"]["SubjectNeighborLink"];

  // Graphe radial d'un sujet : le sujet au centre, ses voisins autour. Un voisin est d'autant plus proche du centre que l'association est spécifique ; les sujets apparentés se placent côte à côte.
  let {
    subject,
    neighbors,
    links,
  }: {
    subject: SubjectListItem;
    neighbors: SubjectNeighbor[];
    links: SubjectNeighborLink[];
  } = $props();

  const layout = $derived(subjectGraphLayout(subject, neighbors, links));

  // Brut : comparé par identité aux nœuds du placement, il ne doit pas être enveloppé dans un proxy.
  let hovered = $state.raw<GraphNode | null>(null);

  function percent(spec: number): string {
    return (spec * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " %";
  }
</script>

<div class="graph">
  <svg
    viewBox="{layout.box.x} {layout.box.y} {layout.box.width} {layout.box.height}"
    style="max-width: {layout.box.width}px"
    role="group"
    aria-label="Graphe des sujets associés à {subject.label}"
  >
    {#each layout.nodes as n (n.neighbor.id)}
      <line
        x1={CX}
        y1={CY}
        x2={n.x}
        y2={n.y}
        class="edge"
        class:active={hovered === n}
        stroke-width={layout.strokeWidth(n.neighbor.cooccurrence_count)}
      />
    {/each}

    <circle cx={CX} cy={CY} r={layout.centerR} class="center" />

    {#each layout.nodes as n (n.neighbor.id)}
      {@const right = n.x >= CX}
      <a
        href={resolve(`subjects/${n.neighbor.id}`)}
        class="node"
        class:active={hovered === n}
        onmouseenter={() => (hovered = n)}
        onmouseleave={() => (hovered = null)}
        onfocus={() => (hovered = n)}
        onblur={() => (hovered = null)}
      >
        <circle cx={n.x} cy={n.y} r={n.r} />
        <text
          x={n.x + (right ? n.r + 6 : -n.r - 6)}
          y={n.y}
          class="label"
          text-anchor={right ? "start" : "end"}
          dominant-baseline="middle">{n.neighbor.label}</text
        >
      </a>
    {/each}

    <!-- Titre du sujet central, dessiné en dernier pour rester au-dessus. -->
    <text x={CX} y={CY + layout.centerR + 18} class="label center-label" text-anchor="middle">{subject.label}</text>
  </svg>

  {#if hovered}
    <div
      class="graph-tip"
      style="left: {((hovered.x - layout.box.x) / layout.box.width) * 100}%; top: {((hovered.y + hovered.r - layout.box.y) / layout.box.height) * 100}%"
    >
      <div class="tip-title">{hovered.neighbor.label}</div>
      <div>{hovered.neighbor.cooccurrence_count.toLocaleString("fr-FR")} publications en commun</div>
      <div>
        {percent(hovered.specificity)} des publications de ce sujet portent aussi « {subject.label} »
      </div>
      <div class="tip-muted">{hovered.neighbor.usage_count.toLocaleString("fr-FR")} publications au total</div>
    </div>
  {/if}
</div>

<style>
  .graph {
    position: relative;
  }
  svg {
    display: block;
    width: 100%;
    height: auto;
    margin: 0 auto;
    overflow: visible;
  }
  .edge {
    stroke: var(--border);
    stroke-linecap: round;
  }
  .edge.active {
    stroke: var(--accent-mid);
  }
  .center {
    fill: var(--accent-mid);
    stroke: var(--bg);
    stroke-width: 3;
  }
  .node {
    cursor: pointer;
    outline: none;
  }
  /* Focus au clavier : le cercle du sujet se cerne de la couleur d'accent. */
  .node:focus-visible circle {
    stroke: var(--accent);
    stroke-width: 3;
  }
  .node circle {
    fill: var(--muted);
    stroke: var(--bg);
    stroke-width: 2;
  }
  .node.active circle {
    fill: var(--accent-mid);
  }
  .label {
    font-size: var(--fs-sm);
    fill: var(--text);
    /* Halo du fond de page : les libellés restent lisibles sur les liens. */
    paint-order: stroke;
    stroke: var(--bg);
    stroke-width: 4px;
    stroke-linejoin: round;
  }
  .node.active .label {
    fill: var(--accent);
    font-weight: 600;
  }
  .center-label {
    font-size: var(--fs-md);
    font-weight: 700;
    fill: var(--accent);
  }
  .graph-tip {
    position: absolute;
    z-index: 10;
    transform: translate(-50%, 10px);
    width: 280px;
    padding: 10px 12px;
    border-radius: var(--radius);
    background: var(--card);
    box-shadow: 0 6px 20px rgba(16, 24, 40, 0.14), 0 0 0 1px rgba(16, 24, 40, 0.06);
    font-size: var(--fs-sm);
    line-height: 1.45;
    color: var(--text-secondary);
    pointer-events: none;
  }
  .tip-title {
    margin-bottom: 4px;
    font-weight: 700;
    color: var(--text);
  }
  .tip-muted {
    color: var(--muted);
  }
</style>
