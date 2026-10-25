# Stage 1: build the React app (static files in /app/dist)
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./

RUN npm ci

COPY . .

# Empty on purpose: the app calls relative /api paths and the ALB routes them to the backend
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# Stage 2: serve the static build. nginx-unprivileged runs as uid 101 on port 8080 and writes
# only to /tmp, so it works with the pod's runAsNonRoot + readOnlyRootFilesystem + drop ALL.
FROM nginxinc/nginx-unprivileged:1.30-alpine

# Pull in Alpine security fixes released since the image was last rebuilt (Trivy gate in CI)
USER root
RUN apk upgrade --no-cache
USER 101

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
