import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import "../i18n/i18n";
import type { EnrolmentPeer, PairingAttempt, PairingState } from "../api/peering";
import { mockApi, type Routes } from "../test/mockApi";
import { PairingScreen } from "./PairingScreen";

const ENROLEMENT = "https://enrolement.example.org";

// TYPÉS : passés en valeurs libres, un champ ajouté au contrat les laisserait muets et
// les tests resteraient verts sur un écran incomplet (leçon du 29/10/2026).
const TENTATIVE: PairingAttempt = {
  base_url: ENROLEMENT,
  created_at: "2026-10-28T09:00:00+00:00",
  name: "Environnement de recette",
  expires_at: "2026-10-28T10:00:00+00:00",
};

const PAIR: EnrolmentPeer = {
  base_url: ENROLEMENT,
  declared_name: "Environnement de recette",
  // Le cas ordinaire : on joint le pair là où il se nomme.
  contact_url: ENROLEMENT,
  // Aucun avis de révocation reçu. Omettre ce champ rendrait la branche qui le lit
  // invisible aux tests — leçon du 29/10/2026, appliquée le jour même.
  revoked_at: null,
  public_key: "A".repeat(43),
  public_key_fingerprint: "82876eb0c19c35fdf589d74b1d96ca65",
  algorithm: "ed25519",
  created_at: "2026-10-20T08:00:00+00:00",
  updated_at: "2026-10-20T08:00:00+00:00",
};

function etatRoute(body: PairingState): Routes {
  // UNE seule route, et c'est la mesure de l'extraction : l'écran du socle n'interroge
  // que l'état de l'appariement. Ce qu'un produit ajoute — l'environnement assigné du
  // module d'environnement — passe par `peerExtra`, avec SA requête, éprouvée chez lui.
  return { "GET /api/identity/pairing/state": { status: 200, body } };
}

function monte(routes: Routes) {
  const calls = mockApi(routes);
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <PairingScreen />
    </QueryClientProvider>,
  );
  return calls;
}

