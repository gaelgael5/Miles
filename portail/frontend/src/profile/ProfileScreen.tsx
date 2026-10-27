import { useTranslation } from "react-i18next";

import { type Me, ProfileShell } from "@miles/socle-web";
import { useWorkspaces } from "../api/workspaces";
import { BranchPicker } from "../workspaces/BranchPicker";
import { ActorIdentitySection } from "./ActorIdentitySection";
import { GitIdentitiesSection } from "./GitIdentitiesSection";
import { OAuthGrantsSection } from "./OAuthGrantsSection";
import { ShelvesSection } from "./ShelvesSection";

function BranchViews() {
  const { t } = useTranslation();
  const workspaces = useWorkspaces();
  const withBranch = (workspaces.data ?? []).filter((w) => w.work_branch !== null);
  return (
    <section className="card" aria-labelledby="profile-branches">
      <h2 id="profile-branches">{t("profile.branches")}</h2>
      {workspaces.isSuccess && withBranch.length === 0 && (
        <p className="muted">{t("profile.noBranch")}</p>
      )}
      <ul className="card-list plain-list">
        {withBranch.map((w) => (
          <li key={w.id} className="row">
            <div className="row-main">
              <div className="row-title">{w.name}</div>
            </div>
            <BranchPicker workspace={w} />
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * Mon profil (ticket 0a52596d) : qui je suis pour le portail, et mes préférences.
 *
 * L'identité de session et le choix de langue sont dans `ProfileShell`, au socle : c'est
 * un des quatre écrans répliqués dans les trois produits (cadrage, « À quel produit
 * appartient chaque écran »). Ne figurent ici que les sections propres au portail.
 */
export function ProfileScreen({ me }: { me: Me }) {
  return (
    <ProfileShell me={me}>
      <GitIdentitiesSection />
      <ActorIdentitySection />
      <OAuthGrantsSection />
      <ShelvesSection />
      {/* Les workspaces sont réservés à l'administrateur tant que les rôles manquent. */}
      {me.root_admin && <BranchViews />}
    </ProfileShell>
  );
}
