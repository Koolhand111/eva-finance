# EVA-Finance Makefile
# Convenience targets for common operations

.PHONY: help up down logs db-shell ingest-reddit clean

# Default target
help:
	@echo "EVA-Finance Makefile"
	@echo ""
	@echo "Available targets:"
	@echo "  help            Show this help message"
	@echo "  up              Start all Docker containers"
	@echo "  down            Stop all Docker containers"
	@echo "  logs            Tail logs from all containers"
	@echo "  db-shell        Open PostgreSQL shell"
	@echo "  ingest-reddit   Run Reddit ingestion job"
	@echo "  clean           Remove logs and temporary files"
	@echo ""
	@echo "Examples:"
	@echo "  make up"
	@echo "  make ingest-reddit"
	@echo "  make ingest-reddit SUBREDDITS=BuyItForLife,Frugal LIMIT=50"
	@echo "  make db-shell"

# Docker operations
up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

restart:
	docker-compose restart

# Database access
db-shell:
	docker exec -it eva_db psql -U eva_user -d eva_db

# Reddit ingestion
SUBREDDITS ?= BuyItForLife,Frugal,running
LIMIT ?= 25
DEBUG ?=

ingest-reddit:
	@echo "Running Reddit ingestion..."
	@echo "Subreddits: $(SUBREDDITS)"
	@echo "Limit: $(LIMIT)"
	@echo ""
	docker exec eva_worker python3 -m eva_ingest.reddit_posts \
		--subreddits $(SUBREDDITS) \
		--limit $(LIMIT) \
		$(if $(DEBUG),--debug,)

# Ingestion from host (for testing)
ingest-reddit-local:
	@echo "Running Reddit ingestion from host..."
	@echo "Note: Using localhost:9080 for EVA API"
	python -m eva_ingest.reddit_posts \
		--subreddits $(SUBREDDITS) \
		--limit $(LIMIT) \
		--eva-api-url http://localhost:9080/intake/message \
		$(if $(DEBUG),--debug,)

# Query recent Reddit posts
db-query-reddit:
	@echo "Querying recent Reddit posts..."
	docker exec -it eva_db psql -U eva_user -d eva_db -c \
		"SELECT id, platform_id, LEFT(text, 50) as text_preview, meta->>'subreddit' as subreddit, created_at FROM raw_messages WHERE source = 'reddit' ORDER BY created_at DESC LIMIT 10;"

# Check processing status
db-check-status:
	@echo "Checking processing status..."
	docker exec -it eva_db psql -U eva_user -d eva_db -c \
		"SELECT COUNT(*) FILTER (WHERE processed = TRUE) as processed, COUNT(*) FILTER (WHERE processed = FALSE) as unprocessed, COUNT(*) as total FROM raw_messages WHERE source = 'reddit';"

# Clean up
clean:
	@echo "Cleaning logs and temporary files..."
	rm -f logs/*.log
	rm -f backtest_*.csv backtest_*.json
	@echo "Done"

# Development helpers
check-containers:
	@echo "Checking container status..."
	docker ps --filter "name=eva_" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

check-health:
	@echo "Checking EVA API health..."
	@curl -s http://localhost:9080/health | python -m json.tool || echo "EVA API not reachable"
