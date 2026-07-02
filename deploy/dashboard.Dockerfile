FROM node:20-alpine AS deps
WORKDIR /app/dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app/dashboard
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/dashboard/node_modules ./node_modules
COPY dashboard ./
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app/dashboard
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
COPY --from=builder /app/dashboard ./
EXPOSE 3000
CMD ["npm", "run", "start"]

