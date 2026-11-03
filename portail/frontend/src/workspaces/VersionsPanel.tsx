import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, ConfirmDialog, useInstant } from "@miles/socle-web";
import { usePublishHold } from "../api/holds";
import type { WorkTarget } from "../api/workTarget";
import { HoldRefusal } from "./HoldRefusal";
import { ProblemReports } from "./ProblemReports";

import {
  type FileReport,
  type SavedVersion,
  useFreezable,
  useRestoreVersion,
  useSaveVersion,
  useVersions,
} from "../api/dataModels";

type Detail = {
  code?: string;
  field?: string;
  reason?: string;
  reports?: FileReport[];
};

function VersionRefusal({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const detail =
    error instanceof ApiError && typeof error.detail === "object" ? (error.detail as Detail) : null;
  let message = t("versions.errors.unexpected");
  if (detail?.code === "parametrage_invalide") {
    message = t("versions.errors.invalid");
  } else if (detail?.code === "acces_depot") {
    message = t("dataModels.errors.access", { reason: detail.reason ?? "echec" });
  } else if (detail?.field === "label") {
    message = t("versions.errors.label");
  } else if (error instanceof ApiError && typeof error.detail === "string") {
    message = t(`versions.errors.conflict.${error.detail}`, {
      defaultValue: t(`dataModels.errors.conflict.${error.detail}`),
    });
  }
  return (
    <div className="alert" role="alert">
      <p>{message}</p>
      {detail?.reports !== undefined && <ProblemReports reports={detail.reports} />}
    </div>
  );
}

function SaveForm({ target, onDone }: { target: WorkTarget; onDone: () => void }) {
  const { t } = useTranslation();
  const save = useSaveVersion(target);
  const [label, setLabel] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate(label, { onSuccess: onDone });
  }

  return (
    <form className="panel" onSubmit={submit} aria-label={t("versions.save")}>
      <label className="field">
        {t("versions.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <p className="help">{t("versions.labelHelp")}</p>
      {save.isError && <VersionRefusal error={save.error} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={save.isPending}>
          {t("versions.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onDone}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}

function VersionRow({ target, version }: { target: WorkTarget; version: SavedVersion }) {
  const { t } = useTranslation();
  const instant = useInstant();
  const restore = useRestoreVersion(target);
  const [confirming, setConfirming] = useState(false);
  const date = instant(version.saved_at);

  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">
          {t("versions.number", { number: version.number })} — {version.label}
        </div>
        <div className="row-sub">
          {date} · {version.author} · <span className="mono">{version.commit.slice(0, 10)}</span>
        </div>
      </div>
      {/* Restaurer change le contenu : refusé sur la racine. Enregistrer y reste permis. */}
      {!target.readOnly && (
        <div className="actions row-actions">
          <button type="button" className="btn btn-secondary" onClick={() => setConfirming(true)}>
            {t("versions.restore")}
          </button>
        </div>
      )}
      {restore.isSuccess && (
        <p className="notice row-detail" role="status">
          {t("versions.restored", { commit: restore.data.commit.slice(0, 10) })}
        </p>
      )}
      {restore.isError && (
        <div className="row-detail">
          <VersionRefusal error={restore.error} />
        </div>
      )}
      {confirming && (
        <ConfirmDialog
          title={t("versions.restoreConfirm.title", { number: version.number })}
          confirmLabel={t("versions.restoreConfirm.confirm")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            restore.mutate(version.number);
          }}
        >
          <p>{t("versions.restoreConfirm.body", { label: version.label })}</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

/** Versions de la branche de travail : enregistrées explicitement, jamais automatiquement. */
export function VersionsPanel({ target }: { target: WorkTarget }) {
  const { t } = useTranslation();
  const versions = useVersions(target);
  const [saving, setSaving] = useState(false);
  // Interrogé seulement si la personne peut figer : inutile sinon, le bouton n'est pas là.
  const freezable = useFreezable(target, target.canFreeze);
  // `target.branch` EST le slug de la prise de main — c'est ce que `useWorkTarget`
  // compare à `hold.slug`. Aucune dérivation ici : elle divergerait de celle-là.
  // Déclaré inconditionnellement, et sans effet tant qu'on ne l'appelle pas : un hook
  // ne peut pas vivre sous une condition, et la racine n'a de toute façon pas de main.
  const publish = usePublishHold(target.workspaceId, target.branch);

  return (
    <section className="card" aria-labelledby="versions-title">
      <div className="card-head">
        <h2 id="versions-title">{t("versions.title")}</h2>
        {/* Racine : toujours. Branche enfant : par qui en a la main (9def0adc). Et
            seulement quand il y a quelque chose à figer — le serveur refusait déjà, mais
            l'écran laissait cliquer (Gael, 25/10/2026). */}
        {!saving && target.canFreeze && (
          <button
            type="button"
            className="btn btn-primary"
            // **Éteint TANT QUE la lecture n'est pas revenue**, et pas seulement quand
            // elle a dit non. Mesuré le 02/11/2026 sur le dépôt de Gael : la route met
            // plus de quatre secondes — elle ouvre la copie tenue et valide tout le
            // paramétrage — et pendant ce temps l'écran offrait un bouton allumé alors
            // que des commits n'étaient pas publiés. Gael en a conclu, à raison de ce
            // qu'il voyait, que sa modification n'était pas détectée.
            disabled={freezable.isPending || (freezable.data !== undefined && !freezable.data.ok)}
            onClick={() => setSaving(true)}
          >
            {t("versions.save")}
          </button>
        )}
      </div>
      {/* Et on DIT qu'on vérifie : un bouton éteint sans un mot se lit comme une panne,
          exactement comme pour les raisons de refus juste en dessous. */}
      {!saving && target.canFreeze && freezable.isPending && (
        <p className="muted" role="status">
          {t("versions.checking")}
        </p>
      )}
      {/* La raison est dite à côté du bouton grisé : un bouton éteint sans explication
          se lit comme une panne. Et quand le geste qui débloque est à portée, il est
          offert ICI — renvoyer vers un autre écran pour un clic est un détour que rien
          ne justifie (Gael, 01/11/2026). */}
      {!saving && target.canFreeze && freezable.data?.reason != null && (
        <p className="muted">{t(`versions.errors.conflict.${freezable.data.reason}`)}</p>
      )}
      {/* **Ce qui ne passe pas les règles, DÈS L'OUVERTURE** (Gael, 01/11/2026 : « il
          faudrait que le message d'erreur arrive avant que j'aie envie de commiter »).
          Jusque-là on ne l'apprenait qu'après avoir cliqué — parfois après avoir publié
          pour rien.

          Affiché même quand la raison est autre : « publiez d'abord » et « ces fichiers
          ne passent pas » sont deux choses, et celui qui publie a le droit de savoir que
          le figement échouera ensuite. */}
      {target.canFreeze && (freezable.data?.reports ?? []).length > 0 && (
        <div className="alert" role="status">
          <p>{t("versions.errors.invalid")}</p>
          <ProblemReports reports={freezable.data?.reports ?? []} />
        </div>
      )}
      {/* **Offert sur la SEULE raison « publication_requise », et c'est ce qui garantit
          que le geste est permis** : le serveur ne rend cette raison que pour une copie
          TENUE par la personne qui regarde et portant des commits locaux. Qui lit ce
          message a donc la main, et peut publier. L'offrir sur les autres raisons
          proposerait un geste que le serveur refuserait.

          Les mêmes mots que dans « Tous les workspaces » (`holds.publish`), et
          volontairement : c'est le même geste, et deux vocabulaires pour une seule action
          en feraient deux dans la tête de qui les lit. */}
      {!saving && target.canFreeze && freezable.data?.reason === "publication_requise" && (
        <div className="actions">
          <button
            type="button"
            className="btn btn-primary"
            disabled={publish.isPending}
            onClick={() => publish.mutate()}
          >
            {t("holds.publish")}
          </button>
        </div>
      )}
      {/* L'accusé est HORS de la condition ci-dessus, et c'est tout l'intérêt : la
          publication réussie efface la raison qui portait le bouton, donc un accusé rangé
          dedans disparaîtrait à l'instant précis où il sert. Trouvé par son test. */}
      {publish.isSuccess && (
        <p className="notice" role="status">
          {t("holds.published", { count: publish.data.published })}
        </p>
      )}
      {publish.isError && <HoldRefusal error={publish.error} />}
      {saving && target.canFreeze && <SaveForm target={target} onDone={() => setSaving(false)} />}
      {versions.isError && <VersionRefusal error={versions.error} />}
      {versions.isSuccess && versions.data.length === 0 && (
        <p className="muted">{t("versions.empty")}</p>
      )}
      {versions.isSuccess && versions.data.length > 0 && (
        <ul className="plain-list">
          {versions.data.map((v) => (
            <VersionRow key={v.number} target={target} version={v} />
          ))}
        </ul>
      )}
    </section>
  );
}
