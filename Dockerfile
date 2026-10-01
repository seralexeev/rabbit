FROM node:26-alpine AS deps
RUN npm install --global pnpm@12.4.1
WORKDIR /app
COPY package.json pnpm-lock.yaml .npmrc ./
RUN pnpm install --prod --frozen-lockfile

FROM node:26-alpine
ENV NODE_ENV=production
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY package.json ./
COPY src ./src
COPY clickhouse ./clickhouse
COPY slabs ./slabs
COPY graph ./graph
RUN mkdir dead_letters && chown node:node dead_letters
USER node
ENTRYPOINT ["node", "src/cli.ts"]
