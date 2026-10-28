import { type JSX, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  applyLanguage,
  AuthGate,
  ConnectorsScreen,
  CulturesScreen,
  HealthStatus,
  type Me,
  ProfileShell,
  readStoredCulture,
  SecretsScreen,
  Topbar,
  useLogout,
  usePreferences,
} from "@miles/socle-web";

import { EnvironmentsScreen } from "./environments/EnvironmentsScreen";
import { PairingScreen } from "./pairing/PairingScreen";

/**
 * Les écrans du menu, en UNE seule déclaration.
 *
 * Divergence volontaire avec le portail, qui tient la liste du menu et la table des
 * écrans à deux endroits : un écran présent dans l'une et absent de l'autre y donne un
 * écran inatteignable alors que tout paraît vert. Ici la clef et le composant voyagent
 * ensemble — l'oubli n'est plus exprimable. Les écrans du métier de l'enrôlement (parc,
 * enrôlement d'une installation, appariement d'un environnement) s'ajouteront ici.
 */
const ECRANS = [
  { nom: "pairing", Ecran: PairingScreen },
  { nom: "environments", Ecran: EnvironmentsScreen },
  { nom: "cultures", Ecran: CulturesScreen },
  { nom: "secrets", Ecran: SecretsScreen },
  { nom: "oidc", Ecran: ConnectorsScreen },
  { nom: "health", Ecran: HealthStatus },
] as const satisfies readonly { nom: string; Ecran: () => JSX.Element }[];

type Page = (typeof ECRANS)[number]["nom"];

function BackOffice({ me, profil, onQuitterProfil }: {
  me: Me;
  profil: boolean;
  onQuitterProfil: () => void;
}) {
  const { t } = useTranslation();
  const [page, setPage] = useState<Page>("health");
  const { Ecran } = ECRANS.find((ecran) => ecran.nom === page) ?? ECRANS[0];

  function ouvrir(nom: Page) {
    // Tout choix dans le menu referme le profil, ouvert depuis la barre du haut.
    onQuitterProfil();
    setPage(nom);
  }

  return (
    <div className="body">
      <nav className="sidebar" aria-label={t("app.navigation")}>
        <div className="sidebar-group">
          <span className="sidebar-section">{t("app.sections.global")}</span>
          <div>
            {ECRANS.map(({ nom }) => (
              <button
                key={nom}
                type="button"
                className="sidebar-link"
                aria-current={!profil && page === nom ? "page" : undefined}
                onClick={() => ouvrir(nom)}
              >
                {t(`app.nav.${nom}`)}
              </button>
            ))}
          </div>
        </div>
      </nav>
      <main className="content">{profil ? <ProfileShell me={me} /> : <Ecran />}</main>
    </div>
  );
}

function Connecte({ me }: { me: Me }) {
  const { t } = useTranslation();
  const logout = useLogout();
  const preferences = usePreferences();
  const [profil, setProfil] = useState(false);
  const language = preferences.data?.language;

  // La langue retenue pour le compte l'emporte ; sans choix, celle de l'écran de
  // connexion. Effet sur i18next, système extérieur à React : rien n'est recopié
  // dans un état, qui se désynchroniserait de la langue réellement affichée.
  useEffect(() => {
    if (preferences.isSuccess) {
      applyLanguage(language ?? readStoredCulture());
    }
  }, [preferences.isSuccess, language]);

  return (
    <>
      <Topbar>
        <button
          type="button"
          className="topbar-user topbar-button"
          aria-pressed={profil}
          onClick={() => setProfil(true)}
        >
          {me.email ?? me.username}
        </button>
        <button type="button" className="topbar-button" onClick={() => logout.mutate()}>
          {t("app.logout")}
        </button>
      </Topbar>
      {me.root_admin ? (
        <BackOffice me={me} profil={profil} onQuitterProfil={() => setProfil(false)} />
      ) : (
        // Authentifié n'est pas autorisé : sans rôle, rien d'autre que son profil ne
        // s'ouvre. Les rôles de ce produit viendront avec leur ticket — l'axe de portée
        // est suspendu par le découpage (cadrage, amendement du 26/10/2026).
        <div className="narrow">
          {profil ? (
            <ProfileShell me={me} />
          ) : (
            <p className="alert" role="status">
              {t("app.noRights", { directory: me.directory ?? "" })}
            </p>
          )}
        </div>
      )}
    </>
  );
}

export function App() {
  return (
    <div className="shell">
      <AuthGate>{(me) => <Connecte me={me} />}</AuthGate>
    </div>
  );
}
