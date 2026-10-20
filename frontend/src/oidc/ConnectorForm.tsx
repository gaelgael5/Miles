import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { type Culture, useActiveCultures } from "../api/cultures";
import { ApiError } from "../api/http";
import { type Connector, type ConnectorInput, DEFAULT_SCOPES, useSaveConnector } from "../api/oidc";
import { SecretPicker } from "../secrets/SecretPicker";

interface ConnectorFormProps {
  /** Connecteur modifié ; absent pour une création. Le formulaire est remonté par `key`. */
  connector?: Connector;
  /** Les autres connecteurs : deux boutons au même libellé se signalent (critère 9). */
  others: Connector[];
  onDone: () => void;
}

const FALLBACK = "en-US";

function sameLabel(a: string | undefined, b: string): boolean {
  return a !== undefined && a.trim() !== "" && a.trim().toLowerCase() === b.trim().toLowerCase();
}

const EMPTY: ConnectorInput = {
  id: "",
  labels: { [FALLBACK]: "" },
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
  const { id, labels, issuer, client_id, client_secret_slug, scopes, active } = connector;
  const { groups_claim, display_name_claim, recognize_admin, manage_associations } = connector;
  return {
    id,
    labels: { ...labels },
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

function LabelField({
  culture,
  value,
  duplicate,
  onChange,
}: {
  culture: Culture;
  value: string;
  duplicate: boolean;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  const fallback = culture.code === FALLBACK;
  return (
    <>
      <label>
        {t("oidc.fields.labelIn", { culture: `${culture.code} — ${culture.label_native}` })}
        {fallback && ` ${t("oidc.form.fallbackLabel")}`}
        <input required={fallback} value={value} onChange={(e) => onChange(e.target.value)} />
      </label>
      {duplicate && <p role="status">{t("oidc.form.duplicateLabel", { culture: culture.code })}</p>}
    </>
  );
}

export function ConnectorForm({ connector, others, onDone }: ConnectorFormProps) {
  const { t } = useTranslation();
  const save = useSaveConnector(connector !== undefined);
  // Seules les cultures actives se saisissent ; en-US d'abord, c'est le repli.
  const cultures = [...(useActiveCultures().data ?? [])].sort(
    (a, b) => Number(b.code === FALLBACK) - Number(a.code === FALLBACK),
  );
  const [draft, setDraft] = useState<ConnectorInput>(connector ? toInput(connector) : EMPTY);

  function set<K extends keyof ConnectorInput>(key: K, value: ConnectorInput[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function setLabel(culture: string, value: string) {
    setDraft((current) => ({ ...current, labels: { ...current.labels, [culture]: value } }));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    // N'envoyer que les cultures actives : celles désactivées gardent leurs libellés,
    // que le serveur ne touche pas tant qu'on ne les lui envoie pas.
    const labels = Object.fromEntries(
      cultures.map((culture) => [culture.code, draft.labels[culture.code] ?? ""]),
    );
    save.mutate({ ...draft, labels }, { onSuccess: onDone });
  }

  return (
    <form onSubmit={submit} aria-label={t(connector ? "oidc.form.editTitle" : "oidc.form.newTitle")}>
      {connector === undefined && (
        <label>
          {t("oidc.fields.id")}
          <input required value={draft.id} onChange={(e) => set("id", e.target.value)} />
        </label>
      )}
      <fieldset>
        <legend>{t("oidc.fields.label")}</legend>
        {cultures.map((culture) => (
          <LabelField
            key={culture.code}
            culture={culture}
            value={draft.labels[culture.code] ?? ""}
            duplicate={others.some((o) =>
              sameLabel(o.labels[culture.code], draft.labels[culture.code] ?? ""),
            )}
            onChange={(value) => setLabel(culture.code, value)}
          />
        ))}
      </fieldset>
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
