import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";

import "../i18n/i18n";
import { type Routes, mockApi } from "@miles/socle-web/testing";
import { CATALOGUE, WORKSPACE_CULTURES } from "./workspaceFixtures";
import { WorkspaceCulturesCard } from "./WorkspaceCultures";

const CULTURES = "/api/workspaces/retrait/cultures";
const DIRS = { "fr-FR": "ltr", "ar-MA": "rtl", "th-TH": "ltr" };
const BASE: Routes = {
  "GET /api/cultures": { status: 200, body: CATALOGUE },
  [`GET ${CULTURES}`]: { status: 200, body: WORKSPACE_CULTURES },
};

function renderCard(routes: Routes = {}) {
  const calls = mockApi({ ...BASE, ...routes });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <WorkspaceCulturesCard workspaceId="retrait" />
    </QueryClientProvider>,
  );
  return calls;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WorkspaceCulturesCard", () => {
  it("shows the default culture first, apart from the additional ones", async () => {
    const calls = renderCard();

    expect(await screen.findByText("fr-FR")).toBeInTheDocument();
    expect(screen.getByText("Default")).toBeInTheDocument();
    expect(screen.getByText("ar-MA")).toBeInTheDocument();
    const codes = [...document.querySelectorAll("code")].map((e) => e.textContent);
    expect(codes).toEqual(["fr-FR", "ar-MA"]);
    expect(calls.some((c) => c.key === `GET ${CULTURES}`)).toBe(true);
  });

  it("adds an additional culture chosen from the whole catalogue", async () => {
    const calls = renderCard({
      [`GET ${CULTURES}`]: [
        { status: 200, body: WORKSPACE_CULTURES },
        { status: 200, body: { default: "fr-FR", additional: ["ar-MA", "th-TH"], directions: DIRS } },
      ],
      [`POST ${CULTURES}`]: {
        status: 200,
        body: { default: "fr-FR", additional: ["ar-MA", "th-TH"], directions: DIRS },
      },
    });
    await screen.findByText("ar-MA");

    // th-TH n'est pas active dans l'application, et se propose quand même (critère 9).
    fireEvent.click(await screen.findByRole("button", { name: /th-TH/ }));
    fireEvent.click(screen.getByText("Add"));

    expect(await screen.findByText("th-TH")).toBeInTheDocument();
    expect(calls.find((c) => c.key === `POST ${CULTURES}`)?.body).toEqual({ culture: "th-TH" });
  });

  it("does not offer a culture the workspace already holds", async () => {
    renderCard();
    await screen.findByText("ar-MA");

    await screen.findByRole("button", { name: /th-TH/ });
    expect(screen.queryByRole("button", { name: /ar-MA/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /fr-FR/ })).not.toBeInTheDocument();
  });

  it("says how many keys are missing when the default culture cannot change yet", async () => {
    renderCard({
      [`PUT ${CULTURES}/default`]: {
        status: 409,
        body: { detail: { code: "culture_defaut_incomplete", culture: "ar-MA", missing: 12 } },
      },
    });
    await screen.findByText("ar-MA");

    fireEvent.click(screen.getByText("Make default"));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("12 key(s) have no value in ar-MA");
  });

  it("changes the default culture, the former one staying as an additional", async () => {
    const calls = renderCard({
      [`GET ${CULTURES}`]: [
        { status: 200, body: WORKSPACE_CULTURES },
        { status: 200, body: { default: "ar-MA", additional: ["fr-FR"], directions: DIRS } },
      ],
      [`PUT ${CULTURES}/default`]: {
        status: 200,
        body: { default: "ar-MA", additional: ["fr-FR"], directions: DIRS },
      },
    });
    await screen.findByText("ar-MA");

    fireEvent.click(screen.getByText("Make default"));

    await screen.findByText("fr-FR");
    const codes = [...document.querySelectorAll("code")].map((e) => e.textContent);
    expect(codes).toEqual(["ar-MA", "fr-FR"]);
    expect(calls.find((c) => c.key === `PUT ${CULTURES}/default`)?.body).toEqual({
      culture: "ar-MA",
    });
  });

  it("says the files are kept before confirming a removal", async () => {
    const calls = renderCard({
      [`GET ${CULTURES}`]: [
        { status: 200, body: WORKSPACE_CULTURES },
        { status: 200, body: { default: "fr-FR", additional: [], directions: DIRS } },
      ],
      [`DELETE ${CULTURES}/ar-MA`]: { status: 200, body: { default: "fr-FR", additional: [], directions: DIRS } },
    });
    await screen.findByText("ar-MA");

    fireEvent.click(screen.getByText("Remove"));

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/translation files stay in the repository/);
    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));

    await vi.waitFor(() => expect(screen.queryByText("ar-MA")).not.toBeInTheDocument());
    expect(calls.some((c) => c.key === `DELETE ${CULTURES}/ar-MA`)).toBe(true);
  });

  it("offers no removal nor promotion on the default culture", async () => {
    renderCard({
      [`GET ${CULTURES}`]: { status: 200, body: { default: "fr-FR", additional: [], directions: DIRS } },
    });

    expect(await screen.findByText("fr-FR")).toBeInTheDocument();
    expect(screen.queryByText("Remove")).not.toBeInTheDocument();
    expect(screen.queryByText("Make default")).not.toBeInTheDocument();
  });

  it("names the unreadable file rather than presenting it as work to do", async () => {
    renderCard({
      [`PUT ${CULTURES}/default`]: {
        status: 422,
        body: {
          detail: {
            code: "trads_illisible",
            path: "trads/accueil/fr-FR.yaml",
            reason: "yaml illisible",
          },
        },
      },
    });
    await screen.findByText("ar-MA");

    fireEvent.click(screen.getByText("Make default"));

    expect(await screen.findByRole("alert")).toHaveTextContent("trads/accueil/fr-FR.yaml");
  });

  it("says when an added culture is not in the catalogue", async () => {
    renderCard({
      [`POST ${CULTURES}`]: {
        status: 422,
        body: { detail: { field: "culture", reason: "inconnue" } },
      },
    });
    await screen.findByText("ar-MA");
    fireEvent.click(await screen.findByRole("button", { name: /th-TH/ }));

    fireEvent.click(screen.getByText("Add"));

    expect(await screen.findByRole("alert")).toHaveTextContent("not in the catalogue");
  });

  it("says when the workspace cultures cannot be read", async () => {
    renderCard({ [`GET ${CULTURES}`]: { status: 500, body: {} } });

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be read");
  });
});
