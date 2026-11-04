import { useState } from "react";
import { useTranslation } from "react-i18next";

import { PageHead } from "../layout/PageHead";
import { ApiError } from "../api/http";
import {
  type Culture,
  FALLBACK_CODE,
  matchesFilter,
  useCultures,
  useSetCulturesActive,
} from "../api/cultures";

function errorKey(error: unknown): string {
  if (error instanceof ApiError && error.status === 422) {
    const detail = error.detail as { code?: string } | undefined;
    if (detail?.code === "repli_obligatoire") {
      return "cultures.errors.fallback";
    }
  }
  return "cultures.errors.unexpected";
}

function CultureRow({
  culture,
  selected,
  onToggle,
}: {
  culture: Culture;
  selected: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  const isFallback = culture.code === FALLBACK_CODE;
  return (
    // La ligne de la maquette : case, code en colonne fixe, nom, pastilles à droite. Le
    // repli porte en plus un fond, parce que sa case est verrouillée et qu'une case
    // cochée-grisée sans autre marque se lit comme une case oubliée.
    <li className={isFallback ? "row row-compact row-soft" : "row row-compact"}>
      {/* Le libellé accessible est porté par la case elle-même et non par un `label`
          englobant : la ligne est devenue trois colonnes, et un `label` qui les enveloppe
          rendrait tout le texte de la ligne cliquable, y compris les pastilles. */}
      <input
        type="checkbox"
        checked={selected}
        disabled={isFallback}
        aria-label={t("cultures.toggle", { code: culture.code })}
        onChange={onToggle}
      />
      <code className="row-code">{culture.code}</code>
      <div className="row-main">
        {culture.label_native} — {culture.label_en}
      </div>
      {/* UNE pastille par ligne, comme la maquette. Le repli est actif par construction :
          afficher « Active » puis « Repli — toujours active » faisait lire deux états là
          où il n'y en a qu'un, et la ligne s'allongeait d'autant. */}
      {isFallback ? (
        <span className="badge badge-accent">{t("cultures.fallbackNote")}</span>
      ) : (
        culture.active && <span className="badge badge-success">{t("cultures.active")}</span>
      )}
    </li>
  );
}

/** Cultures de l'installation : la liste est donnée, on n'y fait qu'activer et désactiver. */
export function CulturesScreen() {
  const { t } = useTranslation();
  const cultures = useCultures();
  const change = useSetCulturesActive();
  const [filter, setFilter] = useState("");
  // La sélection survit au filtre : l'action porte sur ce qui est coché, pas sur ce
  // qui est affiché, pour qu'un filtre modifié entre-temps n'élargisse rien.
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const visible = (cultures.data ?? []).filter((c) => matchesFilter(c, filter));

  function toggle(code: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(code)) {
        next.delete(code);
      } else {
        next.add(code);
      }
      return next;
    });
  }

  function apply(active: boolean) {
    change.mutate({ codes: [...selected], active }, { onSuccess: () => setSelected(new Set()) });
  }

  const actives = (cultures.data ?? []).filter((c) => c.active).length;

  return (
    <section aria-labelledby="cultures-title">
      {/* La maquette chiffre les actives à côté du titre : c'est la seule chose qu'on
          vient vérifier sans rien faire d'autre, et la compter à la main dans une liste
          de deux cents lignes n'est pas un geste. */}
      <PageHead
        id="cultures-title"
        title={t("cultures.title")}
        lead={t("cultures.intro")}
        action={<span className="badge badge-success">{t("cultures.activeCount", { count: actives })}</span>}
      />
      {/* Le filtre seul au-dessus de la liste, sans carte autour : la maquette ne met en
          carte que la liste elle-même, et l'encadrer une deuxième fois ajoutait un bloc
          entre le titre et ce qu'on est venu lire. */}
      <label className="field">
        {t("cultures.filter")}
        <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </label>
      {change.isError && <p className="alert" role="alert">{t(errorKey(change.error))}</p>}
      {cultures.isPending && <p className="muted" role="status">{t("cultures.loading")}</p>}
      {cultures.isError && <p className="alert" role="alert">{t("cultures.errors.unreachable")}</p>}
      {cultures.isSuccess && visible.length === 0 && (
        <p className="muted" role="status">{t("cultures.noMatch", { filter })}</p>
      )}
      {visible.length > 0 && (
        <ul className="card-list plain-list">
          {visible.map((culture) => (
            <CultureRow
              key={culture.code}
              culture={culture}
              selected={selected.has(culture.code)}
              onToggle={() => toggle(culture.code)}
            />
          ))}
        </ul>
      )}
      {/* Les gestes SOUS la liste, comme la maquette : ils portent sur ce qu'on vient de
          cocher, et placés au-dessus ils demandaient d'agir avant d'avoir choisi. La
          conséquence de la désactivation reste à côté d'eux, au moment où elle se décide. */}
      <div className="actions">
        <span className="muted">{t("cultures.selected", { count: selected.size })}</span>
        <button
          type="button"
          className="btn btn-primary"
          disabled={selected.size === 0 || change.isPending}
          onClick={() => apply(true)}
        >
          {t("cultures.activate")}
        </button>
        <button
          type="button"
          className="btn btn-danger"
          disabled={selected.size === 0 || change.isPending}
          onClick={() => apply(false)}
        >
          {t("cultures.deactivate")}
        </button>
      </div>
      <p className="help">{t("cultures.keepValues")}</p>
    </section>
  );
}
