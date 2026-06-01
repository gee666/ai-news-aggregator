FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PI_CODING_AGENT_DIR=/root/.pi/agent \
    PI_TELEMETRY=0

WORKDIR /app

# System deps + Node.js (required to run the pi coding agent).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl ca-certificates gnupg git \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g npm@latest \
    && rm -rf /var/lib/apt/lists/*

# Install the latest pi coding agent and required extensions.
RUN npm install -g @earendil-works/pi-coding-agent@latest \
    && pi install npm:oira666_pi-limits-wait \
    && pi install npm:oira666_pi-web-search \
    && pi list

COPY . .
RUN pip install --upgrade pip \
    && pip install -e ".[models,bot,collectors]"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
