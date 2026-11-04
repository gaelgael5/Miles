import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, ConfirmDialog } from "@miles/socle-web";
import {
  useAddWorkspaceCulture,
  useRemoveWorkspaceCulture,
  useSetDefaultWorkspaceCulture,
  useWorkspaceCultures,
} from "../api/workspaceCultures";
import { CulturePicker } from "./CulturePicker";

interface Incomplete {
  culture: string;
  missing: number;
}

/** Le refus propre au changement de culture par défaut porte le NOMBRE de clés manquantes. */
function incomplete(error: unknown): Incomplete | null {
  if (error instanceof ApiError && error.status === 409) {
    const detail = error.detail as { code?: string; culture?: string; missing?: number };
    if (detail?.code === "culture_defaut_incomplete") {
      return { culture: detail.culture ?? "", missing: detail.missing ?? 0 };
    }
  }
  return null;
}

/** Un fichier de `trads/` illisible n'est pas un travail de traduction : c'est à corriger. */
function unreadable(error: unknown): string | null {
  if (error instanceof ApiError && error.status === 422) {
    const detail = error.detail as { code?: string; path?: string };
    if (detail?.code === "trads_illisible") {
      return detail.path ?? "";
    }
  }
  return null;
}

function errorKey(error: unknown): string {
  if (error instanceof ApiError && error.status === 422) {
    const detail = error.detail as { field?: string; reason?: string };
    if (detail?.reason === "inconnue") {
      return "workspaceCultures.errors.unknown";
    }
    if (detail?.reason === "forme") {
      return "workspaceCultures.errors.shape";
    }
  }
  return "workspaceCultures.errors.unexpected";
}

function Refusal({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const incomplete_ = incomplete(error);
  const path = unreadable(error);
  if (incomplete_ !== null) {
    return (
      <p className="alert" role="alert">
        {t("workspaceCultures.errors.incomplete", {
          culture: incomplete_.culture,
          missing: incomplete_.missing,
        })}
      </p>
    );
  }
  if (path !== null) {
    return (
      <p className="alert" role="alert">
        {t("workspaceCultures.errors.unreadable", { path })}
      </p>
    );
  }
  return (
    <p className="alert" role="alert">
      {t(errorKey(error))}
    </p>
  );
}

function AddForm({ workspaceId, taken }: { workspaceId: string; taken: readonly string[] }) {
  const { t } = useTranslation();
  const add = useAddWorkspaceCulture(workspaceId);
  const [culture, setCulture] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate(culture, { onSuccess: () => setCulture("") });
  }

  return (
    <form onSubmit={submit} aria-label={t("workspaceCultures.addTitle")}>
      <h3>{t("workspaceCultures.addTitle")}</h3>
      <CulturePicker
        label={t("workspaceCultures.additional")}
        value={culture}
        exclude={taken}
        onChange={setCulture}
      />
      {add.isError && <Refusal error={add.error} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={add.isPending || !culture}>
          {t("workspaceCultures.add")}
        </button>
      </div>
    </form>
  );
}

/**
 * Les deux réglages dont le référentiel de traductions dépend entièrement (story 639c25da).
 *
 * La culture par défaut est celle dont la valeur sera EXIGÉE sur chaque clé ; les
 * additionnelles sont facultatives. `en-US` n'a aucun rôle ici — c'est le repli de l'i18n
 * du back-office, pas celui du paramétrage d'un workspace.
 */
export function WorkspaceCulturesCard({ workspaceId }: { workspaceId: string }) {
  const { t } = useTranslation();
  const cultures = useWorkspaceCultures(workspaceId);
  const promote = useSetDefaultWorkspaceCulture(workspaceId);
  const remove = useRemoveWorkspaceCulture(workspaceId);
  const [removing, setRemoving] = useState<string | null>(null);
  const additional = cultures.data?.additional ?? [];

  return (
    <div className="card">
      <h2>{t("workspaceCultures.title")}</h2>
      <p className="muted">{t("workspaceCultures.intro")}</p>
      {cultures.isError && (
        <p className="alert" role="alert">
          {t("workspaceCultures.errors.unreachable")}
        </p>
      )}
      {cultures.isSuccess && (
        <ul className="card-list plain-list">
          <li className="row">
            <div className="row-main">
              <code>{cultures.data.default}</code>
              <div className="row-sub">{t("workspaceCultures.defaultNote")}</div>
            </div>
            <span className="badge badge-accent">{t("workspaceCultures.isDefault")}</span>
          </li>
          {additional.map((culture) => (
            <li className="row" key={culture}>
              <div className="row-main">
                <code>{culture}</code>
              </div>
              <div className="actions">
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={promote.isPending}
                  onClick={() => promote.mutate(culture)}
                >
                  {t("workspaceCultures.promote")}
                </button>
                <button
                  type="button"
                  className="btn btn-danger"
                  onClick={() => setRemoving(culture)}
                >
                  {t("workspaceCultures.remove")}
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {promote.isError && <Refusal error={promote.error} />}
      {remove.isError && <Refusal error={remove.error} />}
      <AddForm workspaceId={workspaceId} taken={[cultures.data?.default ?? "", ...additional]} />
      {removing !== null && (
        <ConfirmDialog
          title={t("workspaceCultures.removeTitle")}
          confirmLabel={t("workspaceCultures.remove")}
          cancelLabel={t("workspaceCultures.cancel")}
          onCancel={() => setRemoving(null)}
          onConfirm={() => {
            remove.mutate(removing);
            setRemoving(null);
          }}
        >
          {/* Dire AVANT de confirmer que les fichiers restent (critère 7) : sans ça, le
              geste se lit comme une destruction du travail de traduction. */}
          <p>{t("workspaceCultures.removeConfirm", { culture: removing })}</p>
          <p className="muted">{t("workspaceCultures.filesKept")}</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
