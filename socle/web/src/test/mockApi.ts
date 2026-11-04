export type Route = { status: number; body?: unknown };
export type Routes = Record<string, Route | Route[]>;

/** Doublure de fetch par « MÉTHODE chemin » ; une liste rejoue ses réponses dans l'ordre. */
/**
 * Le corps tel qu'un test le relira : du JSON décodé, ou la valeur telle quelle.
 *
 * Telle quelle dès qu'elle n'est pas une chaîne — un `File` déposé en mode gros fichier,
 * par exemple (story 0f14adbd). La décoder sans condition JETAIT, et l'exception
 * remontait en « route non simulée » sur une route qui l'était : le test échouait en
 * désignant la mauvaise cause. Une chaîne qui n'est pas du JSON est rendue telle quelle
 * pour la même raison.
 */
function bodyOf(body: RequestInit["body"]): unknown {
  if (body === undefined || body === null) {
    return undefined;
  }
  if (typeof body !== "string") {
    return body;
  }
  try {
    return JSON.parse(body);
  } catch {
    return body;
  }
}

export function mockApi(routes: Routes) {
  const calls: { key: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${path}`;
      calls.push({ key, body: bodyOf(init?.body) });
      // La clé EXACTE d'abord, puis la même sans la chaîne de requête. Sans ce second
      // essai, un écran qui passe des paramètres d'URL — une culture, un filtre — ne
      // serait simulable qu'en recopiant la chaîne caractère par caractère dans chaque
      // test, et un paramètre ajouté les ferait tous tomber sur « route non simulée »,
      // message qui ne parle pas de la cause. Les clés exactes déjà écrites continuent
      // de primer, donc rien de l'existant ne change de sens.
      const entry = routes[key] ?? routes[key.split("?")[0] as string];
      const route = Array.isArray(entry) ? (entry.length > 1 ? entry.shift() : entry[0]) : entry;
      if (route === undefined) {
        return Promise.reject(new Error(`route non simulée : ${key}`));
      }
      const body = route.status === 204 ? null : JSON.stringify(route.body ?? {});
      return Promise.resolve(new Response(body, { status: route.status }));
    }),
  );
  return calls;
}
