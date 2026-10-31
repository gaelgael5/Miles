import { opensSource, runsOn } from "../dataModels/jsltKeys";

/** Ce qui remplace le Web Component JSLT dans les tests : la même interface, un textarea.
 *
 * Le composant réel s'enregistre par un <script type="module"> et gère son clavier
 * lui-même ; sous jsdom il ne vivrait pas. Les raccourcis restent câblés ici, par les
 * mêmes prédicats que le vrai composant : ce que les tests mesurent est la règle que le
 * navigateur exécute, et non une seconde écriture de cette règle.
 *
 * Un `<textarea>` et non un `<input>` : le composant réel en porte un, et c'est par lui
 * que l'écran lit le curseur pour insérer un chemin au bon endroit.
 */
export default function JsltEditorStub({
  value,
  onChange,
  onRun,
  onOpenSource,
  onReady,
  readOnly,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  onRun?: () => void;
  onOpenSource?: () => void;
  onReady?: (area: HTMLTextAreaElement | null) => void;
  readOnly: boolean;
  ariaLabel: string;
  // Reçue mais ignorée : le vrai composant la consomme, pas la doublure.
  paths?: unknown[];
}) {
  return (
    <textarea
      ref={(element) => onReady?.(element)}
      aria-label={ariaLabel}
      value={value}
      readOnly={readOnly}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (runsOn(e)) {
          e.preventDefault();
          onRun?.();
        } else if (opensSource(e)) {
          e.preventDefault();
          onOpenSource?.();
        }
      }}
    />
  );
}
