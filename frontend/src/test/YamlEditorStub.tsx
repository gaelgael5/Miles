/** Ce qui remplace Monaco dans les tests : la même interface, une zone de texte. */
export default function YamlEditorStub({
  value,
  onChange,
  readOnly,
}: {
  value: string;
  onChange: (value: string) => void;
  readOnly: boolean;
}) {
  return (
    <textarea aria-label="YAML" value={value} readOnly={readOnly} onChange={(e) => onChange(e.target.value)} />
  );
}
