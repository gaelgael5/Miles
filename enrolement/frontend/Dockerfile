# syntax=docker/dockerfile:1
FROM node:22-slim AS build
# L'image reproduit la disposition du dépôt — <racine>/enrolement/frontend et
# <racine>/socle/web — au lieu de bâtir dans /app. Raison : `@miles/socle-web` est déclaré
# dans package.json au chemin relatif `../../socle/web`, que npm résout depuis le
# répertoire du paquet. Depuis /app, `../..` sortirait de l'arborescence.
WORKDIR /src/enrolement/frontend
# Le socle arrive par un contexte de build additionnel, et non en élargissant le contexte
# à la racine du dépôt : l'image embarquerait sinon les autres produits.
COPY --from=socle-web . /src/socle/web
COPY package.json package-lock.json ./
RUN npm ci
# Le socle s'installe comme en local, avec SON verrou. Sans son node_modules, TypeScript
# ne résout pas `react` depuis les sources du socle : la résolution remonte depuis le
# fichier qui importe, et ces fichiers sont hors de l'arborescence du produit. Ce n'est
# que l'étape de construction — l'image finale ne copie que `dist`.
RUN npm ci --prefix /src/socle/web
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/enrolement/frontend/dist /usr/share/nginx/html
EXPOSE 80
