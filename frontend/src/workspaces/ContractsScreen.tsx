import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type Contract,
  type Direction,
  useContract,
  useContracts,
  useImportContract,
  usePreviewContract,
} from "../api/contracts";
import type { Workspace } from "../api/workspaces";
import { ContractRefusal } from "./ContractRefusal";
import { ContractSource } from "./ContractSource";

function ImportForm({ workspaceId, onDone }: { workspaceId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const preview = usePreviewContract(workspaceId);
  const save = useImportContract(workspaceId);
  const [content, setContent] = useState("");
  // Le slug proposé se modifie ici, et seulement ici : il est figé une fois importé.
  const [slug, setSlug] = useState<string | null>(null);
  const [sens, setSens] = useState<Direction | null>(null);
  const read = preview.data;
  const shownSlug = slug ?? read?.slug ?? "";

  function readContract(event: FormEvent) {
    event.preventDefault();
    setSlug(null);
    preview.mutate(content);
  }

  // Un fichier ou une adresse chargés sont lus aussitôt : ils remplacent le texte et
  // l'aperçu précédents, slug proposé compris.
  function loaded(text: string) {
    setContent(text);
    setSlug(null);
    preview.mutate(text);
  }

  function submit() {
    if (sens !== null) {
      save.mutate({ slug: shownSlug, sens, content }, { onSuccess: onDone });
    }
  }

  return (
    <form className="card" onSubmit={readContract} aria-label={t("contracts.form.title")}>
      <h2>{t("contracts.form.title")}</h2>
      <ContractSource workspaceId={workspaceId} onContent={loaded} />
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
          {t("contracts.form.read")}
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
          <label className="field">
            {t("contracts.fields.slug")}
            <input required value={shownSlug} onChange={(e) => setSlug(e.target.value)} />
          </label>
          <p className="help">{t("contracts.form.slugHelp")}</p>
          <fieldset>
            <legend>{t("contracts.fields.sens")}</legend>
            {(["sortant", "entrant"] as const).map((value) => (
              <label key={value} className="choice">
                <input
                  type="radio"
                  name="sens"
                  checked={sens === value}
                  onChange={() => setSens(value)}
                />
                {t(`contracts.sens.${value}`)}
              </label>
            ))}
          </fieldset>
          {save.isError && <ContractRefusal error={save.error} />}
          <div className="actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={save.isPending || sens === null}
              onClick={submit}
            >
              {t("contracts.form.submit")}
            </button>
          </div>
        </div>
      )}
      <div className="actions">
        <button type="button" className="btn btn-secondary" onClick={onDone}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}

function ContractRow({ workspaceId, contract }: { workspaceId: string; contract: Contract }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const detail = useContract(workspaceId, open ? contract.slug : null);

  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{contract.title}</div>
        <div className="row-sub mono">contracts/{contract.slug}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("contracts.list.captionSens")}</div>
        <div className="value">
          <span className="badge badge-accent">{t(`contracts.sens.${contract.sens}`)}</span>
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("contracts.list.captionOperations")}</div>
        <div className="value">
          {t("contracts.list.operations", { count: contract.operations })}{" "}
          {contract.warnings.includes("aucune_operation") && (
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
      {open && detail.data && (
        <ul className="row-detail plain-list mono">
          {detail.data.operation_list.map((o) => (
            <li key={`${o.method} ${o.path}`}>
              {o.method.toUpperCase()} {o.path}
              {o.operation_id ? ` — ${o.operation_id}` : ""}
            </li>
          ))}
        </ul>
      )}
      {detail.isError && (
        <div className="row-detail">
          <ContractRefusal error={detail.error} />
        </div>
      )}
    </li>
  );
}

/** Contrats OpenAPI du workspace : importés depuis les tiers, jamais édités. */
export function ContractsScreen({ workspace, onBack }: { workspace: Workspace; onBack: () => void }) {
  const { t } = useTranslation();
  const contracts = useContracts(workspace.id);
  const [importing, setImporting] = useState(false);

  return (
    <section aria-labelledby="contracts-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="contracts-title">{t("contracts.title", { name: workspace.name })}</h1>
          <p className="lead">{t("contracts.intro")}</p>
        </div>
        {!importing && (
          <button type="button" className="btn btn-primary" onClick={() => setImporting(true)}>
            {t("contracts.add")}
          </button>
        )}
      </div>
      {importing && <ImportForm workspaceId={workspace.id} onDone={() => setImporting(false)} />}
      {contracts.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {contracts.isError && <ContractRefusal error={contracts.error} />}
      {contracts.isSuccess && contracts.data.length === 0 && (
        <p className="muted">{t("contracts.empty")}</p>
      )}
      {contracts.isSuccess && contracts.data.length > 0 && (
        <ul className="card-list plain-list">
          {contracts.data.map((c) => (
            <ContractRow key={c.slug} workspaceId={workspace.id} contract={c} />
          ))}
        </ul>
      )}
    </section>
  );
}
