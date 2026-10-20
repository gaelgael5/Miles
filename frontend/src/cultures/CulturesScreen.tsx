import { useState } from "react";
import { useTranslation } from "react-i18next";

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
    <li>
      <label>
        <input type="checkbox" checked={selected} disabled={isFallback} onChange={onToggle} />
        <code>{culture.code}</code> {culture.label_native} — {culture.label_en}
      </label>
      {culture.active && <span>{t("cultures.active")}</span>}
      {isFallback && <span> {t("cultures.fallbackNote")}</span>}
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

  return (
    <section aria-labelledby="cultures-title">
      <h2 id="cultures-title">{t("cultures.title")}</h2>
      <p>{t("cultures.intro")}</p>
      <label>
        {t("cultures.filter")}
        <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </label>
      <p>
        {t("cultures.selected", { count: selected.size })}{" "}
        <button type="button" disabled={selected.size === 0 || change.isPending} onClick={() => apply(true)}>
          {t("cultures.activate")}
        </button>
        <button type="button" disabled={selected.size === 0 || change.isPending} onClick={() => apply(false)}>
          {t("cultures.deactivate")}
        </button>
      </p>
      <p>{t("cultures.keepValues")}</p>
      {change.isError && <p role="alert">{t(errorKey(change.error))}</p>}
      {cultures.isPending && <p role="status">{t("cultures.loading")}</p>}
      {cultures.isError && <p role="alert">{t("cultures.errors.unreachable")}</p>}
      {cultures.isSuccess && visible.length === 0 && (
        <p role="status">{t("cultures.noMatch", { filter })}</p>
      )}
      {visible.length > 0 && (
        <ul>
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
    </section>
  );
}
