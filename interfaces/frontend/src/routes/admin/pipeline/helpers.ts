/** Helpers partagés de la page pipeline : couleurs de statut, formatage. */

export type Status = "ok" | "warning" | "error";

export const STATUS_LABEL: Record<Status, string> = {
  ok: "OK",
  warning: "Avertissement",
  error: "Erreur",
};

// Couleurs de statut des cases du ruban et des pastilles, insérées dans des attributs `style`.
export const CELL_COLOR: Record<Status | "ghost", string> = {
  ok: "var(--success)",
  warning: "var(--warning)",
  error: "var(--danger)",
  ghost: "var(--border)",
};

export const CELL_BG: Record<Status | "ghost", string> = {
  ok: "var(--success-light)",
  warning: "var(--warning-light)",
  error: "var(--danger-light)",
  ghost: "transparent",
};

export function fmtDate(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fmtDuration(s: number): string {
  if (s < 60) return `${s.toFixed(0)} s`;
  const m = Math.floor(s / 60);
  const rs = Math.round(s - m * 60);
  if (m < 60) return `${m} min ${rs} s`;
  const h = Math.floor(m / 60);
  return `${h} h ${m - h * 60} min`;
}

