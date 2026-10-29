import type { components } from "#lib/api/schema.js";

type SubjectListItem = components["schemas"]["SubjectListItem"];
type SubjectNeighbor = components["schemas"]["SubjectNeighborOut"];
type SubjectNeighborLink = components["schemas"]["SubjectNeighborLink"];

/**
 * Placement du graphe radial d'un sujet : le sujet au centre, ses voisins répartis tout autour sur une ellipse.
 *
 * - L'ordre des voisins autour du centre met côte à côte les sujets qui se rencontrent souvent.
 * - La distance au centre dépend de la spécificité de l'association : les plus spécifiques au plus près.
 * - Les recouvrements de cercles et de libellés se règlent en faisant glisser les voisins le long de leur ellipse, sans changer leur distance au centre.
 */

// Repère du placement, centré sur le sujet central ; le cadre affiché (viewBox) épouse le graphe et ses libellés.
export const CX = 0;
export const CY = 0;
/** Étirement horizontal : l'ellipse est plus large que haute, comme l'écran. */
const STRETCH = 1.6;
/** Distance au centre des voisins les plus spécifiques, et écart jusqu'aux moins spécifiques. */
export const INNER_RING = 60;
const RING_SPAN = 140;
const LABEL_SIZE = 13;
const CENTER_LABEL_SIZE = 15;
/** Largeur approximative d'un libellé, en unités du repère, pour une taille de police donnée. */
const labelWidth = (label: string, fontSize: number) => label.length * fontSize * 0.54;

export interface GraphNode {
  neighbor: SubjectNeighbor;
  r: number;
  labelWidth: number;
  /** Spécificité côté voisin : part de ses publications qui portent aussi le sujet central. */
  specificity: number;
  /** Distance au centre, mesurée sur l'ellipse. */
  distance: number;
  x: number;
  y: number;
}

