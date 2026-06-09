# FloodOps frontend — dev server (Vite) with proxy to the backend service.
# Phase D hardens this into a multi-stage build → static server.
FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .

EXPOSE 5173

# BACKEND_URL (compose-injected) points the vite proxy at the backend container.
ENV BACKEND_URL=http://backend:8000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