describe("écran d'appariement vu du demandeur", () => {
  it("says it is not paired and offers the URL and the name", async () => {
    monte(etatRoute({ state: "non_apparie", attempt: null, peer: null }));

    expect(await screen.findByText("Not paired")).toBeInTheDocument();
    expect(screen.getByLabelText("Enrolment module URL")).toBeInTheDocument();
    expect(screen.getByLabelText("Name of this module")).toBeInTheDocument();
  });

  it("distinguishes a malformed URL from one that does not answer", async () => {
    // Les deux appellent des gestes différents : l'une se corrige dans le champ, l'autre
    // se vérifie ailleurs. Les fondre ferait recommencer au hasard.
    monte({
      ...etatRoute({ state: "non_apparie", attempt: null, peer: null }),
      "POST /api/identity/pairing": [
        { status: 422, body: { detail: "base_url" } },
        { status: 502, body: { detail: "pair_injoignable" } },
      ],
    });

    const envoyer = await screen.findByRole("button", { name: "Send the request" });
    fireEvent.click(envoyer);
    expect(await screen.findByText(/not in the expected shape/i)).toBeInTheDocument();

    fireEvent.click(envoyer);
    expect(await screen.findByText(/does not answer/i)).toBeInTheDocument();
  });

  it("refuses an unusable declared name with its own message", async () => {
    monte({
      ...etatRoute({ state: "non_apparie", attempt: null, peer: null }),
      "POST /api/identity/pairing": { status: 422, body: { detail: "name" } },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Send the request" }));

    expect(await screen.findByText(/name is empty, too long/i)).toBeInTheDocument();
  });

  it("sends the URL and the name that were typed", async () => {
    const appels = monte({
      ...etatRoute({ state: "non_apparie", attempt: null, peer: null }),
      "POST /api/identity/pairing": { status: 202, body: TENTATIVE },
    });

    fireEvent.change(await screen.findByLabelText("Enrolment module URL"), {
      target: { value: ENROLEMENT },
    });
    fireEvent.change(screen.getByLabelText("Name of this module"), {
      target: { value: "Recette nord" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send the request" }));

    await waitFor(() =>
      expect(appels.find((appel) => appel.key === "POST /api/identity/pairing")?.body).toEqual({
        base_url: ENROLEMENT,
        name: "Recette nord",
      }),
    );
  });

  it("while pending, says where the code is and takes it", async () => {
    monte(etatRoute({ state: "en_attente", attempt: TENTATIVE, peer: null }));

    expect(await screen.findByText("Request sent, awaiting acceptance")).toBeInTheDocument();
    expect(screen.getByText(new RegExp(ENROLEMENT))).toBeInTheDocument();
    expect(screen.getByLabelText("Six-digit code")).toBeInTheDocument();
    // Et surtout PAS le formulaire de demande : il ferait recommencer une demande vivante.
    expect(screen.queryByLabelText("Enrolment module URL")).toBeNull();
  });

  it("strips whitespace around a pasted code rather than refusing it", async () => {
    // Un code circule par copier-coller : il arrivera sale, et le refuser pour cela
    // reviendrait à refuser le bon code.
    const appels = monte({
      ...etatRoute({ state: "en_attente", attempt: TENTATIVE, peer: null }),
      "POST /api/identity/pairing/confirm": { status: 200, body: PAIR },
    });

    fireEvent.change(await screen.findByLabelText("Six-digit code"), {
      target: { value: "  314 159\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit the code" }));

    await waitFor(() =>
      expect(
        appels.find((appel) => appel.key === "POST /api/identity/pairing/confirm")?.body,
      ).toEqual({ code: "314159" }),
    );
  });

  it("keeps the pending state after a wrong code, and allows another try", async () => {
    monte({
      ...etatRoute({ state: "en_attente", attempt: TENTATIVE, peer: null }),
      "POST /api/identity/pairing/confirm": { status: 409, body: { detail: "appariement_refuse" } },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Submit the code" }));

    expect(await screen.findByText(/code was refused/i)).toBeInTheDocument();
    // L'état n'a pas changé : une nouvelle saisie est possible sans relancer la demande.
    expect(screen.getByLabelText("Six-digit code")).toBeInTheDocument();
    expect(screen.getByText("Request sent, awaiting acceptance")).toBeInTheDocument();
  });

  it("names the clock when that is what refused the code", async () => {
    // Le seul refus que le pair détaille. Sans ce message, on chercherait du côté du code
    // pendant que la cause est une machine à l'heure près.
    monte({
      ...etatRoute({ state: "en_attente", attempt: TENTATIVE, peer: null }),
      "POST /api/identity/pairing/confirm": {
        status: 409,
        body: { detail: "horloges_desynchronisees", drift_s: -150 },
      },
    });

    fireEvent.click(await screen.findByRole("button", { name: "Submit the code" }));

    expect(await screen.findByText(/clocks differ by about 150 seconds/i)).toBeInTheDocument();
  });

  it("says rejected and expired differently, and offers to start again", async () => {
    monte(etatRoute({ state: "refusee", attempt: TENTATIVE, peer: null }));

    expect(await screen.findByText("Request rejected")).toBeInTheDocument();
    expect(await screen.findByText(/rejected the request/i)).toBeInTheDocument();
    // Le formulaire revient : c'est ce qui permet de recommencer.
    expect(screen.getByLabelText("Enrolment module URL")).toBeInTheDocument();
  });

  it("does not take an unreachable peer for a rejection", async () => {
    monte(etatRoute({ state: "pair_injoignable", attempt: TENTATIVE, peer: null }));

    expect(await screen.findByText(/neither rejected nor lost/i)).toBeInTheDocument();
    // Toujours en attente : on ne propose pas de recommencer pour une panne de réseau.
    expect(screen.getByLabelText("Six-digit code")).toBeInTheDocument();
    expect(screen.queryByLabelText("Enrolment module URL")).toBeNull();
  });

  it("shows only one address when the peer is reached where it names itself", async () => {
    // Deux lignes identiques feraient chercher une différence qui n'existe pas.
    monte(etatRoute({ state: "apparie", attempt: null, peer: PAIR }));

    expect(await screen.findByText(ENROLEMENT)).toBeInTheDocument();
    expect(screen.queryByText("Reached at")).toBeNull();
  });

  it("shows the contact address, and why it differs, when it is not the peer's identity", async () => {
    // Un intermédiaire s'est interposé : l'écran aurait l'air de se contredire s'il
    // montrait deux adresses sans dire laquelle sert à quoi.
    const CONTACT = "http://100.74.9.236:8081";
    monte(etatRoute({ state: "apparie", attempt: null, peer: { ...PAIR, contact_url: CONTACT } }));

    expect(await screen.findByText(CONTACT)).toBeInTheDocument();
    expect(screen.getByText(ENROLEMENT)).toBeInTheDocument();
    expect(screen.getByText(/part of no signature/i)).toBeInTheDocument();
  });

  it("names the revocation and its date once the enrolment module has told us", async () => {
    // Le message vague — « son administrateur a PU révoquer, ou les clés ne correspondent
    // plus » — était le symptôme d'un module qui devait deviner. Averti, il nomme.
    monte(
      etatRoute({
        state: "revoque",
        attempt: null,
        peer: { ...PAIR, revoked_at: "2026-10-29T07:21:00+00:00" },
      }),
    );

    expect(await screen.findByText(/revoked this access/i)).toBeInTheDocument();
    expect(screen.getByText(/no longer of any use/i)).toBeInTheDocument();
    // L'appariement reste affiché, et refrapper reste possible.
    expect(screen.getByText(PAIR.public_key_fingerprint)).toBeInTheDocument();
    expect(screen.getByLabelText("Enrolment module URL")).toBeInTheDocument();
  });

  it("says the enrolment module refuses us, keeps the pairing shown, and offers to knock again", async () => {
    // Critère 6 du ticket d5ffeb33 : une stack révoquée doit le CONSTATER. Le pair ne
    // l'appelle jamais ; le seul signal est qu'il refuse ses appels signés.
    monte(etatRoute({ state: "refuse_par_le_pair", attempt: null, peer: PAIR }));

    expect(await screen.findByText(/no longer accepts our signed calls/i)).toBeInTheDocument();
    // L'appariement reste affiché : son empreinte est ce qu'on voudra comparer après
    // avoir refrappé. On ne l'efface pas sur la foi d'une réponse distante.
    expect(screen.getByText(PAIR.public_key_fingerprint)).toBeInTheDocument();
    // Et refrapper est possible : c'est la seconde moitié du critère.
    expect(screen.getByLabelText("Enrolment module URL")).toBeInTheDocument();
  });

  it("shows the pairing and warns before replacing it", async () => {
    const appels = monte({
      ...etatRoute({ state: "apparie", attempt: null, peer: PAIR }),
      "POST /api/identity/pairing": { status: 202, body: TENTATIVE },
    });

    expect(await screen.findByText("Paired")).toBeInTheDocument();
    expect(screen.getByText(PAIR.public_key_fingerprint)).toBeInTheDocument();
    // Un seul appariement : aucun moyen d'en AJOUTER un second, seulement de remplacer.
    expect(screen.queryByRole("button", { name: "Send the request" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Replace the pairing" }));
    const dialogue = within(screen.getByRole("dialog"));
    // Le libellé NEUTRE du socle : ce que le produit perd, c'est le produit qui le dit,
    // en redéfinissant `peering.repair.body` dans ses propres libellés.
    expect(
      dialogue.getByText(/will no longer come from it/i),
    ).toBeInTheDocument();
    // Tant qu'on n'a pas confirmé, rien n'est envoyé.
    expect(appels.some((appel) => appel.key === "POST /api/identity/pairing")).toBe(false);

    fireEvent.click(dialogue.getByRole("button", { name: "Replace" }));

    await waitFor(() =>
      expect(appels.some((appel) => appel.key === "POST /api/identity/pairing")).toBe(true),
    );
  });
});
