FROM python:3.12-slim

ENV TZ=Europe/Rome
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Il modulo PDF di default va in una cartella diversa da "assets", così
# un eventuale volume montato dall'utente su /app/assets non lo nasconde.
RUN mv /app/assets /app/assets_default

EXPOSE 5000

CMD ["python", "app.py"]
