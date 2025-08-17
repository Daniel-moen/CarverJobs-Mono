#!/bin/bash

# Function to handle graceful shutdown
cleanup() {
    echo "Shutting down services..."
    tmux kill-server 2>/dev/null || true
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT

echo "Starting development environment with tmux..."

# Start tmux in detached mode
tmux new-session -d -s dev 'echo "Development environment starting..."'

# Split the window into two panes
tmux split-window -h -t dev

# Run frontend in the left pane (pane 0)
tmux send-keys -t dev:0.0 'cd /app/frontend' C-m
tmux send-keys -t dev:0.0 'echo "Starting Svelte frontend on port 5173..."' C-m
tmux send-keys -t dev:0.0 'npm run dev -- --host 0.0.0.0 --port 5173' C-m

# Run backend in the right pane (pane 1)
tmux send-keys -t dev:0.1 'cd /app/backend' C-m
tmux send-keys -t dev:0.1 'echo "Starting Go backend on port 8080..."' C-m
tmux send-keys -t dev:0.1 'go run cmd/server/main.go' C-m

# Set pane titles
tmux select-pane -t dev:0.0 -T "Frontend (Svelte)"
tmux select-pane -t dev:0.1 -T "Backend (Go)"

# Enable pane titles
tmux set -g pane-border-status top
tmux set -g pane-border-format "#{pane_title}"

echo "Services started in tmux session 'dev'"
echo "Frontend: http://localhost:5173"
echo "Backend:  http://localhost:8080"
echo ""
echo "To attach to tmux session: docker exec -it <container_name> tmux attach -t dev"
echo "To view logs, attach to tmux and switch between panes with Ctrl+B then arrow keys"

# Keep the script running by attaching to tmux
tmux attach -t dev
