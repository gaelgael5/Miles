import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type ContractVersionDetail,
  type Operation,
  useContract,
  useImportVersion,
  usePreviewContract,
} from "../api/contracts";
import type { WorkTarget } from "../api/workTarget";
import { ContractRefusal } from "./ContractRefusal";
import { ContractSource } from "./ContractSource";

function IntegrateForm({ target, slug }: { target: WorkTarget; slug: string }) {
  const { t } = useTranslation();
  const preview = usePreviewContract(target);
  const save = useImportVersion(target, slug);
  const [content, setContent] = useState("");
  const read = preview.data;

  // Un fichier ou une adresse chargés sont lus aussitôt : ils remplacent le texte et
  // l'aperçu précédents.
  function loaded(text: string) {
    setContent(text);
    save.reset();
    preview.mutate(text);
  }

  function readContract(event: FormEvent) {
    event.preventDefault();
    save.reset();
    preview.mutate(content);
  }

  function integrate() {
    save.mutate(content, {
      onSuccess: () => {
        setContent("");
        preview.reset();
      },
    });
  }

  return (
    <form className="card" onSubmit={readContract} aria-label={t("contracts.integrate.title")}>
      <h2>{t("contracts.integrate.title")}</h2>
      <ContractSource target={target} onContent={loaded} />
      <label className="field">
        {t("contracts.fields.content")}
        <textarea
          required
          rows={12}
          spellCheck={false}
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
      </label>
      <div className="actions">
        <button type="submit" className="btn btn-secondary" disabled={preview.isPending}>
          {t("contracts.integrate.read")}
        </button>
      </div>
      {preview.isError && <ContractRefusal error={preview.error} />}
      {read && (
        <div className="panel">
          <p>
            <strong>{read.title}</strong> · OpenAPI {read.openapi} ·{" "}
            {t("contracts.list.operations", { count: read.operations.length })}
          </p>
          {read.warnings.includes("aucune_operation") && (
            <p className="alert">{t("contracts.warnings.aucune_operation")}</p>
          )}
          {save.isError && <ContractRefusal error={save.error} />}
          <div className="actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={save.isPending}
              onClick={integrate}
            >
              {t("contracts.integrate.submit")}
            </button>
          </div>
        </div>
      )}
      {save.isSuccess && (
        <p className="muted" role="status">
          {t("contracts.integrate.done", { number: save.data.number })}
        </p>
      )}
    </form>
  );
}

function OperationLine({ operation }: { operation: Operation }) {
  return (
    <>
      {operation.method.toUpperCase()} {operation.path}
      {operation.operation_id ? ` — ${operation.operation_id}` : ""}
    </>
  );
}

function VersionRow({ version }: { version: ContractVersionDetail }) {
  const { t, i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const deposited = version.imported_at
    ? t("contracts.versions.deposited", {
        date: new Date(version.imported_at).toLocaleString(i18n.language),
        by: version.imported_by ?? "",
      })
    : t("contracts.versions.outside");
  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">
          v{version.number} — {version.title ?? t("contracts.versions.unreadable")}
        </div>
        <div className="row-sub">{deposited}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("contracts.list.captionOperations")}</div>
        <div className="value">
          {t("contracts.list.operations", { count: version.operations })}{" "}
          {version.warnings.includes("aucune_operation") && (
            <span className="badge badge-warning">{t("contracts.list.noOperation")}</span>
          )}
        </div>
      </div>
      <div className="actions row-actions">
        <button
          type="button"
          className="btn btn-secondary"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
        >
          {t(open ? "dataModels.list.hide" : "contracts.list.showOperations")}
        </button>
      </div>
      {open && (
        <div className="row-detail">
          <ul className="plain-list mono">
            {version.operation_list.map((o) => (
              <li key={`${o.method} ${o.path}`}>
                <OperationLine operation={o} />{" "}
                {o.change === "nouvelle" && (
                  <span className="badge badge-accent">{t("contracts.versions.new")}</span>
                )}{" "}
                {/* Les mappings arrivent avec leur feature : d'ici là, rien ne couvre une opération. */}
                <span className="badge badge-warning">{t("contracts.versions.unmapped")}</span>
              </li>
            ))}
          </ul>
          {version.removed.length > 0 && (
            <>
              <p className="caption">
                {t("contracts.versions.removed", { number: version.compared_with })}
              </p>
              <ul className="plain-list mono muted">
                {version.removed.map((o) => (
                  <li key={`${o.method} ${o.path}`}>
                    <OperationLine operation={o} />
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </li>
  );
}

/** Un contrat déclaré : on y intègre les fichiers du tiers, chacun en nouvelle version. */
export function ContractScreen({
  target,
  slug,
  onBack,
}: {
  target: WorkTarget;
  slug: string;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const contract = useContract(target, slug);
  const detail = contract.data;

  return (
    <section aria-labelledby="contract-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("contracts.back")}
      </button>
      {contract.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {contract.isError && <ContractRefusal error={contract.error} />}
      {detail && (
        <>
          <div className="page-head">
            <div>
              <h1 id="contract-title">{detail.label}</h1>
              <p className="lead">
                <span className="mono">contracts/{detail.slug}</span> ·{" "}
                <span className="badge badge-accent">{t(`contracts.sens.${detail.sens}`)}</span>
              </p>
            </div>
          </div>
          <IntegrateForm target={target} slug={detail.slug} />
          <h2>{t("contracts.versions.title")}</h2>
          {detail.versions.length === 0 ? (
            <p className="muted">{t("contracts.versions.empty")}</p>
          ) : (
            <ul className="card-list plain-list">
              {detail.versions.map((v) => (
                <VersionRow key={v.number} version={v} />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