export interface Box {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

/** Rayon d'un cercle selon le nombre de publications du sujet (aire proportionnelle). */
function radius(usage: number, maxUsage: number): number {
  return 5 + (Math.sqrt(usage) / Math.sqrt(maxUsage)) * 17;
}

/** Emprise d'un voisin : son cercle et son libellé, placé du côté extérieur du graphe. */
export function nodeBox(n: GraphNode): Box {
  const half = Math.max(n.r, LABEL_SIZE * 0.7);
  return n.x >= CX
    ? { x0: n.x - n.r, x1: n.x + n.r + 6 + n.labelWidth, y0: n.y - half, y1: n.y + half }
    : { x0: n.x - n.r - 6 - n.labelWidth, x1: n.x + n.r, y0: n.y - half, y1: n.y + half };
}

/** Place un voisin sur l'ellipse de distance donnée (par défaut la sienne), à l'angle donné. */
function placeAt(n: GraphNode, angle: number, distance = n.distance): void {
  n.x = CX + Math.cos(angle) * distance * STRETCH;
  n.y = CY + Math.sin(angle) * distance;
}

/** Angle d'un voisin sur son ellipse. */
function angleOf(n: GraphNode): number {
  return Math.atan2(n.y - CY, (n.x - CX) / STRETCH);
}

/**
 * Ordre circulaire des voisins qui maximise la proximité entre voisins consécutifs : chaîne gloutonne depuis le voisin le plus fréquent, puis améliorations par inversion de segments (2-opt).
 */
function circularOrder(nodes: GraphNode[], sim: (a: GraphNode, b: GraphNode) => number): GraphNode[] {
  const remaining = [...nodes].sort((a, b) => b.neighbor.cooccurrence_count - a.neighbor.cooccurrence_count);
  const order: GraphNode[] = [remaining.shift()!];
  while (remaining.length) {
    const last = order[order.length - 1];
    let best = 0;
    for (let i = 1; i < remaining.length; i++) if (sim(last, remaining[i]) > sim(last, remaining[best])) best = i;
    order.push(...remaining.splice(best, 1));
  }
  const n = order.length;
  let improved = true;
  while (improved && n > 3) {
    improved = false;
    for (let i = 0; i < n - 1; i++) {
      for (let j = i + 2; j < n; j++) {
        if (i === 0 && j === n - 1) continue;
        const a = order[i];
        const b = order[i + 1];
        const c = order[j];
        const d = order[(j + 1) % n];
        if (sim(a, c) + sim(b, d) > sim(a, b) + sim(c, d) + 1e-12) {
          order.splice(i + 1, j - i, ...order.slice(i + 1, j + 1).reverse());
          improved = true;
        }
      }
    }
  }
  return order;
}

export function subjectGraphLayout(
  subject: SubjectListItem,
  neighbors: SubjectNeighbor[],
  links: SubjectNeighborLink[],
) {
  const maxUsage = Math.max(subject.usage_count, ...neighbors.map((n) => n.usage_count), 1);
  const maxCooc = Math.max(...neighbors.map((n) => n.cooccurrence_count), 1);
  const specs = neighbors.map((n) => Math.min(1, n.cooccurrence_count / Math.max(n.usage_count, 1)));
  const logMin = Math.log(Math.min(...specs));
  const logMax = Math.log(Math.max(...specs));
  // Distance au centre : l'anneau intérieur pour les plus spécifiques, puis un écart croissant quand la spécificité baisse, en échelle log pour ne pas écraser les faibles spécificités.
  const distanceOf = (spec: number) => {
    const t = logMax === logMin ? 0.5 : (Math.log(spec) - logMin) / (logMax - logMin);
    return INNER_RING + RING_SPAN * (1 - t);
  };
  const nodes: GraphNode[] = neighbors.map((n, i) => ({
    neighbor: n,
    r: radius(n.usage_count, maxUsage),
    labelWidth: labelWidth(n.label, LABEL_SIZE),
    specificity: specs[i],
    distance: distanceOf(specs[i]),
    x: CX,
    y: CY,
  }));
  const byId = new Map(nodes.map((n) => [n.neighbor.id, n]));

  // Proximité de deux voisins : leurs publications en commun, rapportées à la moyenne géométrique de leurs tailles.
  const similarity = new Map<string, number>();
  const pairKey = (a: number, b: number) => (a < b ? `${a}-${b}` : `${b}-${a}`);
  for (const l of links) {
    const a = byId.get(l.subject_a_id);
    const b = byId.get(l.subject_b_id);
    if (a && b) similarity.set(pairKey(a.neighbor.id, b.neighbor.id), l.cooccurrence_count / Math.sqrt(a.neighbor.usage_count * b.neighbor.usage_count));
  }
  const sim = (a: GraphNode, b: GraphNode) => similarity.get(pairKey(a.neighbor.id, b.neighbor.id)) ?? 0;

  const order = circularOrder(nodes, sim);
  const baseDistance = new Map(nodes.map((n) => [n, n.distance]));

  // Le sujet central et son titre, placé dessous, forment une emprise fixe que les voisins contournent.
  const centerR = radius(subject.usage_count, maxUsage) + 4;
  const centerLabelHalf = labelWidth(subject.label, CENTER_LABEL_SIZE) / 2;
  const centerBox: Box = {
    x0: CX - Math.max(centerLabelHalf, centerR),
    x1: CX + Math.max(centerLabelHalf, centerR),
    y0: CY - centerR,
    y1: CY + centerR + 24,
  };

  // Recouvrements : on écarte les emprises le long de l'axe du moindre recouvrement, puis chaque voisin revient sur son ellipse en gardant son nouvel angle. Renvoie vrai si plus rien ne se recouvre.
  const gap = 4;
  function relax(): boolean {
    for (let pass = 0; pass < 300; pass++) {
      let moved = false;
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i];
        for (let j = i + 1; j <= nodes.length; j++) {
          const b = j < nodes.length ? nodes[j] : null;
          const ba = nodeBox(a);
          const bb = b ? nodeBox(b) : centerBox;
          const ox = Math.min(ba.x1, bb.x1) - Math.max(ba.x0, bb.x0) + gap;
          const oy = Math.min(ba.y1, bb.y1) - Math.max(ba.y0, bb.y0) + gap;
          if (ox <= 0 || oy <= 0) continue;
          moved = true;
          const share = b ? 0.5 : 1;
          if (ox < oy) {
            const sign = (ba.x0 + ba.x1) / 2 < (bb.x0 + bb.x1) / 2 ? -1 : 1;
            a.x += sign * ox * share;
            if (b) b.x -= sign * ox * share;
          } else {
            const sign = (ba.y0 + ba.y1) / 2 < (bb.y0 + bb.y1) / 2 ? -1 : 1;
            a.y += sign * oy * share;
            if (b) b.y -= sign * oy * share;
          }
        }
      }
      // Retour vers l'ellipse : chaque voisin garde son nouvel angle et peut s'écarter un peu de sa distance théorique, ce qui règle les recouvrements sur place.
      for (const n of nodes) {
        const actual = Math.hypot((n.x - CX) / STRETCH, n.y - CY);
        placeAt(n, angleOf(n), Math.min(Math.max(actual, n.distance * 0.85), n.distance * 1.35));
      }
      if (!moved) return true;
    }
    return false;
  }

  // Répartition régulière tout autour du centre, dans l'ordre de proximité. Quand la place manque, l'écart au-delà de l'anneau intérieur grandit par paliers : les plus spécifiques restent près du centre, l'ordre des distances ne change pas.
  for (let scale = 1; scale < 3; scale *= 1.1) {
    for (const n of nodes) n.distance = INNER_RING + (baseDistance.get(n)! - INNER_RING) * scale;
    order.forEach((n, i) => placeAt(n, -Math.PI / 2 + (2 * Math.PI * i) / order.length));
    if (relax()) break;
  }

  // Cadre englobant cercles et libellés, avec une marge.
  let { x0: minX, x1: maxX, y0: minY, y1: maxY } = centerBox;
  for (const n of nodes) {
    const b = nodeBox(n);
    minX = Math.min(minX, b.x0);
    maxX = Math.max(maxX, b.x1);
    minY = Math.min(minY, b.y0);
    maxY = Math.max(maxY, b.y1);
  }
  const pad = 12;
  const box = { x: minX - pad, y: minY - pad, width: maxX - minX + 2 * pad, height: maxY - minY + 2 * pad };

  return {
    nodes,
    box,
    centerBox,
    centerR,
    strokeWidth: (cooc: number) => 1 + (cooc / maxCooc) * 6,
  };
}
