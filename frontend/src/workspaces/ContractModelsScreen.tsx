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

/**
 * Modèles dérivés des contrats d'un sens (story 47f55d8b) : un par schéma du fichier
 * OpenAPI, rangés par contrat puis par version. En lecture seule — un contrat est subi.
 */
export function ContractModelsScreen({
  workspace,
  target,
  sens,
  onBack,
  onOpen,
}: {
  workspace: Workspace;
  target: WorkTarget;
  sens: Direction;
  onBack: () => void;
  onOpen: (ref: DerivedRef) => void;
}) {
  const { t } = useTranslation();
  const contracts = useContracts(target);
  const mine = (contracts.data ?? []).filter((c) => c.sens === sens);

  return (
    <section aria-labelledby="contract-models-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="contract-models-title">
            {t(`contractModels.title.${sens}`, { name: workspace.name })}
          </h1>
          <p className="lead">{t("contractModels.intro")}</p>
        </div>
      </div>
      {contracts.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {contracts.isError && <ContractRefusal error={contracts.error} />}
      {contracts.isSuccess && mine.length === 0 && (
        <p className="muted">{t(`contractModels.empty.${sens}`)}</p>
      )}
      {mine.map((contract) =>
        contract.versions.map((version) => (
          <VersionModels
            key={`${contract.slug}/${version.number}`}
            target={target}
            contract={contract}
            version={version}
            onOpen={onOpen}
          />
        )),
      )}
    </section>
  );
}
