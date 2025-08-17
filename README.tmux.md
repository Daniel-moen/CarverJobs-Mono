# CarverJobs Development Environment with tmux

This setup runs both the Svelte frontend and Go backend in separate tmux panes within a single Docker container, giving you the best of both worlds: separation of concerns while keeping everything in one container.

## Architecture

- **Single Container**: One Docker container runs both services
- **tmux Sessions**: Frontend and backend run in separate tmux panes
- **Process Separation**: Each service runs independently and can be restarted separately
- **Hot Reloading**: Both services support hot reloading via volume mounts
- **Port Mapping**: Frontend on 5173, Backend on 8080

## Quick Start

1. **Build and start the environment:**
   ```bash
   make -f Makefile.tmux dev-up
   ```

2. **View the running services:**
   ```bash
   make -f Makefile.tmux dev-attach
   ```

3. **Access your applications:**
   - Frontend: http://localhost:5173
   - Backend API: http://localhost:8080

## Available Commands

```bash
# Start services
make -f Makefile.tmux dev-up

# Stop services  
make -f Makefile.tmux dev-down

# Build container
make -f Makefile.tmux dev-build

# Attach to tmux session (see both services)
make -f Makefile.tmux dev-attach

# View only frontend logs
make -f Makefile.tmux dev-frontend

# View only backend logs
make -f Makefile.tmux dev-backend

# Restart frontend only
make -f Makefile.tmux restart-frontend

# Restart backend only  
make -f Makefile.tmux restart-backend

# Full restart
make -f Makefile.tmux dev-restart

# Open shell in container
make -f Makefile.tmux dev-shell

# Show container logs
make -f Makefile.tmux dev-logs
```

## tmux Navigation

When you attach to the tmux session (`make -f Makefile.tmux dev-attach`), you'll see both services running side by side:

- **Left pane**: Svelte frontend (port 5173)
- **Right pane**: Go backend (port 8080)

### tmux Keyboard Shortcuts

- `Ctrl+B` then `←/→`: Switch between panes
- `Ctrl+B` then `d`: Detach from tmux (container keeps running)
- `Ctrl+B` then `|`: Split pane vertically
- `Ctrl+B` then `-`: Split pane horizontally
- `Ctrl+B` then `c`: Create new window
- `Ctrl+B` then `n/p`: Next/previous window

### Direct Commands

You can also run commands directly in specific panes:

```bash
# Send command to frontend pane
docker exec -it carverjobs-dev tmux send-keys -t dev:0.0 'npm run build' C-m

# Send command to backend pane  
docker exec -it carverjobs-dev tmux send-keys -t dev:0.1 'go test ./...' C-m
```

## Development Workflow

1. **Start the environment**: `make -f Makefile.tmux dev-up`
2. **Attach to tmux**: `make -f Makefile.tmux dev-attach`
3. **Make code changes**: Edit files in `./frontend/` or `./backend/`
4. **Hot reloading**: Both services automatically reload on changes
5. **Switch panes**: Use `Ctrl+B` + arrow keys to see different logs
6. **Individual restarts**: If needed, restart services individually
7. **Detach when done**: `Ctrl+B` then `d`

## Troubleshooting

### Container not starting
```bash
make -f Makefile.tmux dev-logs
```

### Services not responding
```bash
# Check if both panes are running
make -f Makefile.tmux dev-attach

# Restart individual services
make -f Makefile.tmux restart-frontend
make -f Makefile.tmux restart-backend
```

### Full reset
```bash
make -f Makefile.tmux dev-down
docker system prune -f
make -f Makefile.tmux dev-build
make -f Makefile.tmux dev-up
```

## Environment Variables

The container uses these environment variables:

**Frontend:**
- `VITE_API_URL=http://localhost:8080`

**Backend:**
- `DATABASE_URL=postgresql://...` (your Railway DB)
- `PORT=8080`

## File Structure

```
├── Dockerfile.tmux           # Main Dockerfile
├── docker-compose.tmux.yml   # Docker compose config
├── tmux.conf                 # tmux configuration
├── start-services.sh         # Startup script
├── Makefile.tmux            # Convenient commands
└── README.tmux.md           # This file
```

## Benefits of This Setup

1. **Single container**: Easier to manage than multiple containers
2. **Process separation**: Each service can be restarted independently
3. **Logging**: Easy to view logs for both services or individually  
4. **Hot reloading**: Both frontend and backend reload on file changes
5. **tmux power**: Full terminal multiplexing capabilities
6. **Resource efficient**: One container instead of two
