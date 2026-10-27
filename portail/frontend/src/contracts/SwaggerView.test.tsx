import { render, screen } from "@testing-library/react";

// Le VRAI Swagger UI, pas la doublure : c'est le seul test qui vérifie que la
// bibliothèque s'installe réellement dans le nœud qu'on lui donne. Partout ailleurs
// elle est remplacée, parce qu'elle est lourde et qu'on ne teste pas son rendu.
vi.unmock("./SwaggerView");

const SPEC = {
  openapi: "3.1.0",
  info: { title: "sonde", version: "1" },
  paths: {
    "/ingest/x": {
      post: { summary: "Déposer un objet", responses: { "202": { description: "ok" } } },
    },
  },
};

describe("SwaggerView, bibliothèque réelle", () => {
  it("installs Swagger UI in its host node and renders the operation", async () => {
    const { default: SwaggerView } = await import("./SwaggerView");

    const { container } = render(<SwaggerView spec={SPEC} />);

    expect(await screen.findByText("sonde")).toBeInTheDocument();
    expect(container.querySelector(".swagger-ui")).not.toBeNull();
    expect(await screen.findByText("Déposer un objet")).toBeInTheDocument();
  });
});
