# This is meant to be run on the machine that will host the Postgres instance

# 1) Clone pg_textsearch extension code
mkdir -p ~/andromeda-bm25 && cd ~/andromeda-bm25
git clone https://github.com/timescale/pg_textsearch.git

# 2) Create Dockerfile
cat > Dockerfile.pgvector-pgtextsearch <<'EOF'
FROM pgvector/pgvector:pg17

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git ca-certificates postgresql-server-dev-17 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp
COPY pg_textsearch /tmp/pg_textsearch
RUN cd /tmp/pg_textsearch && make && make install && rm -rf /tmp/pg_textsearch
EOF

# 3) Build image
docker build -t andromeda-pg:pg17-bm25 -f Dockerfile.pgvector-pgtextsearch .

# 4) Replace old container (no data preservation)
docker rm -f andromeda-pg 2>/dev/null || true
docker run --name andromeda-pg \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=andromeda \
  -p 5432:5432 \
  -d andromeda-pg:pg17-bm25

# 5) Wait for Postgres to be ready
until docker exec andromeda-pg pg_isready -U postgres -d andromeda >/dev/null 2>&1; do
  sleep 1
done

# 5) Enable extensions
docker exec andromeda-pg psql -U postgres -d andromeda -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker exec andromeda-pg psql -U postgres -d andromeda -c "CREATE EXTENSION IF NOT EXISTS pg_textsearch;"

# 6) Verify
docker exec andromeda-pg psql -U postgres -d andromeda -c "\dx"
# You should see this output
#                                  List of installed extensions
#      Name      |  Version  |   Schema   |                     Description                      
# ---------------+-----------+------------+------------------------------------------------------
#  pg_textsearch | 1.0.0-dev | public     | Full-text search with BM25 ranking
#  plpgsql       | 1.0       | pg_catalog | PL/pgSQL procedural language
#  vector        | 0.8.1     | public     | vector data type and ivfflat and hnsw access methods
# (3 rows)
