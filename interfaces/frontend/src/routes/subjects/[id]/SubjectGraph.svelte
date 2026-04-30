<script lang="ts">
  import { onDestroy, onMount } from "svelte";
  import { DataSet, Network } from "vis-network/standalone";
  import type { Node, Edge, Options } from "vis-network/standalone";
  import type { components } from "$lib/api/schema";

  type SubjectListItem = components["schemas"]["SubjectListItem"];
  type SubjectNeighbor = components["schemas"]["SubjectNeighborOut"];

  let {
    subject,
    neighbors,
    onSelect,
  }: {
    subject: SubjectListItem;
    neighbors: SubjectNeighbor[];
    onSelect: (id: number) => void;
  } = $props();

  let container: HTMLDivElement | undefined = $state();
  let network: Network | undefined;

  /** Palette identique à SubjectsCloud, pour cohérence visuelle entre le
   *  nuage et le graphe. Couleur stable par sujet via hash de l'id. */
  const PALETTE = ["#075985", "#0369a1", "#7c3aed", "#9333ea", "#be123c", "#b45309"];
  function colorFor(id: number): string {
    return PALETTE[id % PALETTE.length];
  }

  /** Taille de police adaptative au range du graphe en cours. */
  function nodeFontSize(
    usageCount: number,
    minUsage: number,
    maxUsage: number,
  ): number {
    const minSize = 18;
    const maxSize = 38;
    if (maxUsage === minUsage) return (minSize + maxSize) / 2;
    const t =
      (Math.log10(usageCount + 1) - Math.log10(minUsage + 1)) /
      (Math.log10(maxUsage + 1) - Math.log10(minUsage + 1));
    return minSize + t * (maxSize - minSize);
  }

  /** Wrap un label sur les espaces (jamais en milieu de mot).
   *  vis-network respecte les `\n` dans les labels ; on précalcule les
   *  retours à la ligne plutôt que de laisser `widthConstraint` couper. */
  function wrapLabel(label: string, maxCharsPerLine = 18): string {
    const words = label.split(/\s+/).filter(Boolean);
    if (words.length === 0) return label;
    const lines: string[] = [];
    let current = "";
    for (const word of words) {
      if (current && current.length + 1 + word.length > maxCharsPerLine) {
        lines.push(current);
        current = word;
      } else {
        current = current ? `${current} ${word}` : word;
      }
    }
    if (current) lines.push(current);
    return lines.join("\n");
  }

  /** Longueur de l'arête en fonction de la *spécificité côté voisin* :
   *
   *      spec = cooc / usage_neighbor
   *
   *  C'est la fraction des publications du voisin qui touchent au sujet
   *  central. Asymétrique, dévalorise les sujets ubiquitous (ex un parent
   *  très large a peu de spécificité côté lui-même), qui sont alors
   *  relégués à la périphérie du graphe sans être filtrés.
   *
   *  Échelle log pour ne pas écraser les faibles spécificités. */
  function edgeLength(spec: number, minSpec: number, maxSpec: number): number {
    const minLen = 120;
    const maxLen = 500;
    if (maxSpec === minSpec) return (minLen + maxLen) / 2;
    // log(0) → −∞, on ajoute un epsilon ; on a déjà spec > 0 puisque
    // cooc >= min_cooccurrence >= 1 et usage > 0.
    const eps = 1e-6;
    const t =
      (Math.log(spec + eps) - Math.log(minSpec + eps)) /
      (Math.log(maxSpec + eps) - Math.log(minSpec + eps));
    return maxLen - (maxLen - minLen) * t;
  }


  function buildData(): { nodes: Node[]; edges: Edge[] } {
    // Min/max sur tous les nœuds visibles (centre + voisins) pour calibrer
    // les tailles relativement au graphe courant.
    const allUsages = [subject.usage_count, ...neighbors.map((n) => n.usage_count)];
    const minUsage = Math.min(...allUsages);
    const maxUsage = Math.max(...allUsages);
    // Texte nu : la couleur vient de la palette stable par id (mêmes
    // règles que SubjectsCloud) ; le centre est agrandi pour rester
    // identifiable une fois la physique figée.
    const fontFor = (id: number, usageCount: number, isCenter: boolean) => ({
      size: nodeFontSize(usageCount, minUsage, maxUsage) + (isCenter ? 6 : 0),
      color: colorFor(id),
      face: "system-ui, sans-serif",
    });
    const nodes: Node[] = [
      {
        id: subject.id,
        label: wrapLabel(subject.label),
        font: fontFor(subject.id, subject.usage_count, true),
      },
    ];
    const edges: Edge[] = [];
    // Spécificité côté voisin : `cooc / usage_neighbor`. Bornée à 1.
    const specificities = neighbors.map((n) =>
      n.usage_count > 0 ? Math.min(1, n.cooccurrence_count / n.usage_count) : 0,
    );
    const minSpec = specificities.length ? Math.min(...specificities) : 0;
    const maxSpec = specificities.length ? Math.max(...specificities) : 0;
    for (const [i, n] of neighbors.entries()) {
      nodes.push({
        id: n.id,
        label: wrapLabel(n.label),
        font: fontFor(n.id, n.usage_count, false),
      });
      const spec = specificities[i];
      edges.push({
        from: subject.id,
        to: n.id,
        value: n.cooccurrence_count,
        length: edgeLength(spec, minSpec, maxSpec),
        title: `${n.cooccurrence_count} co-occurrences (spécificité ${(spec * 100).toFixed(1)} %)`,
      });
    }
    return { nodes, edges };
  }

  function buildOptions(): Options {
    return {
      nodes: {
        // Texte nu, sans cercle ni rectangle : aligne visuellement le
        // graphe avec le nuage de mots du dashboard. Les arêtes
        // connectent au centre du label.
        shape: "text",
      },
      edges: {
        scaling: { min: 1, max: 8 },
        color: { color: "#cbd5e1", highlight: "#64748b", hover: "#64748b" },
        smooth: { enabled: true, type: "continuous", roundness: 0.3 },
      },
      physics: {
        solver: "forceAtlas2Based",
        forceAtlas2Based: {
          gravitationalConstant: -120,
          centralGravity: 0.005,
          springLength: 200,
          springConstant: 0.06,
          avoidOverlap: 1,
        },
        stabilization: { iterations: 300 },
      },
      interaction: {
        hover: true,
        tooltipDelay: 150,
      },
    };
  }

  // Quand `subject` ou `neighbors` changent (navigation), on rebuild les datasets.
  $effect(() => {
    if (!network) return;
    const { nodes, edges } = buildData();
    network.setData({
      nodes: new DataSet<Node>(nodes),
      edges: new DataSet<Edge>(edges),
    });
  });

  onMount(() => {
    if (!container) return;
    const { nodes, edges } = buildData();
    network = new Network(
      container,
      {
        nodes: new DataSet<Node>(nodes),
        edges: new DataSet<Edge>(edges),
      },
      buildOptions(),
    );
    network.on("click", (params: { nodes: (string | number)[] }) => {
      if (params.nodes.length === 0) return;
      const clickedId = Number(params.nodes[0]);
      if (clickedId !== subject.id) onSelect(clickedId);
    });
    // Une fois la physique stabilisée : recentre + désactive la physique pour
    // figer le graphe (les nœuds restent draggables manuellement, mais plus
    // de rebond infini). vis-network réactive la physique à un drag, on la
    // re-coupe à la fin via le bus d'événements.
    network.once("stabilizationIterationsDone", () => {
      network?.fit({ animation: false });
      network?.setOptions({ physics: { enabled: false } });
    });
    network.on("dragEnd", () => {
      network?.setOptions({ physics: { enabled: false } });
    });
  });

  onDestroy(() => {
    network?.destroy();
    network = undefined;
  });
</script>

<div bind:this={container} class="graph"></div>

<style>
  .graph {
    width: 100%;
    height: 70vh;
    background: white;
    border: 1px solid var(--border);
    border-radius: 6px;
  }
</style>
