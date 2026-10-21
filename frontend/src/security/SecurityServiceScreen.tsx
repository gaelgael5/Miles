import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { PageHead } from "../layout/PageHead";
import { invalidField } from "../api/http";
import {
  type SecurityInput,
  type SecurityService,
  useDeclareSecurityService,
  useSecurityServices,
  useUpdateSecurityService,
  useVerifySecurityService,
} from "../api/security";
import { SecretPicker } from "../secrets/SecretPicker";

const EMPTY: SecurityInput = { base_url: "", realm: "", client_id: "", client_secret_slug: "" };

function errorKey(error: unknown): string {
  const field = invalidField(error);
  return field === null ? "security.errors.unexpected" : `security.errors.invalid.${field}`;
}

interface FormProps {
  service?: SecurityService;
  onDone: () => void;
}

/** Déclaration ou correction des coordonnées ; remonté par `key` à chaque ouverture. */
function SecurityForm({ service, onDone }: FormProps) {
  const { t } = useTranslation();
  const declare = useDeclareSecurityService();
  const update = useUpdateSecurityService(service?.id ?? "");
  const save = service ? update : declare;
  const [id, setId] = useState("racine");
  const [draft, setDraft] = useState<SecurityInput>(
    service
      ? {
          base_url: service.base_url,
          realm: service.realm,
          client_id: service.client_id,
          client_secret_slug: service.client_secret_slug,
        }
      : EMPTY,
  );
  const [confirmed, setConfirmed] = useState(false);
  // Changer les coordonnées touche les terminaux enrôlés : on avertit avant de valider.
  const dependents = service?.dependent_installations ?? 0;
  const needsConfirmation = dependents > 0 && !confirmed;

  function set(key: keyof SecurityInput, value: string) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const done = { onSuccess: onDone };
    if (service) {
      update.mutate(draft, done);
    } else {
      declare.mutate({ id, ...draft }, done);
    }
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t(service ? "security.form.editTitle" : "security.form.newTitle")}>
      {!service && (
        <label className="field">
          {t("security.fields.id")}
          <input required value={id} onChange={(e) => setId(e.target.value)} />
        </label>
      )}
      <label className="field">
        {t("security.fields.baseUrl")}
        <input
          required
          type="url"
          placeholder="https://security.example.org"
          value={draft.base_url}
          onChange={(e) => set("base_url", e.target.value)}
        />
      </label>
      <label className="field">
        {t("security.fields.realm")}
        <input required value={draft.realm} onChange={(e) => set("realm", e.target.value)} />
      </label>
      <label className="field">
        {t("security.fields.clientId")}
        <input required value={draft.client_id} onChange={(e) => set("client_id", e.target.value)} />
      </label>
      <SecretPicker
        label={t("security.fields.clientSecret")}
        secretType="SECURITY_SERVICE_CLIENT_SECRET"
        value={draft.client_secret_slug || null}
        onChange={(slug) => set("client_secret_slug", slug ?? "")}
      />
      {dependents > 0 && (
        <label className="field-check alert" role="alert">
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
          {t("security.form.dependents", { count: dependents })}
        </label>
      )}
      {save.isError && <p className="alert" role="alert">{t(errorKey(save.error))}</p>}
      <div className="actions">
      <button
        type="submit"
        className="btn btn-primary"
        disabled={save.isPending || needsConfirmation || draft.client_secret_slug === ""}
      >
        {t("security.form.save")}
      </button>
      {service && (
        <button type="button" className="btn btn-secondary" onClick={onDone}>
          {t("security.form.cancel")}
        </button>
      )}
      </div>
    </form>
  );
}

function ServiceCard({ service }: { service: SecurityService }) {
  const { t } = useTranslation();
  const verify = useVerifySecurityService(service.id);
  const [editing, setEditing] = useState(false);
  const outcome = service.last_check_outcome;

  if (editing) {
    return <SecurityForm service={service} onDone={() => setEditing(false)} />;
  }
  return (
    <div className="card">
      <div className="row-title">{service.id}</div>
      <div className="row-sub">
        {service.kind} · {service.base_url}
      </div>
      <div className="row">
        <div className="cell">
          <div className="caption">{t("security.fields.realm")}</div>
          <div className="value mono">{service.realm}</div>
        </div>
        <div className="cell">
          <div className="caption">{t("security.fields.clientId")}</div>
          <div className="value mono">{service.client_id}</div>
        </div>
        <div className="cell">
          <div className="caption">{t("security.fields.clientSecret")}</div>
          <div className="value">{t("security.secretBy", { slug: service.client_secret_slug })}</div>
        </div>
      </div>
      {/* La panne la plus structurante du dispositif : nommée, reconnaissable d'emblée. */}
      <p
        className={outcome === "ok" ? "notice" : "alert"}
        role={outcome !== null && outcome !== "ok" ? "alert" : "status"}
      >
        {t(outcome === null ? "security.outcomes.unchecked" : `security.outcomes.${outcome}`, {
          id: service.id,
        })}
      </p>
      <div className="actions">
        <button type="button" className="btn btn-primary" disabled={verify.isPending} onClick={() => verify.mutate(undefined)}>
          {t("security.verify")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={() => setEditing(true)}>
          {t("security.edit")}
        </button>
      </div>
    </div>
  );
}

/** Service de sécurité racine : un seul pour l'instant, référencé ensuite par les workspaces. */
export function SecurityServiceScreen() {
  const { t } = useTranslation();
  const services = useSecurityServices();

  return (
    <section aria-labelledby="security-title">
      <PageHead id="security-title" title={t("security.title")} lead={t("security.intro")} />
      {services.isPending && <p className="muted" role="status">{t("security.loading")}</p>}
      {services.isError && <p className="alert" role="alert">{t("security.errors.unreachable")}</p>}
      {services.isSuccess && services.data.length === 0 && (
        <SecurityForm key="new" onDone={() => undefined} />
      )}
      {services.data?.map((service) => <ServiceCard key={service.id} service={service} />)}
    </section>
  );
}
