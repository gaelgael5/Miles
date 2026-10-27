/** Ce qui remplace le Web Component JSLT dans les tests : la même interface, un textarea.
 *
 * Le composant réel s'enregistre par un <script type="module"> et gère son clavier
 * lui-même ; sous jsdom il ne vivrait pas. F5 reste câblé ici, pour que le raccourci
 * soit éprouvé là où il est écrit : autour du composant.
 */
export default function JsltEditorStub({
  value,
  onChange,
  onRun,
  readOnly,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  onRun?: () => void;
  readOnly: boolean;
  ariaLabel: string;
  // Reçue mais ignorée : le vrai composant la consomme, pas le doublon.
  paths?: unknown[];
}) {
  return (
    <textarea
      aria-label={ariaLabel}
      value={value}
      readOnly={readOnly}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "F5") {
          e.preventDefault();
          onRun?.();
        }
      }}
    />
  );
}
