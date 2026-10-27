/** Ce qui remplace Swagger UI dans les tests : il ne tourne pas sous jsdom.
 *
 * Le document reçu est affiché en texte, ce qui permet de vérifier ce que l'écran a
 * RÉELLEMENT demandé au serveur — c'est la seule chose qui nous intéresse ici, le rendu
 * étant celui de Swagger UI et pas le nôtre.
 */
export default function SwaggerViewStub({ spec }: { spec: object }) {
  return <pre data-testid="swagger-spec">{JSON.stringify(spec)}</pre>;
}
