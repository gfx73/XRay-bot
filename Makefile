.PHONY: up down logs restart build shell

up:
	@touch users.db
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f bot

restart:
	docker compose restart bot

build:
	docker compose build --no-cache

shell:
	docker compose exec bot sh
