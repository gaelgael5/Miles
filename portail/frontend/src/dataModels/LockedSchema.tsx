import { type JsonSchema, SchemaFieldsEditor, en, fr } from "jsonjoy-builder";
import "jsonjoy-builder/styles.css";
import { useTranslation } from "react-i18next";

/**
 * Un schéma montré dans l'éditeur visuel, VERROUILLÉ.
 *
 * C'est le geste de la vue « Événements » du playground d'urban-workflow, et sa raison y
 * est écrite : le fork de l'éditeur ne sait pas verrouiller un champ isolé, donc le socle
 * commun est une SECONDE instance en lecture seule, au-dessus de l'instance éditable.
 *
 * Pourquoi le même éditeur et pas un tableau : montré autrement, le socle se lit comme
 * une annexe, et on ne voit plus que l'événement en DÉRIVE (relevé par Gael le
 * 11/11/2026). Mêmes types, même arbre, même vocabulaire — la seule différence visible
 * est qu'on ne peut pas y toucher.
 */
export default function LockedSchema({ schema }: { schema: JsonSchema }) {
  const { i18n } = useTranslation();
  return (
    <div className="locked-schema">
      <SchemaFieldsEditor
        value={schema}
        // L'éditeur exige un `onChange` ; en lecture seule il ne part jamais.
        onChange={() => undefined}
        readOnly
        locale={i18n.language.startsWith("fr") ? fr : en}
      />
    </div>
  );
}
