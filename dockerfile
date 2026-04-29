FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev \
    build-essential \
    curl \
    wget \
    unzip \
    chromium \
    chromium-driver \
    libgtk-3-0 \
    libnss3 \
    libgconf-2-4 \
    libx11-6 \
    libxext6 \
    libxrender1 \
    fonts-liberation \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

ENV PATH="/usr/lib/chromium:$PATH"
ENV CHROME_BIN="/usr/bin/chromium"
ENV CHROMEDRIVER_PATH="/usr/bin/chromedriver"

CMD ["python", "app.py"]

