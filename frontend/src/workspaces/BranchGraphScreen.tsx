import { useTranslation } from "react-i18next";

import { useBranchGraph } from "../api/branches";
import type { Workspace } from "../api/workspaces";
import { type PlacedCommit, layout } from "./graphLanes";

// Pas d'unité ici : ce sont des pixels, et la grille doit rester régulière pour que les
// traits tombent exactement sur les pastilles.
const ROW = 34;
const LANE = 22;
const DOT = 5;
const MARGIN = 14;

function x(lane: number): number {
  return MARGIN + lane * LANE;
}

function y(row: number): number {
  return ROW / 2 + row * ROW;
}

/** Les traits d'un commit vers ses parents, en courbe quand ils changent de voie. */
function Edges({ placed, rows }: { placed: PlacedCommit; rows: number }) {
  return (
    <>
      {placed.edges.map((edge, index) => {
        // Parent non lu : le trait sort par le bas, ce qui montre la troncature au lieu
        // de laisser croire à une racine.
        const endRow = edge.toRow ?? rows;
        const start = `${x(edge.fromLane)},${y(placed.row)}`;
        const end = `${x(edge.toLane)},${y(endRow)}`;
        const bend = `${x(edge.toLane)},${y(placed.row) + ROW / 2}`;
        return (
          <path
            key={index}
            className="graph-edge"
            d={
              edge.fromLane === edge.toLane
                ? `M ${start} L ${end}`
                : `M ${start} Q ${bend} ${end}`
            }
          />
        );
      })}
    </>
  );
}

/**
 * Vue ferroviaire des branches (Gael, 24/10/2026) : les commits en voies, leurs liens de
 * parenté, et les branches qui les pointent.
 *
 * Le dessin est en SVG à côté des lignes, sur la MÊME grille : une ligne de texte vaut
 * une ligne de graphe, sinon les pastilles ne tombent pas en face de leur commit.
 *
 * Le bouton de fusion viendra ici.
 */
export function BranchGraphScreen({
  workspace,
  onBack,
}: {
  workspace: Workspace;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const graph = useBranchGraph(workspace.id);
  const { placed, width } = layout(graph.data ?? []);

  return (
    <section aria-labelledby="branch-graph-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("branches.graph.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="branch-graph-title">{t("branches.graph.title", { name: workspace.name })}</h1>
          <p className="lead muted">{t("branches.graph.lead")}</p>
        </div>
      </div>
      {graph.isPending && (
        <p className="muted" role="status">
          {t("dataModels.loading")}
        </p>
      )}
      {graph.isError && (
        <p className="alert" role="alert">
          {t("branches.graph.unreadable")}
        </p>
      )}
      {graph.isSuccess && placed.length === 0 && (
        <p className="muted">{t("branches.graph.empty")}</p>
      )}
      {placed.length > 0 && (
        <div className="card graph">
          <svg
            className="graph-rails"
            width={MARGIN * 2 + (width - 1) * LANE}
            height={placed.length * ROW}
            aria-hidden="true"
          >
            {placed.map((p) => (
              <Edges key={`e-${p.commit.sha}`} placed={p} rows={placed.length} />
            ))}
            {placed.map((p) => (
              <circle
                key={`d-${p.commit.sha}`}
                className={p.commit.refs.length > 0 ? "graph-dot graph-dot-ref" : "graph-dot"}
                cx={x(p.lane)}
                cy={y(p.row)}
                r={DOT}
              />
            ))}
          </svg>
          <ol className="graph-rows">
            {placed.map((p) => (
              <li key={p.commit.sha} className="graph-row" style={{ height: ROW }}>
                {p.commit.refs.map((ref) => (
                  <span key={ref} className="badge badge-accent">
                    {/* Nom court : le préfixe du workspace est le même sur toute la vue. */}
                    {ref.replace(`back/${workspace.id}/`, "")}
                  </span>
                ))}
                <span className="graph-subject">{p.commit.subject}</span>
                <span className="graph-meta mono">
                  {p.commit.sha.slice(0, 7)} · {p.commit.author}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
