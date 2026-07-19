FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Runtime state (risk_state.json) is written here; mount it as a volume
# in docker-compose.yml so a container recreate doesn't lose it.
RUN mkdir -p /app/state

CMD ["python", "main.py", "run"]
