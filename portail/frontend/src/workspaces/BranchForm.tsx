import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { useCreateBranch, useSetBranchView } from "../api/branches";
import { proposeSlug } from "../api/contracts";
import { ApiError, invalidField } from "../api/http";
import type { Workspace } from "../api/workspaces";

function refusalKey(error: unknown): string {
  const field = invalidField(error);
  if (field !== null) {
    return `branches.errors.field.${field}`;
  }
  if (error instanceof ApiError && typeof error.detail === "object" && error.detail !== null) {
    if ((error.detail as { code?: string }).code === "slug_pris") {
      return "branches.errors.taken";
    }
  }
  if (error instanceof ApiError && typeof error.detail === "string") {
    return `dataModels.errors.conflict.${error.detail}`;
  }
  return "branches.errors.unexpected";
}

/**
 * Nouvelle branche de travail, tirée de la tête de la branche de base (Gael, 22/10/2026).
 * Label saisi, slug proposé d'après lui puis figé : le slug devient `back/<workspace>/<slug>`.
 */
export function BranchForm({
  workspace,
  onDone,
}: {
  workspace: Workspace;
  onDone: (slug: string | null) => void;
}) {
  const { t } = useTranslation();
  const create = useCreateBranch(workspace.id);
  const choose = useSetBranchView(workspace.id);
  const [label, setLabel] = useState("");
  const [slug, setSlug] = useState<string | null>(null);
  // Le slug d'une branche tient en 40 caractères, la limite du nom de branche.
  const shownSlug = slug ?? proposeSlug(label).slice(0, 40).replace(/-+$/, "");
  const by =
    create.error instanceof ApiError && typeof create.error.detail === "object"
      ? String((create.error.detail as { by?: string }).by ?? "")
      : "";

  function submit(event: FormEvent) {
    event.preventDefault();
    // Créée pour y travailler : elle devient la branche regardée, et le menu la nomme.
    create.mutate(
      { label, slug: shownSlug },
      {
        onSuccess: (branch) =>
          choose.mutate(branch.slug, { onSettled: () => onDone(branch.slug) }),
      },
    );
  }

  return (
    // Rendu DANS la carte « Branche de travail », d'où l'absence de `card` ici et le
    // titre de second rang : deux cartes imbriquées empileraient leurs cadres.
    <form onSubmit={submit} aria-label={t("branches.form.title")}>
      <h3>{t("branches.form.title", { name: workspace.name })}</h3>
      <p className="help">{t("branches.form.from", { branch: workspace.work_branch ?? "" })}</p>
      <label className="field">
        {t("branches.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label className="field">
        {t("branches.fields.slug")}
        <input required value={shownSlug} onChange={(e) => setSlug(e.target.value)} />
      </label>
      <p className="help">{t("branches.form.slugHelp", { slug: shownSlug || "…", workspace: workspace.id })}</p>
      {create.isError && (
        <p className="alert" role="alert">
          {t(refusalKey(create.error), { by })}
        </p>
      )}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={create.isPending}>
          {t("branches.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => onDone(null)}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}
