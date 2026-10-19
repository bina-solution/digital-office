# node:22-slim, not node:22.17 — the full image carries a complete build toolchain and
# ~1.12GB of it was pure overhead here (the app itself is ~1MB). Same Debian base, so
# poppler-utils and the prebuilt native modules (sharp, sqlite3) still resolve.
FROM node:22-slim

WORKDIR /app

# Install system deps for PDF thumbnails (pdftoppm from poppler-utils) and clean cache
RUN apt-get update \
	&& apt-get install -y --no-install-recommends poppler-utils \
	&& rm -rf /var/lib/apt/lists/*

ENV NODE_ENV=production

COPY package*.json ./
RUN npm install --omit=dev \
	&& npm cache clean --force

COPY . .

EXPOSE 3000
CMD ["npm", "start"]
