import { useTranslation } from "react-i18next";

import {
  type Contract,
  type ContractVersion,
  type DerivedRef,
  type Direction,
  useContracts,
  useRederive,
} from "../api/contracts";
import type { WorkTarget } from "../api/workTarget";
import type { Workspace } from "../api/workspaces";
import { ContractRefusal } from "./ContractRefusal";

function VersionModels({
  target,
  contract,
  version,
  onOpen,
}: {
  target: WorkTarget;
  contract: Contract;
  version: ContractVersion;
  onOpen: (ref: DerivedRef) => void;
}) {
  const { t } = useTranslation();
  const rederive = useRederive(target, contract.slug);
  const stale = version.models_state === "a_rederiver";
  return (
    <section className="contract-models" aria-label={`${contract.label} v${version.number}`}>
      <div className="page-head">
        <div>
          <h2>
            {contract.label} · v{version.number}
          </h2>
          <p className="lead mono">contracts/{contract.slug}/models/v{version.number}</p>
        </div>
        {/* Le contrat fait foi : des modèles absents ou retouchés se réécrivent d'après lui. */}
        {stale && !target.readOnly && (
          <div className="actions">
            <button
              type="button"
              className="btn btn-primary"
              disabled={rederive.isPending}
              onClick={() => rederive.mutate(version.number)}
            >
              {t("contractModels.rederive")}
            </button>
          </div>
        )}
      </div>
      {stale && <p className="alert">{t("contractModels.stale")}</p>}
      {version.models_state === "non_derivable" && (
        <p className="alert">{t("contractModels.underivable")}</p>
      )}
      {rederive.isError && <ContractRefusal error={rederive.error} />}
      {version.models.length === 0 ? (
        <p className="muted">{t("contractModels.noSchema")}</p>
      ) : (
        <ul className="card-list plain-list">
          {version.models.map((name) => (
            <li key={name} className="row row-openable">
              <div className="row-main">
                <button
                  type="button"
                  className="row-title row-open"
                  onClick={() => onOpen({ slug: contract.slug, version: version.number, name })}
                >
                  {name}
                </button>
                <div className="row-sub mono">
                  contracts/{contract.slug}/models/v{version.number}/{name}.yaml
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ContractRow({ contract, onOpen }: { contract: Contract; onOpen: () => void }) {
  const { t } = useTranslation();
  const models = contract.versions.reduce((count, v) => count + v.models.length, 0);
  return (
    <li className="row row-openable">
      <div className="row-main">
        <button type="button" className="row-title row-open" onClick={onOpen}>
          {contract.label}
        </button>
        <div className="row-sub mono">contracts/{contract.slug}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("contracts.list.captionVersions")}</div>
        <div className="value">{contract.versions.length}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("contractModels.captionModels")}</div>
        <div className="value">{models}</div>
      </div>
    </li>
  );
}

/**
 * Modèles dérivés des contrats d'un sens (story 47f55d8b), un par schéma du fichier
 * OpenAPI, en lecture seule — un contrat est subi. D'abord les contrats, puis tous les
 * modèles de celui qu'on ouvre, par version (Gael, 23/10/2026, story a3988aaf).
 */
export function ContractModelsScreen({
  workspace,
  target,
  sens,
  contract: opened,
  onBack,
  onContract,
  onOpen,
}: {
  workspace: Workspace;
  target: WorkTarget;
  sens: Direction;
  // Le contrat ouvert ; absent : la liste des contrats.
  contract: string | undefined;
  onBack: () => void;
  onContract: (slug: string | undefined) => void;
  onOpen: (ref: DerivedRef) => void;
}) {
  const { t } = useTranslation();
  const contracts = useContracts(target);
  const mine = (contracts.data ?? []).filter((c) => c.sens === sens);
  const chosen = opened === undefined ? undefined : mine.find((c) => c.slug === opened);

  return (
    <section aria-labelledby="contract-models-title">
      <button
        type="button"
        className="btn btn-secondary back"
        onClick={() => (opened === undefined ? onBack() : onContract(undefined))}
      >
        {opened === undefined ? t("dataModels.back") : t("contractModels.backToContracts")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="contract-models-title">
            {chosen
              ? t("contractModels.contractTitle", { label: chosen.label })
              : t(`contractModels.title.${sens}`, { name: workspace.name })}
          </h1>
          <p className="lead">{t("contractModels.intro")}</p>
        </div>
      </div>
      {contracts.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {contracts.isError && <ContractRefusal error={contracts.error} />}
      {contracts.isSuccess && opened === undefined && mine.length === 0 && (
        <p className="muted">{t(`contractModels.empty.${sens}`)}</p>
      )}
      {contracts.isSuccess && opened !== undefined && chosen === undefined && (
        <p className="alert" role="alert">{t("contracts.errors.notFound")}</p>
      )}
      {opened === undefined && mine.length > 0 && (
        <ul className="card-list plain-list">
          {mine.map((c) => (
            <ContractRow key={c.slug} contract={c} onOpen={() => onContract(c.slug)} />
          ))}
        </ul>
      )}
      {chosen?.versions.length === 0 && <p className="muted">{t("contractModels.noVersion")}</p>}
      {chosen?.versions.map((version) => (
        <VersionModels
          key={version.number}
          target={target}
          contract={chosen}
          version={version}
          onOpen={onOpen}
        />
      ))}
    </section>
  );
}
