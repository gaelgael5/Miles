import { type FormEvent, useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";
import { proposeSlug } from "../api/contracts";
import {
  DEVICE_SENSES,
  type DataModel,
  type DeviceSens,
  type ListedModel,
  SHARED_SCOPE,
  deviceScope,
  useDeclareDataModel,
  useDeleteDataModel,
  useModelListing,
} from "../api/dataModels";
import { useDomains } from "../api/domains";
import type { WorkTarget } from "../api/workTarget";
import type { Workspace } from "../api/workspaces";
import { BrokenRefs, isEventPayload, roleSummary } from "../dataModels/ModelRole";
import { DomainForm } from "./DomainForm";
import { ModelRefusal } from "./ModelRefusal";

/**
 * L'emplacement d'un modèle, en mots : une portée technique ne se montre pas telle quelle.
 *
 * Un domaine est rendu par son propre nom — il est choisi par la personne, et il n'a pas
 * de traduction. Les trois autres portées sont posées par Miles, et ont donc un libellé :
 * « devices-inbound » affiché brut se lirait comme un nom de domaine mal nommé.
 */
function scopeLabel(t: TFunction, scope: string): string {
  if (scope === SHARED_SCOPE) {
    return t("dataModels.list.shared");
  }
  const sens = DEVICE_SENSES.find((s) => deviceScope(s) === scope);
  return sens === undefined ? scope : t(`dataModels.devices.${sens}`);
}

/**
 * Création en deux temps (Gael, 23/10/2026) : label, slug et domaine ici ; le YAML
 * s'écrit ensuite sur l'écran d'édition du modèle, qu'on ouvre aussitôt.
 */
function CreateForm({
  target,
  pinnedScope,
  onCreated,
  onCancel,
}: {
  target: WorkTarget;
  /** Portée imposée : le sous-menu d'un sens crée chez lui, et nulle part ailleurs. */
  pinnedScope?: string;
  onCreated: (model: DataModel) => void;
  onCancel: () => void;
}) {
  const { t } = useTranslation();
  const declare = useDeclareDataModel(target);
  const [label, setLabel] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  // Transverse par défaut : on ne promeut au transverse qu'au second usage réel, mais un
  // domaine se choisit dans la liste, jamais ne se tape (story 7fa00f56).
  const [chosenScope, setScope] = useState(SHARED_SCOPE);
  const scope = pinnedScope ?? chosenScope;
  // Aucun domaine à proposer quand la portée est imposée : la requête serait faite pour
  // un `<select>` qui ne s'affiche pas.
  const domains = useDomains(target, pinnedScope === undefined);
  const shownSlug = slugTouched ? slug : proposeSlug(label);

  function submit(event: FormEvent) {
    event.preventDefault();
    declare.mutate({ scope, label, slug: shownSlug }, { onSuccess: onCreated });
  }

  return (
    <form className="card" onSubmit={submit} aria-label={t("dataModels.form.title")}>
      <h2>{t("dataModels.form.title")}</h2>
      <label className="field">
        {t("dataModels.fields.label")}
        <input required value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <label className="field">
        {t("dataModels.fields.slug")}
        <input
          required
          className="mono"
          value={shownSlug}
          onChange={(e) => {
            setSlugTouched(true);
            setSlug(e.target.value);
          }}
        />
      </label>
      <p className="help">{t("dataModels.form.slugHelp")}</p>
      {/* Pas de choix d'emplacement quand le sous-menu l'impose : un `<select>` qui
          n'offre qu'une valeur demande un geste pour rien, et laisser choisir ferait
          créer un transverse depuis l'écran des devices entrants. */}
      {pinnedScope === undefined && (
        <>
          <label className="field">
            {t("dataModels.fields.domain")}
            <select value={scope} onChange={(e) => setScope(e.target.value)}>
              <option value={SHARED_SCOPE}>{t("dataModels.list.shared")}</option>
              {(domains.data ?? []).map((d) => (
                <option key={d.name} value={d.name}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>
          <p className="help">{t("dataModels.form.domainHelp")}</p>
        </>
      )}
      {declare.isError && <ModelRefusal error={declare.error} />}
      <div className="actions">
        <button type="submit" className="btn btn-primary" disabled={declare.isPending}>
          {t("dataModels.form.submit")}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          {t("dataModels.form.cancel")}
        </button>
      </div>
    </form>
  );
}

function ModelRow({
  target,
  model,
  onOpen,
}: {
  target: WorkTarget;
  model: ListedModel;
  onOpen: () => void;
}) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  const remove = useDeleteDataModel(target);

  return (
    <li className="row row-openable">
      <div className="row-main">
        {/* Toute la ligne ouvre le modèle (fbe9b512) : ce bouton étend sa zone à la ligne
            par CSS, plutôt qu'un <li> cliquable qui engloberait « Supprimer », mal lu au
            clavier et par un lecteur d'écran. Un modèle créé par son YAML n'a pas de label. */}
        <button type="button" className="row-title row-open" onClick={onOpen}>
          {model.label ?? model.name}
        </button>
        <div className="row-sub mono">{model.path}</div>
      </div>
      <div className="cell">
        <div className="caption">{t("dataModels.list.captionScope")}</div>
        <div className="value">{scopeLabel(t, model.scope)}</div>
      </div>
      {/* À quoi il sert, sur la ligne : depuis le 14/11/2026 le dossier ne le dit plus,
          et deux modèles de même emplacement n'ont plus rien qui les distingue sans ça
          (story e36192f8). Un modèle que rien ne désigne le dit, et ce n'est pas une
          anomalie : il peut être écrit avant ce qui s'en servira. */}
      <div className="cell">
        <div className="caption">{t("dataModels.role.caption")}</div>
        <div className="value">
          {model.usages.length === 0
            ? t("dataModels.role.none")
            : roleSummary(t, model.usages)}
        </div>
      </div>
      <div className="actions row-actions">
        {!target.readOnly && (
          <button type="button" className="btn btn-danger" onClick={() => setConfirming(true)}>
            {t("dataModels.list.delete")}
          </button>
        )}
      </div>
      {remove.isError && (
        <div className="row-detail">
          <ModelRefusal error={remove.error} />
        </div>
      )}
      {confirming && (
        <ConfirmDialog
          title={t("dataModels.deleteConfirm.title")}
          confirmLabel={t("dataModels.deleteConfirm.confirm")}
          cancelLabel={t("dataModels.form.cancel")}
          onCancel={() => setConfirming(false)}
          onConfirm={() => {
            setConfirming(false);
            remove.mutate(model);
          }}
        >
          <p>{t("dataModels.deleteConfirm.body", { path: model.path })}</p>
        </ConfirmDialog>
      )}
    </li>
  );
}

/**
 * Modèles de données du workspace, lus et écrits dans sa branche de travail.
 *
 * `device` : le sens du tuyau MQTT dont on ne montre que les modèles (story 31025fe6).
 * LE MÊME écran, et c'est la décision : « même forme et même éditeur que les pivots ».
 * Un écran séparé aurait dupliqué la liste, la déclaration, la suppression et leurs
 * refus — quatre endroits à corriger deux fois, pour un filtre sur une portée.
 */
export function DataModelsScreen({
  workspace,
  target,
  device,
  onBack,
  onOpen,
}: {
  workspace: Workspace;
  target: WorkTarget;
  device?: DeviceSens;
  onBack: () => void;
  onOpen: (model: DataModel) => void;
}) {
  const { t } = useTranslation();
  const listing = useModelListing(target);
  const scope = device === undefined ? undefined : deviceScope(device);
  // La liste de la branche est lue en UNE fois, quel que soit le sous-menu : c'est la même
  // requête que « Tous les modèles », donc le filtre ne coûte aucune ouverture de branche
  // de plus (chemin critique mesuré de l'enabler 7fb3577c).
  // Le payload d'un type d'event n'est pas dans cette liste (Gael, 19/11/2026 : « les
  // events apparaissent dans le menu events mais pas dans le menu model »). Il reste
  // joignable et éditable depuis l'écran de son event : il sort d'ici, il ne devient pas
  // invisible. Et c'est son USAGE qui le dit, jamais son nom ni son dossier.
  const all = (listing.data?.models ?? []).filter((m) => !isEventPayload(m.usages));
  const models = scope === undefined ? all : all.filter((m) => m.scope === scope);
  const [creating, setCreating] = useState(false);
  const [addingDomain, setAddingDomain] = useState(false);
  const [added, setAdded] = useState<string | null>(null);

  return (
    <section aria-labelledby="data-models-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="data-models-title">
            {device === undefined
              ? t("dataModels.title", { name: workspace.name })
              : t("dataModels.devices.title", {
                  sens: t(`dataModels.devices.${device}`),
                  name: workspace.name,
                })}
          </h1>
          <p className="lead">
            {device === undefined ? t("dataModels.intro") : t(`dataModels.devices.intro.${device}`)}{" "}
            <span className="mono">{workspace.work_branch}</span>
          </p>
        </div>
        {!target.readOnly && (
          <div className="actions">
            {/* Un sens n'a pas de domaine à déclarer : son dossier est à la racine du
                dépôt, commun à tous les domaines. */}
            {!addingDomain && device === undefined && (
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  setAdded(null);
                  setAddingDomain(true);
                }}
              >
                {t("dataModels.addDomain")}
              </button>
            )}
            {!creating && (
              <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
                {t("dataModels.add")}
              </button>
            )}
          </div>
        )}
      </div>
      {addingDomain && (
        <DomainForm
          target={target}
          onAdded={(domain) => {
            setAddingDomain(false);
            setAdded(domain.name);
          }}
          onCancel={() => setAddingDomain(false)}
        />
      )}
      {added !== null && (
        <p className="notice" role="status">
          {t("dataModels.domainForm.added", { name: added })}
        </p>
      )}
      {creating && (
        <CreateForm
          target={target}
          pinnedScope={scope}
          onCreated={onOpen}
          onCancel={() => setCreating(false)}
        />
      )}
      {listing.isPending && <p className="muted" role="status">{t("dataModels.loading")}</p>}
      {listing.isError && <ModelRefusal error={listing.error} />}
      {/* Les désignations cassées en TÊTE de liste : elles ne se rattachent à aucune
          ligne — c'est leur définition — et elles bloqueront l'enregistrement d'une
          version. Dites ici pour qu'on les voie avant d'y arriver (critère 5). */}
      {/* Les désignations cassées ne sont dites que sur la liste ENTIÈRE : elles sont de
          la branche, pas d'une portée, et les répéter sur chaque sous-menu ferait lire
          trois fois le même blocage — dont deux fois sous un titre qui ne le concerne pas. */}
      {device === undefined && listing.data !== undefined && listing.data.broken.length > 0 && (
        <BrokenRefs broken={listing.data.broken} />
      )}
      {listing.isSuccess && models.length === 0 && (
        <p className="muted">
          {device === undefined ? t("dataModels.empty") : t("dataModels.devices.empty")}
        </p>
      )}
      {listing.isSuccess && models.length > 0 && (
        <ul className="card-list plain-list">
          {models.map((m) => (
            <ModelRow key={m.path} target={target} model={m} onOpen={() => onOpen(m)} />
          ))}
        </ul>
      )}
    </section>
  );
}
