FROM python:3.13-slim

WORKDIR /app

# Install system deps needed by psycopg2-binary (none extra needed for slim)
# Copy project files
COPY pyproject.toml ./
COPY kungfu_chess/ ./kungfu_chess/
COPY server.json ./

# Install the package with postgres + redis extras
RUN pip install --no-cache-dir -e ".[postgres,redis]"

# Server listens on this port (overridable via SERVER_PORT env / server.json)
EXPOSE 8765

CMD ["python", "-m", "kungfu_chess.server.main"]
