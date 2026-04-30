# syntax=docker/dockerfile:1.6

# ---- deps ----------------------------------------------------------------
# Install all dependencies (incl. dev deps so the build stage has TS/Tailwind).
FROM node:20-alpine AS deps
WORKDIR /app

# Build context is the repo root (both Amvera and docker-compose.prod.yml).
COPY frontend/package.json frontend/package-lock.json* ./

# Use `npm ci` when a lockfile is present (reproducible), `npm install`
# otherwise. The `--no-audit --no-fund` flags keep build logs quiet.
RUN if [ -f package-lock.json ]; then \
      npm ci --no-audit --no-fund; \
    else \
      npm install --no-audit --no-fund; \
    fi


# ---- builder -------------------------------------------------------------
FROM node:20-alpine AS builder
WORKDIR /app

# NEXT_PUBLIC_* vars are inlined at build time. Amvera does not support
# --build-arg, so the default here IS the production value for Amvera.
# VPS deploy (docker-compose.prod.yml) overrides via build.args.
# Phase 2: technical domain; Phase 4: change to https://api.stilist24.com
ARG NEXT_PUBLIC_API_URL=https://stilist24-api.expertgds.amvera.io
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ .

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build


# ---- runner --------------------------------------------------------------
# Minimal runtime image. Uses the standalone server emitted by Next 14.
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Run as a non-root user for safety.
RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 nextjs

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
