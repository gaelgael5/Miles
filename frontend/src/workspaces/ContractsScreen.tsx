import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type Contract,
  type Direction,
  proposeSlug,
  useContracts,
  useDeclareContract,
} from "../api/contracts";
import type { WorkTarget } from "../api/workTarget";
import type { Workspace } from "../api/workspaces";
import { ContractRefusal } from "./ContractRefusal";

function DeclareForm({
  target,
  onDeclared,
  onCancel,
}: {
  target: WorkTarget;
  onDeclared: (slug: string) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const declare = useDeclareContract(target);
  const [label, setLabel] = useState("");
  // Le slug suit le label tant qu'on ne l'a pas touché ; modifiable ici seulement, il est
  // figé une fois le contrat déclaré.
  const [slug, setSlug] = useState<string | null>(null);
  const [sens, setSens] = useState<Direction | null>(null);
  const shownSlug = slug ?? proposeSlug(label);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (sens !== null) {
      declare.mutate(
        { label, slug: shownSlug, sens },
        { onSuccess: (contract) => onDeclared(contract.slug) },
      );
    }
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("contracts.form.title")}>
      <h2>{t("contracts.form.title")}</h2>
      <label className="field">
        {t("contracts.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
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
      {declare.isError && <ContractRefusal error={declare.error} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={declare.isPending || sens === null}>
          {t("contracts.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}

function ContractRow({ contract, onOpen }: { contract: Contract; onOpen: () => void }) {
  const { t } = useTranslation();
  const latest = contract.versions.at(-1);
  return (
    <li className="row">
      <div className="row-main">
        <div className="row-title">{contract.label}</div>
        <div className="row-sub mono">contracts/{contract.slug}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("contracts.list.captionSens")}</div>
        <div className="value">
          <span className="badge badge-accent">{t(`contracts.sens.${contract.sens}`)}</span>
        </div>
      </div>
      <div className="cell">
        <div className="caption">{t("contracts.list.captionVersions")}</div>
        <div className="value">
          {latest === undefined ? (
            <span className="badge badge-warning">{t("contracts.list.noFile")}</span>
          ) : (
            t("contracts.list.versions", { count: contract.versions.length, latest: latest.number })
          )}
        </div>
      </div>
      <div className="actions row-actions">
        <button type="button" className="btn btn-secondary" onClick={onOpen}>
          {t("contracts.list.open")}
        </button>
      </div>
    </li>
  );
}

/** Contrats OpenAPI du workspace : déclarés ici, puis alimentés par les fichiers du tiers. */
export function ContractsScreen({
  workspace,
  target,
  onBack,
  onOpen,
}: {
  workspace: Workspace;
  target: WorkTarget;
  onBack: () => void;
  onOpen: (slug: string) => void;
}) {
  const { t } = useTranslation();
  const contracts = useContracts(target);
  const [declaring, setDeclaring] = useState(false);

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
        {!declaring && !target.readOnly && (
          <button type="button" className="btn btn-primary" onClick={() => setDeclaring(true)}>
            {t("contracts.add")}
          </button>
        )}
      </div>
      {declaring && (
        <DeclareForm
          target={target}
          onDeclared={onOpen}
          onCancel={() => setDeclaring(false)}
        />
      )}
      {contracts.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {contracts.isError && <ContractRefusal error={contracts.error} />}
      {contracts.isSuccess && contracts.data.length === 0 && (
        <p className="muted">{t("contracts.empty")}</p>
      )}
      {contracts.isSuccess && contracts.data.length > 0 && (
        <ul className="card-list plain-list">
          {contracts.data.map((c) => (
            <ContractRow key={c.slug} contract={c} onOpen={() => onOpen(c.slug)} />
          ))}
        </ul>
      )}
    </section>
  );
}
