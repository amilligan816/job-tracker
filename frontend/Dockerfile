# syntax=docker/dockerfile:1
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci


# --- dev --------------------------------------------------------------------
# Source arrives via the compose bind mount; node_modules is kept by an
# anonymous volume declared in docker-compose.yml.
FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]


# --- build + serve ----------------------------------------------------------
FROM deps AS build
COPY . .
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
