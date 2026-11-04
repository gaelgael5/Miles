import { useTranslation } from "react-i18next";

import {
  type CultureCoverage,
  type TradsCoverage,
  percentOf,
  useTradsCoverage,
} from "../api/tradsCoverage";
import type { TradsContext } from "../api/trads";
import type { WorkTarget } from "../api/workTarget";
import { Refusal } from "./tradsRefusal";

/** Une barre de couverture, et le taux à côté. `null` : aucune clé, donc aucun taux. */
function Bar({ translated, keys }: { translated: number; keys: number }) {
  const { t } = useTranslation();
  const percent = percentOf(translated, keys);
  if (percent === null) {
    return <span className="badge">{t("tradsCoverage.emptyContext")}</span>;
  }
  return (
    <span className="coverage-bar" title={t("tradsCoverage.percent", { percent })}>
      {/* `aria-hidden` : la barre redit le taux qui est juste à côté en texte, et un
          lecteur d'écran l'annoncerait deux fois. */}
      <span className="coverage-bar-fill" style={{ width: `${percent}%` }} aria-hidden="true" />
      <span className="coverage-bar-value">{t("tradsCoverage.percent", { percent })}</span>
    </span>
  );
}

/**
 * Une culture à l'échelle de l'installation (critère 1), avec ce qui mérite d'être dit.
 *
 * Une traduction manquante n'est PAS une erreur : c'est l'état normal d'une clé qu'on
 * vient d'ajouter. La ligne la compte et la retrouve, elle ne crie pas. Ce qui se
 * signale, c'est une culture très peu traduite — celle-là est déjà sous les yeux
 * d'utilisateurs réels — et une incohérence du dépôt sur la culture par défaut.
 */
function CultureRow({ row, coverage }: { row: CultureCoverage; coverage: TradsCoverage }) {
  const { t } = useTranslation();
  return (
    <li className="row">
      <div className="row-main">
        <code>{row.culture}</code>
        {row.is_default && (
          <span className="badge badge-accent">{t("tradsCoverage.isDefault")}</span>
        )}
        {row.low && (
          <span
            className="badge badge-warning"
            title={t("tradsCoverage.lowHelp", { culture: coverage.default })}
          >
            {t("tradsCoverage.low", { threshold: coverage.threshold })}
          </span>
        )}
      </div>
      <div className="cell">
        <div className="caption">{t("tradsCoverage.translated")}</div>
        <div className="value">
          {row.translated} / {coverage.keys}
        </div>
      </div>
      <div className="cell">
        <Bar translated={row.translated} keys={coverage.keys} />
      </div>
      {row.inconsistent && (
        // Dit comme une incohérence du DÉPÔT et non comme un retard de traduction
        // (critère 6) : une clé ne peut pas être créée sans valeur dans cette culture,
        // donc ces clés viennent d'une modification faite hors de Miles.
        <p className="alert">
          {t("tradsCoverage.inconsistent", { count: row.missing })}{" "}
          {t("tradsCoverage.inconsistentHelp")}
        </p>
      )}
    </li>
  );
}

/** Une cellule par culture sur la ligne d'un contexte : le compte, et le raccourci vers
 * les clés qui manquent — c'est ce qui fait « retrouver ce qui manque ». */
function ContextCell({
  context,
  row,
  onOpen,
}: {
  context: TradsContext;
  row: CultureCoverage;
  onOpen?: (context: string, untranslated: string) => void;
}) {
  const { t } = useTranslation();
  const done = context.translated[row.culture] ?? 0;
  const missing = context.keys - done;
  return (
    <div className="cell">
      <div className="caption">
        <code>{row.culture}</code>
      </div>
      <div className="value">
        {done} / {context.keys}
        {missing > 0 && onOpen && (
          <button
            type="button"
            className="coverage-missing"
            title={t("tradsCoverage.openUntranslatedTitle", {
              context: context.label,
              culture: row.culture,
            })}
            onClick={() => onOpen(context.name, row.culture)}
          >
            {t("tradsCoverage.openUntranslated", { count: missing })}
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * Couverture des traductions de la branche (story 82e60880) : ce qui est traduit, et ce
 * qui manque. Trois niveaux de lecture — l'installation, le contexte, puis la clé, cette
 * dernière sur l'écran de saisie où le filtre « non traduit » donne la liste de travail.
 *
 * Aucun index : les compteurs viennent du DÉPÔT à chaque lecture. Un index de couverture
 * stocké à côté pourrait le contredire, et il faudrait alors choisir lequel croire.
 */
export function TradsCoverageScreen({
  target,
  onBack,
  onOpen,
}: {
  target: WorkTarget;
  onBack: () => void;
  /** Ouvre un contexte, filtré sur les clés sans valeur dans cette culture. */
  onOpen?: (context: string, untranslated: string) => void;
}) {
  const { t } = useTranslation();
  const coverage = useTradsCoverage(target);
  const data = coverage.data;

  return (
    <section aria-labelledby="trads-coverage-title">
      <button type="button" className="btn btn-secondary back" onClick={onBack}>
        {t("dataModels.back")}
      </button>
      <div className="page-head">
        <div>
          <h1 id="trads-coverage-title">{t("tradsCoverage.title")}</h1>
          <p className="lead">{t("tradsCoverage.intro")}</p>
        </div>
      </div>
      {coverage.isError && <Refusal error={coverage.error} />}
      {coverage.isPending && (
        <p className="muted" role="status">
          {t("tradsCoverage.loading")}
        </p>
      )}
      {data && (
        <>
          <div className="card">
            {/* La branche que le SERVEUR a lue, et non celle de l'adresse : sans branche
                demandée il lit la branche de base, et deux branches n'ont pas les mêmes
                clés (critère 11). */}
            <p className="muted">{t("tradsCoverage.branch", { branch: data.branch })}</p>
            <p className="muted" role="status">
              {t("tradsCoverage.keysTotal", { count: data.keys })}
            </p>
          </div>
          <h2 id="coverage-by-culture">{t("tradsCoverage.byCulture")}</h2>
          {/* Les deux listes portent leur titre comme nom accessible : « par culture » et
              « par contexte » montrent les mêmes comptes, et sans nom un lecteur d'écran
              annonce deux listes indiscernables. */}
          <ul className="card-list plain-list" aria-labelledby="coverage-by-culture">
            {data.cultures.map((row) => (
              <CultureRow key={row.culture} row={row} coverage={data} />
            ))}
          </ul>
          <h2 id="coverage-by-context">{t("tradsCoverage.byContext")}</h2>
          {data.contexts.length === 0 ? (
            <p className="muted" role="status">
              {t("trads.none")}
            </p>
          ) : (
            <ul className="card-list plain-list" aria-labelledby="coverage-by-context">
              {data.contexts.map((context) => (
                <li className="row" key={context.name}>
                  <div className="row-main">
                    {context.label}
                    <div className="row-sub mono">{context.name}</div>
                  </div>
                  <div className="cell">
                    <div className="caption">{t("tradsCoverage.contextKeys")}</div>
                    <div className="value">{context.keys}</div>
                  </div>
                  {context.keys === 0 ? (
                    // Critère 9 : compté comme VIDE, jamais comme couvert. « 0 / 0 » par
                    // culture se lirait aussi bien « rien à faire » que « tout est fait ».
                    <div className="cell">
                      <span className="badge">{t("tradsCoverage.emptyContext")}</span>
                    </div>
                  ) : (
                    <div className="trads-values">
                      {data.cultures.map((row) => (
                        <ContextCell
                          key={row.culture}
                          context={context}
                          row={row}
                          onOpen={onOpen}
                        />
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
