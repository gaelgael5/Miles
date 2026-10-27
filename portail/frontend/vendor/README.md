# Paquets vendus

## jsonjoy-builder-1.0.4-89529b6.tgz

Éditeur visuel de JSON Schema (story e38806f3), licence MIT.

- **Pourquoi pas npm** : la version publiée (1.0.4, 25/06/2026) ne gère pas les `$ref`,
  seule façon de désigner un autre modèle. Le support a été fusionné sur GitHub le
  02/09/2026 sans nouvelle version publiée (choix de Gael, 23/10/2026).
- **Provenance** : https://github.com/lovasoa/jsonjoy-builder, commit
  `89529b6f1d69a77861137c9e2c931af79c26b0d3` (2 septembre 2026).
- **Construction** : `git checkout 89529b6 && npm ci && npm run build && npm test`
  (105 tests réussis, 2 ignorés), puis `npm pack`.
- **À faire** : repasser sur la version npm dès qu'une version ≥ 1.0.5 publie le support
  des `$ref`, et supprimer ce fichier.
