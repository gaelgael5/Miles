import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { type ContractVersionDetail, type Operation, useContract } from "../api/contracts";
import type { WorkTarget } from "../api/workTarget";
import { useSaveShortcut } from "../layout/useSaveShortcut";
import { ContractDelete } from "./ContractDelete";
import { ContractRefusal } from "./ContractRefusal";
import { ContractSource } from "./ContractSource";
import { type Integration, useIntegration } from "./contractIntegration";

function IntegrateForm({
  target,
  integration,
  onClose,
}: {
  target: WorkTarget;
  integration: Integration;
  // Absent : contrat sans version, le bloc reste ouvert, rien à fermer.
  onClose?: () => void;
}) {
  const { t } = useTranslation();
  const { preview, save, content, read } = integration;

  function readContract(event: FormEvent) {
    event.preventDefault();
    integration.readContent();
  }

  return (
    <form className="card" onSubmit={readContract} aria-label={t("contracts.integrate.title")}>
      <h2>{t("contracts.integrate.title")}</h2>
      <ContractSource target={target} onContent={integration.load} />
      <label className="field">
        {t("contracts.fields.content")}
        <textarea
          required
          rows={12}
          spellCheck={false}
          value={content}
          onChange={(e) => integration.setContent(e.target.value)}
        />
      </label>
      <div className="actions">
        <button type="submit" className="btn btn-secondary" disabled={preview.isPending}>
          {t("contracts.integrate.read")}
        </button>
        {onClose && (
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            {t("contracts.integrate.close")}
          </button>
        )}
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
          {/* « Intégrer » est en haut à droite de la page, comme Ctrl+S (caad743d). */}
          <p className="help">{t("contracts.integrate.where")}</p>
        </div>
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
  const [integrating, setIntegrating] = useState(false);
  const [integrated, setIntegrated] = useState<number | null>(null);
  // Contrat déjà intégré : ses opérations d'abord, l'intégration derrière un bouton
  // (Gael, 23/10/2026). Sans version, rien à lire : le bloc reste ouvert d'emblée.
  const hasVersions = (detail?.versions.length ?? 0) > 0;
  const showForm = !target.readOnly && (!hasVersions || integrating);
  const integration = useIntegration(target, slug, (number) => {
    setIntegrated(number);
    setIntegrating(false);
  });
  useSaveShortcut(showForm ? integration.shortcut : null);

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
            {/* Comme toute modification : sur une branche enfant dont on a la main. */}
            {showForm && (
              <button
                type="button"
                className="btn btn-primary"
                disabled={integration.read === null || integration.busy}
                title={t("dataModels.editor.saveShortcut")}
                onClick={integration.integrate}
              >
                {t("contracts.integrate.submit")}
              </button>
            )}
            {!target.readOnly && hasVersions && !integrating && (
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => {
                  setIntegrated(null);
                  setIntegrating(true);
                }}
              >
                {t("contracts.integrate.open")}
              </button>
            )}
            {!target.readOnly && (
              <ContractDelete
                target={target}
                slug={detail.slug}
                versions={detail.versions.length}
                onDeleted={onBack}
              />
            )}
          </div>
          {integrated !== null && (
            <p className="notice" role="status">
              {t("contracts.integrate.done", { number: integrated })}
            </p>
          )}
          {showForm && (
            <IntegrateForm
              target={target}
              integration={integration}
              onClose={
                hasVersions
                  ? () => {
                      // Fermé, le bloc oublie le texte : rouvert, il repart à vide.
                      integration.clear();
                      setIntegrating(false);
                    }
                  : undefined
              }
            />
          )}
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
