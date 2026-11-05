import { useTranslation } from "react-i18next";

import { useInstant } from "@miles/socle-web";

import {
  type OrderedVersion,
  type PublishedVersion,
  hostingRefusKey,
  repositoryReason,
  useOrderVersion,
  useOrderedVersion,
  usePublishedVersions,
  useResendOrder,
} from "../api/hosting";

/**
 * Ce que l'environnement SERT, et ce qu'on peut lui demander de servir.
 *
 * L'écran distingue toujours trois choses, parce que les confondre ferait croire à un
 * parc à jour qui ne l'est pas : ce qui est PUBLIÉ dans le dépôt, ce qui est ORDONNÉ à
 * l'environnement, et ce qu'il a CONFIRMÉ servir. La troisième est un instantané daté —
 * la stack peut avoir redémarré depuis —, et c'est pour cela que l'écran dit « au
 * <instant> » et jamais « actuellement ».
 */
export function HostedVersion({ environmentId }: { environmentId: string }) {
  const { t } = useTranslation();
  const publiees = usePublishedVersions(environmentId);
  const ordonnee = useOrderedVersion(environmentId);
  const ordonner = useOrderVersion(environmentId);
  const renvoyer = useResendOrder(environmentId);

  return (
    <div className="card">
      <div className="card-head">
        <h2>{t("workspaces.version.title")}</h2>
      </div>
      {ordonnee.data === undefined ? (
        // « Aucune version ordonnée » est un état à part entière, et pas une panne : le
        // serveur rend 404, et l'écran le DIT plutôt que d'afficher une ligne vide.
        <p className="help">{t("workspaces.version.none")}</p>
      ) : (
        <Etat ordonnee={ordonnee.data} />
      )}
      {publiees.isError && <Refus error={publiees.error} />}
      {ordonner.isError && <Refus error={ordonner.error} />}
      {renvoyer.isError && <Refus error={renvoyer.error} />}
      {publiees.data !== undefined && (
        <Liste
          versions={publiees.data}
          ordonnee={ordonnee.data ?? null}
          onChoisir={(number) => ordonner.mutate(number)}
          onRenvoyer={() => renvoyer.mutate()}
          enCours={ordonner.isPending || renvoyer.isPending}
        />
      )}
    </div>
  );
}

function Etat({ ordonnee }: { ordonnee: OrderedVersion }) {
  const { t } = useTranslation();
  const instant = useInstant();
  const acquitte = ordonnee.acked_at === null ? null : instant(ordonnee.acked_at);
  return (
    <dl className="facts">
      <div>
        <dt className="caption">{t("workspaces.version.captionOrdered")}</dt>
        <dd className="value">
          {t("workspaces.version.numbered", { number: ordonnee.number })}{" "}
          <span className="badge">{ordonnee.commit.slice(0, 12)}</span>
        </dd>
      </div>
      <div>
        <dt className="caption">{t("workspaces.version.captionServed")}</dt>
        <dd className="value">
          {ordonnee.up_to_date ? (
            <span className="badge badge-ok">{t("workspaces.version.upToDate")}</span>
          ) : (
            // Le refus est NOMMÉ : chacun appelle un geste différent, et « pas à jour »
            // seul enverrait chercher au hasard. Le geste, lui, est sur la LIGNE de la
            // version ordonnée, juste en dessous : un même geste offert à deux endroits
            // laisse croire à deux effets.
            <span className="badge badge-warning">
              {ordonnee.refusal === null
                ? t("workspaces.version.notApplied")
                : t(`workspaces.version.refusals.${ordonnee.refusal}`, {
                    defaultValue: t("workspaces.version.refusals.unknown", {
                      code: ordonnee.refusal,
                    }),
                  })}
            </span>
          )}
          {acquitte !== null && (
            <span className="muted"> {t("workspaces.version.asOf", { instant: acquitte })}</span>
          )}
        </dd>
      </div>
    </dl>
  );
}

function Liste({
  versions,
  ordonnee,
  onChoisir,
  onRenvoyer,
  enCours,
}: {
  versions: PublishedVersion[];
  ordonnee: OrderedVersion | null;
  onChoisir: (number: number) => void;
  onRenvoyer: () => void;
  enCours: boolean;
}) {
  const { t } = useTranslation();
  const instant = useInstant();
  if (versions.length === 0) {
    // Lu du dépôt, donc une liste vide est une VÉRITÉ ici — contrairement à avant, où
    // elle n'aurait été qu'une absence de route. On le dit comme tel.
    return <p className="help">{t("workspaces.version.nonePublished")}</p>;
  }
  return (
    <ul className="rows">
      {versions.map((version) => (
        <li className="row" key={version.number}>
          <div className="row-main">
            <div className="row-title">
              {t("workspaces.version.numbered", { number: version.number })} — {version.label}
            </div>
            <div className="row-sub">
              {version.author} · {instant(version.saved_at)}
              {version.branch !== null && <> · {version.branch}</>}
            </div>
          </div>
          <div className="cell">
            <div className="value">
              <span className="badge">{version.commit.slice(0, 12)}</span>
            </div>
          </div>
          <div className="actions row-actions">
            {ordonnee !== null && ordonnee.commit === version.commit ? (
              <>
                <span className="badge">{t("workspaces.version.current")}</span>
                {/* Réassocier la version DÉJÀ ordonnée (Gael, 05/11/2026). Le renvoi
                    d'ordre est le geste de réparation complet du module d'environnement :
                    il rejoue l'aval — la matérialisation des tables de ses storages —
                    même quand l'arbre servi est déjà le bon. Sans ce bouton, il fallait
                    associer une AUTRE version puis revenir, ce qui fait deux poses là où
                    on n'en voulait aucune. */}
                <button type="button" className="btn" disabled={enCours} onClick={onRenvoyer}>
                  {t("workspaces.version.resend")}
                </button>
              </>
            ) : (
              <button
                type="button"
                className="btn"
                disabled={enCours}
                onClick={() => onChoisir(version.number)}
              >
                {t("workspaces.version.choose")}
              </button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}

function Refus({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const raison = repositoryReason(error);
  return (
    <p className="alert alert-danger" role="alert">
      {t(hostingRefusKey(error))}
      {raison !== null && (
        <>
          {" "}
          {t(`workspaces.version.reasons.${raison}`, {
            defaultValue: t("workspaces.version.reasons.unknown", { code: raison }),
          })}
        </>
      )}
    </p>
  );
}
