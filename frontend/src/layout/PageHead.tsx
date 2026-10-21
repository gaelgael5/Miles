import type { ReactNode } from "react";

/** En-tête des maquettes : titre et chapeau à gauche, action principale à droite. */
export function PageHead({
  id,
  title,
  lead,
  action,
}: {
  id: string;
  title: string;
  lead: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        <h1 id={id}>{title}</h1>
        <p className="lead">{lead}</p>
      </div>
      {action}
    </div>
  );
}
