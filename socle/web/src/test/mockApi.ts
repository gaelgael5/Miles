export type Route = { status: number; body?: unknown };
export type Routes = Record<string, Route | Route[]>;

/**
 * Doublure des APPELS d'API par « MÉTHODE chemin » ; une liste rejoue ses réponses dans
 * l'ordre. `fetch` ET `XMLHttpRequest` sont doublés, sur la même table de routes.
 */
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

/**
 * La réponse simulée d'une clé, ou `undefined` si la route n'est pas déclarée.
 *
 * Partagée par les deux transports doublés depuis le 07/11/2026 : `fetch` et
 * `XMLHttpRequest` doivent résoudre la MÊME table, sinon un écran qui change de transport
 * trouve ses routes simulées d'un côté et « non simulée » de l'autre.
 */
function routeOf(routes: Routes, key: string): Route | undefined {
  // La clé EXACTE d'abord, puis la même sans la chaîne de requête. Sans ce second
  // essai, un écran qui passe des paramètres d'URL — une culture, un filtre — ne
  // serait simulable qu'en recopiant la chaîne caractère par caractère dans chaque
  // test, et un paramètre ajouté les ferait tous tomber sur « route non simulée »,
  // message qui ne parle pas de la cause. Les clés exactes déjà écrites continuent
  // de primer, donc rien de l'existant ne change de sens.
  const entry = routes[key] ?? routes[key.split("?")[0] as string];
  return Array.isArray(entry) ? (entry.length > 1 ? entry.shift() : entry[0]) : entry;
}

/**
 * Doublure d'`XMLHttpRequest`, pour les envois dont on montre la PROGRESSION.
 *
 * Elle existe parce que `fetch()` ne rapporte pas la progression d'un envoi : l'écran
 * d'essai du module d'environnement passe donc par `XMLHttpRequest` pour déposer un
 * document (story `1a3fc5a7`). Sans cette doublure, ses tests partiraient sur le vrai
 * objet de jsdom, qui tenterait un appel réseau et échouerait en désignant une cause qui
 * n'a rien à voir.
 *
 * La progression est émise en DEUX temps — la moitié, puis le tout — pour qu'un test
 * puisse distinguer un envoi en cours d'un envoi fini. La réponse, elle, arrive
 * synchroniquement dans `send` : un test qui veut observer la barre à mi-chemin éprouve le
 * composant avec sa progression en propriété, pas le transport.
 */
function fauxEnvoi(routes: Routes, calls: { key: string; body: unknown }[]) {
  return class FauxEnvoi extends EventTarget {
    status = 0;
    responseText = "";
    readonly upload = new EventTarget();
    private key = "";

    open(method: string, path: string): void {
      this.key = `${method} ${path}`;
    }

    setRequestHeader(): void {
      // Les en-têtes ne sont pas relus par les tests : ce qu'ils éprouvent est la route
      // atteinte et le corps envoyé. Déclarée parce que l'appelant l'appelle.
    }

    send(body?: unknown): void {
      calls.push({ key: this.key, body });
      const taille = body instanceof Blob ? body.size : 0;
      for (const loaded of [Math.floor(taille / 2), taille]) {
        this.upload.dispatchEvent(
          new ProgressEvent("progress", { lengthComputable: true, loaded, total: taille }),
        );
      }
      const route = routeOf(routes, this.key);
      if (route === undefined) {
        // Pas de `status` : une panne de transport n'en a pas, et c'est ce que l'appelant
        // doit distinguer d'un refus. Le message, lui, part dans la console du test.
        this.dispatchEvent(new Event("error"));
        return;
      }
      this.status = route.status;
      this.responseText = route.status === 204 ? "" : JSON.stringify(route.body ?? {});
      this.dispatchEvent(new Event("load"));
    }

    abort(): void {
      this.dispatchEvent(new Event("abort"));
    }
  };
}

export function mockApi(routes: Routes) {
  const calls: { key: string; body: unknown }[] = [];
  vi.stubGlobal("XMLHttpRequest", fauxEnvoi(routes, calls));
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${path}`;
      calls.push({ key, body: bodyOf(init?.body) });
      const route = routeOf(routes, key);
      if (route === undefined) {
        return Promise.reject(new Error(`route non simulée : ${key}`));
      }
      const body = route.status === 204 ? null : JSON.stringify(route.body ?? {});
      return Promise.resolve(new Response(body, { status: route.status }));
    }),
  );
  return calls;
}
