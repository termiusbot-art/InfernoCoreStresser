FROM python:3.11-slim

WORKDIR /app

# Install only SSH client (for VPS connections)
RUN apt-get update && apt-get install -y \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/keys /app/backups
RUN chmod +x ultimate

EXPOSE 8080

CMD gunicorn -w 4 -b 0.0.0.0:$PORT app:app