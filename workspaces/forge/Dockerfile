FROM node:26-slim AS deps
RUN npm install --global pnpm@12.4.1
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
RUN pnpm install --prod --frozen-lockfile

FROM node:26-slim
ENV NODE_ENV=production
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY package.json ./
RUN mkdir dead_letters data && chown node:node dead_letters data
USER node
ENTRYPOINT ["node", "--liftoff-only", "src/cli.ts"]
