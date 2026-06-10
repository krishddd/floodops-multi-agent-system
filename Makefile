# FloodOps — developer task runner.
.PHONY: dev test lint format build up down security install

install:        ## Install backend + frontend deps
	cd backend && pip install -r requirements.txt && pip install ruff mypy bandit pytest pytest-asyncio pytest-cov
	cd frontend && npm install

dev:            ## Run backend (uvicorn) — frontend: `npm run dev --prefix frontend`
	cd backend && uvicorn floodops.api.app:create_app --factory --reload --port 8000

test:           ## Run backend + frontend test suites
	cd backend && pytest -q
	cd frontend && npm test

lint:           ## Lint backend (ruff) + frontend (eslint); mypy advisory
	cd backend && ruff check floodops && (mypy floodops || true)
	cd frontend && npm run lint

format:         ## Auto-format backend (ruff) + frontend (prettier)
	cd backend && ruff check floodops --fix
	cd frontend && npm run format

security:       ## Security gate — bandit HIGH + npm audit high (blocking)
	cd backend && bandit -r floodops -lll
	cd frontend && npm audit --omit=dev --audit-level=high

build:          ## Build frontend production bundle
	cd frontend && npm run build

up:             ## Start the full stack via docker compose
	docker compose up --build

down:           ## Stop the stack
	docker compose down
