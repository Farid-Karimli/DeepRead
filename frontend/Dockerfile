FROM node:22-alpine AS build

RUN corepack enable && corepack prepare pnpm@9.15.9 --activate

WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

# Nginx proxies this same-origin path to the private API container.
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL

# Vite transpiles the application for production. The repository's separate
# `tsc -b` check currently also type-checks legacy source shipped by
# @allenai/pdf-components, so keep that check outside the image build.
RUN pnpm exec vite build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
