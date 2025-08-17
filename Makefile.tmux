.PHONY: dev-up dev-down dev-build dev-logs dev-shell dev-attach dev-frontend dev-backend

# Start the development environment
dev-up:
	@echo "Starting development environment..."
	docker-compose -f docker-compose.tmux.yml up -d

# Stop the development environment  
dev-down:
	@echo "Stopping development environment..."
	docker-compose -f docker-compose.tmux.yml down

# Build the development environment
dev-build:
	@echo "Building development environment..."
	docker-compose -f docker-compose.tmux.yml build

# Show container logs
dev-logs:
	docker-compose -f docker-compose.tmux.yml logs -f

# Open a shell in the container
dev-shell:
	docker exec -it carverjobs-dev /bin/bash

# Attach to the tmux session to see both services
dev-attach:
	@echo "Attaching to tmux session..."
	@echo "Use Ctrl+B then arrow keys to switch between panes"
	@echo "Use Ctrl+B then d to detach from tmux"
	@echo "Press Ctrl+C to exit this command"
	docker exec -it carverjobs-dev tmux attach -t dev

# View only frontend logs (left pane)
dev-frontend:
	@echo "Showing frontend pane..."
	docker exec -it carverjobs-dev tmux select-pane -t dev:0.0
	docker exec -it carverjobs-dev tmux attach -t dev

# View only backend logs (right pane)  
dev-backend:
	@echo "Showing backend pane..."
	docker exec -it carverjobs-dev tmux select-pane -t dev:0.1
	docker exec -it carverjobs-dev tmux attach -t dev

# Restart just the frontend service
restart-frontend:
	docker exec -it carverjobs-dev tmux send-keys -t dev:0.0 C-c
	docker exec -it carverjobs-dev tmux send-keys -t dev:0.0 'npm run dev -- --host 0.0.0.0 --port 5173' C-m

# Restart just the backend service
restart-backend:
	docker exec -it carverjobs-dev tmux send-keys -t dev:0.1 C-c  
	docker exec -it carverjobs-dev tmux send-keys -t dev:0.1 'go run cmd/server/main.go' C-m

# Full restart - rebuild and start
dev-restart: dev-down dev-build dev-up

# Show help
help:
	@echo "Available commands:"
	@echo "  dev-up        - Start the development environment"
	@echo "  dev-down      - Stop the development environment" 
	@echo "  dev-build     - Build the development environment"
	@echo "  dev-logs      - Show container logs"
	@echo "  dev-shell     - Open shell in container"
	@echo "  dev-attach    - Attach to tmux session"
	@echo "  dev-frontend  - View frontend pane"
	@echo "  dev-backend   - View backend pane"
	@echo "  restart-frontend - Restart only frontend"
	@echo "  restart-backend  - Restart only backend"
	@echo "  dev-restart   - Full restart with rebuild"
