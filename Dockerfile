FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copiar e instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código fuente
COPY . .

# Crear directorio de datos persistentes
RUN mkdir -p /data

# Exponer puerto
EXPOSE 8000

# Arrancar la app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
