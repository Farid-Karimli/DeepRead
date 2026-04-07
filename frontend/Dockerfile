FROM node:22-alpine AS build

RUN corepack enable && corepack prepare pnpm@9 --activate

WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

# Browser calls this URL (host port mapped in docker-compose)
ARG VITE_API_URL=https://server-871113564150.us-east1.run.app
ENV VITE_API_URL=$VITE_API_URL

RUN pnpm exec vite build

FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
