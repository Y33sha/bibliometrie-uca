<script lang="ts">
  import { forceCollide, forceLink, forceManyBody, forceRadial, forceSimulation } from "d3-force";
  import type { SimulationLinkDatum, SimulationNodeDatum } from "d3-force";
  import type { components } from "#lib/api/schema.js";

  type SubjectListItem = components["schemas"]["SubjectListItem"];
  type SubjectNeighbor = components["schemas"]["SubjectNeighborOut"];
  type SubjectNeighborLink = components["schemas"]["SubjectNeighborLink"];

  // Graphe radial d'un sujet : le sujet au centre, ses voisins autour. Un voisin est d'autant plus proche du centre que l'association est spécifique ; les co-occurrences entre voisins rapprochent les sujets apparentés.
  let {
    subject,
    neighbors,
    links,
    onSelect,
  }: {
    subject: SubjectListItem;
    neighbors: SubjectNeighbor[];
    links: SubjectNeighborLink[];
    onSelect: (id: number) => void;
  } = $props();

  // Repère du placement ; le cadre affiché (viewBox) est recalculé pour épouser le graphe et ses libellés.
  const CX = 0;
  const CY = 0;
  /** Largeur approximative d'un libellé, en unités du repère, pour une taille de police donnée. */
  const labelWidth = (label: string, fontSize: number) => label.length * fontSize * 0.54;

  interface GraphNode extends SimulationNodeDatum {
    neighbor: SubjectNeighbor;
    r: number;
    /** Rayon d'encombrement : cercle et marge pour le libellé. */
    clearance: number;
    /** Spécificité côté voisin : part de ses publications qui portent aussi le sujet central. */
    specificity: number;
  }

  interface GraphLink extends SimulationLinkDatum<GraphNode> {
    cooccurrence: number;
  }

  /** Rayon d'un cercle selon le nombre de publications du sujet (aire proportionnelle). */
  function radius(usage: number, maxUsage: number): number {
    return 5 + (Math.sqrt(usage) / Math.sqrt(maxUsage)) * 17;
  }

  const layout = $derived.by(() => {
    const maxUsage = Math.max(subject.usage_count, ...neighbors.map((n) => n.usage_count), 1);
    const maxCooc = Math.max(...neighbors.map((n) => n.cooccurrence_count), 1);
    const specs = neighbors.map((n) => Math.min(1, n.cooccurrence_count / Math.max(n.usage_count, 1)));
    const logMin = Math.log(Math.min(...specs));
    const logMax = Math.log(Math.max(...specs));
    // Distance au centre : les plus spécifiques au plus près, en échelle log pour ne pas écraser les faibles spécificités.
    const distance = (spec: number) => {
      const t = logMax === logMin ? 0.5 : (Math.log(spec) - logMin) / (logMax - logMin);
      return 230 - 130 * t;
    };
    const nodes: GraphNode[] = neighbors.map((n, i) => {
      const r = radius(n.usage_count, maxUsage);
      return { neighbor: n, r, clearance: r + 26, specificity: specs[i] };
    });
    // Le sujet central et son titre, placé dessous, forment un obstacle fixe que les voisins contournent.
    const centerR = radius(subject.usage_count, maxUsage) + 4;
    const centerLabelHalf = labelWidth(subject.label, 17) / 2;
    const centerObstacle = {
      neighbor: null,
      r: centerR,
      clearance: Math.max(centerR + 30, centerLabelHalf + 12),
      specificity: 1,
      fx: CX,
      fy: CY,
    };
    const byId = new Map(nodes.map((n) => [n.neighbor.id, n]));
    const maxLink = Math.max(...links.map((l) => l.cooccurrence_count), 1);
    const neighborLinks: GraphLink[] = links
      .filter((l) => byId.has(l.subject_a_id) && byId.has(l.subject_b_id))
      .map((l) => ({ source: byId.get(l.subject_a_id)!, target: byId.get(l.subject_b_id)!, cooccurrence: l.cooccurrence_count }));

    const simulation = forceSimulation<GraphNode>([...nodes, centerObstacle as unknown as GraphNode])
      .force("radial", forceRadial<GraphNode>((n) => distance(n.specificity), CX, CY).strength((n) => (n.neighbor ? 0.9 : 0)))
      .force(
        "neighbors",
        forceLink<GraphNode, GraphLink>(neighborLinks)
          .distance(70)
          .strength((l) => 0.05 + 0.35 * (l.cooccurrence / maxLink)),
      )
      .force("charge", forceManyBody<GraphNode>().strength(-60))
      .force("collide", forceCollide<GraphNode>((n) => n.clearance))
      .stop();
    for (let i = 0; i < 300; i++) simulation.tick();

    // L'ellipse occupe la largeur disponible : abscisses étirées autour du centre.
    for (const n of nodes) n.x = CX + ((n.x ?? CX) - CX) * 1.7;

    // Cadre englobant cercles et libellés, avec une marge.
    let minX = CX - centerLabelHalf;
    let maxX = CX + centerLabelHalf;
    let minY = CY - centerR;
    let maxY = CY + centerR + 28;
    for (const n of nodes) {
      const x = n.x ?? CX;
      const y = n.y ?? CY;
      const w = labelWidth(n.neighbor.label, 14);
      minX = Math.min(minX, x >= CX ? x - n.r : x - n.r - 6 - w);
      maxX = Math.max(maxX, x >= CX ? x + n.r + 6 + w : x + n.r);
      minY = Math.min(minY, y - Math.max(n.r, 10));
      maxY = Math.max(maxY, y + Math.max(n.r, 10));
    }
    const pad = 12;
    const box = { x: minX - pad, y: minY - pad, width: maxX - minX + 2 * pad, height: maxY - minY + 2 * pad };

    return {
      nodes,
      box,
      centerR,
      strokeWidth: (cooc: number) => 1 + (cooc / maxCooc) * 6,
    };
  });

  let hovered = $state<GraphNode | null>(null);

  function percent(spec: number): string {
    return (spec * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " %";
  }
</script>

<div class="graph">
  <svg
    viewBox="{layout.box.x} {layout.box.y} {layout.box.width} {layout.box.height}"
    role="img"
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
      {@const right = (n.x ?? CX) >= CX}
      <g
        class="node"
        class:active={hovered === n}
        role="link"
        tabindex="0"
        aria-label={n.neighbor.label}
        onmouseenter={() => (hovered = n)}
        onmouseleave={() => (hovered = null)}
        onfocus={() => (hovered = n)}
        onblur={() => (hovered = null)}
        onclick={() => onSelect(n.neighbor.id)}
        onkeydown={(e) => {
          if (e.key === "Enter") onSelect(n.neighbor.id);
        }}
      >
        <circle cx={n.x} cy={n.y} r={n.r} />
        <text
          x={(n.x ?? 0) + (right ? n.r + 6 : -n.r - 6)}
          y={n.y}
          class="label"
          text-anchor={right ? "start" : "end"}
          dominant-baseline="middle">{n.neighbor.label}</text
        >
      </g>
    {/each}

    <!-- Titre du sujet central, dessiné en dernier pour rester au-dessus. -->
    <text x={CX} y={CY + layout.centerR + 18} class="label center-label" text-anchor="middle">{subject.label}</text>
  </svg>

  {#if hovered}
    <div
      class="graph-tip"
      style="left: {(((hovered.x ?? 0) - layout.box.x) / layout.box.width) * 100}%; top: {(((hovered.y ?? 0) + hovered.r - layout.box.y) / layout.box.height) * 100}%"
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
  .node circle {
    fill: var(--muted);
    stroke: var(--bg);
    stroke-width: 2;
  }
  .node.active circle {
    fill: var(--accent-mid);
  }
  .label {
    font-size: 14px;
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
    font-size: 17px;
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
    font-size: 0.85rem;
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
