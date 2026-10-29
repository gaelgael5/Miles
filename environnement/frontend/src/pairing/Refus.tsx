import { useTranslation } from "react-i18next";

import { ApiError } from "@miles/socle-web";

import { clockDrift } from "../api/pairing";

/**
 * La clef de libellé d'un refus, choisie sur ce que le serveur a RÉELLEMENT dit.
 *
 * Les cas sont séparés parce qu'ils appellent des gestes différents : une URL malformée
 * se corrige dans le champ, une URL qui ne répond pas se vérifie ailleurs, et un code
 * refusé se ressaisit. Les fondre en « une erreur est survenue » ferait recommencer au
 * hasard — ce que le ticket interdit explicitement.
 */
export function refusKey(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "pairing.errors.unexpected";
  }
  if (error.status === 422) {
    return error.detail === "name" ? "pairing.errors.name" : "pairing.errors.baseUrl";
  }
  if (error.status === 502) {
    return "pairing.errors.unreachable";
  }
  if (error.status === 409) {
    return "pairing.errors.refused";
  }
  return "pairing.errors.unexpected";
}

export function Refus({ error }: { error: unknown }) {
  const { t } = useTranslation();
  const derive = clockDrift(error);
  return (
    <p className="alert alert-danger" role="alert">
      {/* La dérive d'horloge est le SEUL refus que le pair détaille, et il le fait parce
          qu'un appariement TOTP qui échoue sans dire pourquoi est le piège classique :
          on cherche du côté du code pendant que la cause est une machine à l'heure près. */}
      {derive === null
        ? t(refusKey(error))
        : t("pairing.errors.clockSkew", { seconds: Math.abs(derive) })}
    </p>
  );
}
