import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@miles/socle-web";

import type { Environment } from "../api/environments";
import { type PairedEnvironment, useSetPeerEnvironment } from "../api/pairing";
import { EnvironmentPicker } from "./EnvironmentPicker";

/**
 * L'environnement d'un appariement conclu : le rattacher, ou en changer.
 *
 * Un seul composant pour les deux, parce que c'est un seul geste côté humain — « cet
 * appariement appartient à cet environnement ». Ce qui change, c'est ce qu'il y avait
 * avant, et donc ce qu'il faut lui dire :
 *
 * - RIEN avant : appariement hérité, conclu avant que la désignation n'existe. Le
 *   rattacher ne retire rien à personne, et part sans confirmation.
 * - QUELQUE CHOSE avant : c'est un déplacement. Il se confirme, et la confirmation NOMME
 *   l'environnement quitté et l'environnement pris — par leur libellé ET leur slug, parce
 *   que c'est le slug qui s'écrit dans une procédure et deux libellés se ressemblent.
 *
 * Le serveur refuse le déplacement d'un appariement qui porte des devices : la garde est
 * chez lui, pas ici. L'écran la répète pour que l'humain la lise avant de cliquer, jamais
 * à sa place — un bouton caché laisserait la route répondre.
 */
export function EnvironmentAssign({ environnement }: { environnement: PairedEnvironment }) {
  const { t } = useTranslation();
  const [ouvreChoix, setOuvreChoix] = useState(false);
  const [cible, setCible] = useState<Environment | null>(null);
  const pose = useSetPeerEnvironment();
  const quitte = environnement.environment;

  function envoie(choisi: Environment) {
    pose.mutate(
      { baseUrl: environnement.base_url, environmentId: choisi.id },
      {
        onSuccess: () => {
          setOuvreChoix(false);
          setCible(null);
        },
      },
    );
  }

  return (
    <>
      <div className="actions row-actions">
        <button
          type="button"
          className={quitte === null ? "btn btn-primary" : "btn btn-secondary"}
          aria-expanded={ouvreChoix}
          onClick={() => setOuvreChoix((ouvert) => !ouvert)}
        >
          {quitte === null ? t("pairing.designation.attach") : t("pairing.move.action")}
        </button>
      </div>
      {quitte === null && !ouvreChoix && (
        <p className="help" role="status">
          {t("pairing.designation.attachHelp")}
        </p>
      )}
      {ouvreChoix && (
        <EnvironmentPicker
          choisi={quitte?.id ?? null}
          pending={pose.isPending}
          error={pose.isError ? pose.error : null}
          submitLabel={
            quitte === null ? t("pairing.designation.attachSubmit") : t("pairing.move.submit")
          }
          onChoose={(choisi) => {
            // Le rattachement part tout de suite : il n'y a rien à perdre. Le déplacement
            // passe par la confirmation, qui est le seul endroit où les deux noms se
            // lisent côte à côte.
            if (quitte === null) {
              envoie(choisi);
              return;
            }
            setCible(choisi);
          }}
        />
      )}
      {ouvreChoix && quitte !== null && <p className="help">{t("pairing.move.help")}</p>}
      {cible !== null && quitte !== null && (
        <ConfirmDialog
          title={t("pairing.move.title")}
          confirmLabel={t("pairing.move.confirm")}
          cancelLabel={t("pairing.move.cancel")}
          onCancel={() => setCible(null)}
          onConfirm={() => envoie(cible)}
        >
          <p>
            {t("pairing.move.body", {
              url: environnement.base_url,
              fromLabel: quitte.label,
              fromSlug: quitte.slug,
              toLabel: cible.label,
              toSlug: cible.slug,
            })}
          </p>
          {/* Ce que le déplacement NE fait pas : ni clés, ni devices. Les deux craintes
              qu'on a devant ce bouton, et les taire les laisse entières. */}
          <p className="help">{t("pairing.move.keys")}</p>
          <p className="help">{t("pairing.move.devices")}</p>
        </ConfirmDialog>
      )}
    </>
  );
}
