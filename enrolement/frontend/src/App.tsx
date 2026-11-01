import { type JSX, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  applyLanguage,
  AuthGate,
  CollapsibleGroup,
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

import { type Environment, useEnvironments } from "./api/environments";
import { EnvironmentsScreen } from "./environments/EnvironmentsScreen";
import { PairingScreen } from "./pairing/PairingScreen";
import { AccountsScreen } from "./workspaces/AccountsScreen";
import { WorkspaceScreen } from "./workspaces/WorkspaceScreen";

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

/** Les deux pages d'un workspace hébergé : ce qu'il sert, et ses comptes. */
type VueWorkspace = "hosting" | "accounts";

/**
 * Ce que le menu a ouvert : un écran global, ou une page d'un workspace hébergé.
 *
 * Une seule valeur pour les deux, et non deux états côte à côte : deux états laissent
 * exprimer « un écran global ET un workspace ouverts », qui n'a pas de sens et qu'il
 * faudrait alors arbitrer à chaque rendu.
 */
type Ouvert =
  | { quoi: "page"; nom: Page }
  | { quoi: "workspace"; environmentId: string; vue: VueWorkspace };

function BackOffice({ me, profil, onQuitterProfil }: {
  me: Me;
  profil: boolean;
  onQuitterProfil: () => void;
}) {
  const { t } = useTranslation();
  const [ouvert, setOuvert] = useState<Ouvert>({ quoi: "page", nom: "health" });
  const environnements = useEnvironments();
  // Les workspaces du menu sont ceux qu'un environnement héberge : le placement les y
  // fait apparaître, et le retrait les en retire. Aucune autre source — un workspace
  // exposé mais placé nulle part n'a pas de page, il n'est hébergé par personne.
  const heberges = (environnements.data ?? []).filter((e) => e.workspace_id !== null);
  const choisi =
    ouvert.quoi === "workspace"
      ? heberges.find((e) => e.id === ouvert.environmentId)
      : undefined;

  function ouvrir(cible: Ouvert) {
    // Tout choix dans le menu referme le profil, ouvert depuis la barre du haut.
    onQuitterProfil();
    setOuvert(cible);
  }

  function actuel(cible: Ouvert): "page" | undefined {
    if (profil) {
      return undefined;
    }
    if (cible.quoi === "page") {
      return ouvert.quoi === "page" && ouvert.nom === cible.nom ? "page" : undefined;
    }
    const meme =
      ouvert.quoi === "workspace" &&
      ouvert.environmentId === cible.environmentId &&
      ouvert.vue === cible.vue;
    return meme ? "page" : undefined;
  }

  return (
    <div className="body">
      <nav className="sidebar" aria-label={t("app.navigation")}>
        <div className="sidebar-group">
          {/* Repliable comme celles du portail (Gael, 01/11/2026) : la feuille de style
              du socle dessine un chevron sur `.sidebar-section`, et un menu qui montre
              le geste sans le servir se lit comme une panne. */}
          <CollapsibleGroup
            className="sidebar-section"
            label={t("app.sections.global")}
            defaultOpen
          >
            {ECRANS.map(({ nom }) => (
              <button
                key={nom}
                type="button"
                className="sidebar-link"
                aria-current={actuel({ quoi: "page", nom })}
                onClick={() => ouvrir({ quoi: "page", nom })}
              >
                {t(`app.nav.${nom}`)}
              </button>
            ))}
          </CollapsibleGroup>
        </div>
        <div className="sidebar-group">
          <CollapsibleGroup
            className="sidebar-section"
            label={t("app.sections.workspaces")}
            defaultOpen
          >
            {heberges.length === 0 && (
              <p className="sidebar-link muted">{t("app.workspaces.none")}</p>
            )}
            {heberges.map((environnement) => (
              <WorkspaceLiens
                key={environnement.id}
                environnement={environnement}
                actuel={actuel}
                onOuvrir={ouvrir}
              />
            ))}
          </CollapsibleGroup>
        </div>
      </nav>
      <main className="content">
        {profil ? <ProfileShell me={me} /> : <Contenu ouvert={ouvert} choisi={choisi} />}
      </main>
    </div>
  );
}

/**
 * Le workspace dans le menu, et sa page Comptes dessous.
 *
 * La page du workspace s'ouvre d'un clic sur son nom, et « Comptes » reste visible
 * dessous même fermée : une page qu'on ne découvre qu'après avoir ouvert la précédente
 * n'est pas découverte du tout.
 */
function WorkspaceLiens({
  environnement,
  actuel,
  onOuvrir,
}: {
  environnement: Environment;
  actuel: (cible: Ouvert) => "page" | undefined;
  onOuvrir: (cible: Ouvert) => void;
}) {
  const { t } = useTranslation();
  const hosting: Ouvert = { quoi: "workspace", environmentId: environnement.id, vue: "hosting" };
  const accounts: Ouvert = { quoi: "workspace", environmentId: environnement.id, vue: "accounts" };
  return (
    <>
      <button
        type="button"
        className="sidebar-link"
        aria-current={actuel(hosting)}
        onClick={() => onOuvrir(hosting)}
      >
        {environnement.workspace_id}
        {/* L'environnement sous le workspace : deux environnements peuvent héberger le
            même, et le nom seul ne dirait pas lequel on ouvre. */}
        <span className="muted"> · {environnement.slug}</span>
      </button>
      <button
        type="button"
        className="sidebar-link sidebar-sublink"
        aria-current={actuel(accounts)}
        onClick={() => onOuvrir(accounts)}
      >
        {t("app.nav.accounts")}
      </button>
    </>
  );
}

function Contenu({ ouvert, choisi }: { ouvert: Ouvert; choisi: Environment | undefined }) {
  const { t } = useTranslation();
  if (ouvert.quoi === "page") {
    const { Ecran } = ECRANS.find((ecran) => ecran.nom === ouvert.nom) ?? ECRANS[0];
    return <Ecran />;
  }
  if (choisi === undefined) {
    // Le workspace a été retiré de son environnement pendant qu'on le regardait, ou la
    // lecture du référentiel n'a pas encore rendu. On le DIT : une page vide se lirait
    // comme une panne de l'écran.
    return (
      <p className="alert" role="status">
        {t("app.workspaces.gone")}
      </p>
    );
  }
  return ouvert.vue === "accounts" ? (
    <AccountsScreen environnement={choisi} />
  ) : (
    <WorkspaceScreen environnement={choisi} />
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
