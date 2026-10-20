import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/http";
import { type Connector, type ConnectorInput, DEFAULT_SCOPES, useSaveConnector } from "../api/oidc";
import { SecretPicker } from "../secrets/SecretPicker";

interface ConnectorFormProps {
  /** Connecteur modifié ; absent pour une création. Le formulaire est remonté par `key`. */
  connector?: Connector;
  onDone: () => void;
}

const EMPTY: ConnectorInput = {
  id: "",
  label: "",
  issuer: "",
  client_id: "",
  client_secret_slug: "",
  scopes: DEFAULT_SCOPES,
  active: true,
  groups_claim: "groups",
  display_name_claim: "name",
  // Décochées d'office : chacune accorde un pouvoir (décision du 19/10/2026).
  recognize_admin: false,
  manage_associations: false,
};

/** Seuls les champs saisissables repartent vers l'API, qui refuse tout champ en trop. */
function toInput(connector: Connector): ConnectorInput {
  const { id, label, issuer, client_id, client_secret_slug, scopes, active } = connector;
  const { groups_claim, display_name_claim, recognize_admin, manage_associations } = connector;
  return {
    id,
    label,
    issuer,
    client_id,
    client_secret_slug,
    scopes,
    active,
    groups_claim,
    display_name_claim,
    recognize_admin,
    manage_associations,
  };
}

function errorKey(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = error.detail as { field?: string; reason?: string } | string | undefined;
    if (typeof detail === "object" && detail.reason === "injoignable") {
      return "oidc.errors.issuerUnreachable";
    }
    if (typeof detail === "object" && detail.field) {
      return `oidc.errors.invalid.${detail.field}`;
    }
    if (detail === "identifiant_pris") {
      return "oidc.errors.idTaken";
    }
  }
  return "oidc.errors.unexpected";
}

export function ConnectorForm({ connector, onDone }: ConnectorFormProps) {
  const { t } = useTranslation();
  const save = useSaveConnector(connector !== undefined);
  const [draft, setDraft] = useState<ConnectorInput>(connector ? toInput(connector) : EMPTY);

  function set<K extends keyof ConnectorInput>(key: K, value: ConnectorInput[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate(draft, { onSuccess: onDone });
  }

  return (
    <form onSubmit={submit} aria-label={t(connector ? "oidc.form.editTitle" : "oidc.form.newTitle")}>
      {connector === undefined && (
        <label>
          {t("oidc.fields.id")}
          <input required value={draft.id} onChange={(e) => set("id", e.target.value)} />
        </label>
      )}
      <label>
        {t("oidc.fields.label")}
        <input required value={draft.label} onChange={(e) => set("label", e.target.value)} />
      </label>
      <label>
        {t("oidc.fields.issuer")}
        <input
          required
          type="url"
          placeholder="https://security.example.org/realms/miles"
          value={draft.issuer}
          onChange={(e) => set("issuer", e.target.value)}
        />
      </label>
      <label>
        {t("oidc.fields.clientId")}
        <input required value={draft.client_id} onChange={(e) => set("client_id", e.target.value)} />
      </label>
      <SecretPicker
        label={t("oidc.fields.clientSecret")}
        secretType="OIDC_CLIENT_SECRET"
        value={draft.client_secret_slug || null}
        onChange={(slug) => set("client_secret_slug", slug ?? "")}
      />
      <label>
        {t("oidc.fields.scopes")}
        <input required value={draft.scopes} onChange={(e) => set("scopes", e.target.value)} />
      </label>
      <label>
        {t("oidc.fields.groupsClaim")}
        <input
          required
          value={draft.groups_claim}
          onChange={(e) => set("groups_claim", e.target.value)}
        />
      </label>
      <label>
        {t("oidc.fields.displayNameClaim")}
        <input
          required
          value={draft.display_name_claim}
          onChange={(e) => set("display_name_claim", e.target.value)}
        />
      </label>
      {/* Chaque case dit ce qu'elle accorde, pas seulement son nom (critère 6 de 02891f10). */}
      <label>
        <input
          type="checkbox"
          checked={draft.recognize_admin}
          onChange={(e) => set("recognize_admin", e.target.checked)}
        />
        {t("oidc.fields.recognizeAdmin")}
      </label>
      <p>{t("oidc.form.recognizeAdminGrants")}</p>
      <label>
        <input
          type="checkbox"
          checked={draft.manage_associations}
          onChange={(e) => set("manage_associations", e.target.checked)}
        />
        {t("oidc.fields.manageAssociations")}
      </label>
      <p>{t("oidc.form.manageAssociationsGrants")}</p>
      <label>
        <input
          type="checkbox"
          checked={draft.active}
          onChange={(e) => set("active", e.target.checked)}
        />
        {t("oidc.fields.active")}
      </label>
      <p>{t("oidc.form.checkedOnSave")}</p>
      {save.isError && <p role="alert">{t(errorKey(save.error))}</p>}
      <button type="submit" disabled={save.isPending || draft.client_secret_slug === ""}>
        {t("oidc.form.save")}
      </button>
      <button type="button" onClick={onDone}>
        {t("oidc.form.cancel")}
      </button>
    </form>
  );
}
