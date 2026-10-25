/**
 * Swagger UI ne publie pas de types pour son bundle ES. On déclare ce qu'on en utilise,
 * et rien de plus : un `any` global masquerait une faute d'appel.
 */
declare module "swagger-ui-dist/swagger-ui-es-bundle.js" {
  interface SwaggerUIOptions {
    domNode: HTMLElement;
    spec: object;
    supportedSubmitMethods?: string[];
    deepLinking?: boolean;
  }
  export default function SwaggerUI(options: SwaggerUIOptions): unknown;
}

declare module "swagger-ui-dist/swagger-ui.css";
