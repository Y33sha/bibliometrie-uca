<script lang="ts">
  import { resolve } from "$app/paths";
  import type { components } from "#lib/api/schema.js";
  import {
    CENTER_LABEL_SIZE,
    CX,
    CY,
    LABEL_FLOOR,
    LABEL_SIZE,
    LINE_HEIGHT,
    subjectGraphLayout,
    type GraphNode,
  } from "./subjectGraphLayout";
  import { specificityPercent } from "./specificity";

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

  const layoutFor = $derived(subjectGraphLayout(subject, neighbors, links));
  // Largeur disponible dans la page, connue une fois le conteneur affiché.
  let width = $state(0);
  const layout = $derived(width > 0 ? layoutFor(width) : null);
  // En deçà de cette largeur, les libellés passeraient sous la taille minimale : le graphe défile horizontalement.
  const minWidth = $derived(layout ? (layout.box.width * LABEL_FLOOR) / LABEL_SIZE : 0);
  const overflowing = $derived(minWidth > width);

  let scroller = $state<HTMLDivElement>();
  // Le défilement horizontal part du centre du graphe.
  $effect(() => {
    if (overflowing && scroller) scroller.scrollLeft = (scroller.scrollWidth - scroller.clientWidth) / 2;
  });

  // Brut : comparé par identité aux nœuds du placement, il ne doit pas être enveloppé dans un proxy.
  let hovered = $state.raw<GraphNode | null>(null);
</script>

<div class="graph" class:overflowing bind:clientWidth={width} bind:this={scroller}>
  {#if layout}
    <div class="plot" style="max-width: {layout.box.width}px; min-width: {minWidth}px">
      <svg
        viewBox="{layout.box.x} {layout.box.y} {layout.box.width} {layout.box.height}"
        role="group"
        aria-label="Graphe des sujets associés à {subject.label}"
      >
        {#each layout.nodes as n (n.neighbor.label_normalized)}
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

        {#each layout.nodes as n (n.neighbor.label_normalized)}
          {@const right = n.x >= CX}
          {@const labelX = n.x + (right ? n.r + 6 : -n.r - 6)}
          <a
            href={resolve(`subjects/${n.neighbor.label_normalized}`)}
            class="node"
            class:active={hovered === n}
            onmouseenter={() => (hovered = n)}
            onmouseleave={() => (hovered = null)}
            onfocus={() => (hovered = n)}
            onblur={() => (hovered = null)}
          >
            <circle cx={n.x} cy={n.y} r={n.r} />
            <!-- Lignes centrées verticalement sur le cercle. -->
            <text
              y={n.y}
              class="label"
              font-size={LABEL_SIZE}
              text-anchor={right ? "start" : "end"}
              dominant-baseline="middle"
              >{#each n.lines as line, i (i)}<tspan x={labelX} dy={i === 0 ? (-(n.lines.length - 1) * LINE_HEIGHT) / 2 : LINE_HEIGHT}>{line}</tspan>{/each}</text
            >
          </a>
        {/each}

        <!-- Titre du sujet central, dessiné en dernier pour rester au-dessus. -->
        <text
          x={CX}
          y={CY + layout.centerR + 18}
          class="label center-label"
          font-size={CENTER_LABEL_SIZE}
          text-anchor="middle">{subject.label}</text
        >
      </svg>

      {#if hovered}
        <div
          class="graph-tip"
          style="left: {((hovered.x - layout.box.x) / layout.box.width) * 100}%; top: {((hovered.y + hovered.r - layout.box.y) / layout.box.height) * 100}%"
        >
          <div class="tip-title">{hovered.neighbor.label}</div>
          <div>{hovered.neighbor.cooccurrence_count.toLocaleString("fr-FR")} publications en commun</div>
          <div>
            {specificityPercent(hovered.neighbor)}&nbsp;% des publications de ce sujet portent aussi « {subject.label} »
          </div>
          <div class="tip-muted">{hovered.neighbor.usage_count.toLocaleString("fr-FR")} publications au total</div>
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .graph.overflowing {
    overflow-x: auto;
  }
  /* Zone du graphe : elle épouse le dessin, l'infobulle s'y positionne. */
  .plot {
    position: relative;
    margin: 0 auto;
  }
  svg {
    display: block;
    width: 100%;
    height: auto;
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
