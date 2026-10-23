import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { DOMAIN_NAME_RE, type Domain, useAddDomain } from "../api/domains";
import type { WorkTarget } from "../api/workTarget";
import { ModelRefusal } from "./ModelRefusal";

/**
 * Ajout d'un domaine (story 7fa00f56) : un modèle ne crée plus son domaine au passage,
 * où une faute de frappe en faisait naître un nouveau. Le nom est refusé en direct, et
 * le serveur le revérifie.
 */
export function DomainForm({
  target,
  onAdded,
  onCancel,
}: {
  target: WorkTarget;
  onAdded: (domain: Domain) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const add = useAddDomain(target);
  const [name, setName] = useState("");
  const valid = DOMAIN_NAME_RE.test(name);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (valid) add.mutate(name, { onSuccess: onAdded });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("dataModels.domainForm.title")}>
      <h2>{t("dataModels.domainForm.title")}</h2>
      <label className="field">
        {t("dataModels.domainForm.name")}
        <input
          required
          className="mono"
          value={name}
          aria-invalid={name !== "" && !valid}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <p className="help">{t("dataModels.domainForm.help")}</p>
      {name !== "" && !valid && (
        <p className="alert" role="alert">
          {t("dataModels.errors.invalid.domain")}
        </p>
      )}
      {add.isError && (
        <ModelRefusal error={add.error} fields={{ name: "dataModels.errors.invalid.domain" }} />
      )}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={!valid || add.isPending}>
          {t("dataModels.domainForm.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}
