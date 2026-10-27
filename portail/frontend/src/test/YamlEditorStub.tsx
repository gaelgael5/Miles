/** Ce qui remplace Monaco dans les tests : la même interface, une zone de texte. */
export default function YamlEditorStub({
  value,
  onChange,
  readOnly,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  readOnly: boolean;
  ariaLabel?: string;
}) {
  return (
    <textarea
      aria-label={ariaLabel ?? "YAML"}
      value={value}
      readOnly={readOnly}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}
