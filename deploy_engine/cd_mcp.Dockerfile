# cd_mcp query engine. Runs from /app with the source dirs on the path (the repo
# runs from cwd, not an installed wheel, and cd_mcp imports pipeline4 which is not
# in the wheel package list, so we copy sources rather than pip install the project).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY deploy_engine/requirements-mcp.txt .
RUN pip install -r requirements-mcp.txt

COPY cd_mcp ./cd_mcp
COPY ingest ./ingest
COPY embeddings ./embeddings
COPY retrieval ./retrieval
COPY pipeline2 ./pipeline2
COPY pipeline4 ./pipeline4
COPY evidence ./evidence
COPY historical ./historical
COPY questions.json ./questions.json

ENV MCP_HOST=0.0.0.0 MCP_PORT=8765
EXPOSE 8765
CMD ["python", "-m", "cd_mcp.server"]
