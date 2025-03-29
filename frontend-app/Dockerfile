FROM python:3.10-slim

WORKDIR /app

# Installa le dipendenze di sistema necessarie
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copia i file dei requisiti
COPY requirements.txt .

# Installa le dipendenze Python
RUN pip install --no-cache-dir -r requirements.txt

# Crea le directory necessarie
RUN mkdir -p templates static static/css static/js static/img

# Copia i file dell'applicazione
COPY app.py salesforce_agent.py ./
COPY templates/ templates/
COPY static/ static/

# Variabili d'ambiente
ENV PORT=8000
ENV MODEL_PATH="llama3-8b-instruct"
ENV QUANTIZE="True"
ENV DEBUG="False"

# Esponi la porta
EXPOSE 8000

# Comando di avvio
CMD ["python", "app.py"]
