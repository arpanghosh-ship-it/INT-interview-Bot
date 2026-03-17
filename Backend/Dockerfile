# FROM python:3.11-slim

# ENV DEBIAN_FRONTEND=noninteractive
# ENV PYTHONUNBUFFERED=1
# ENV DISPLAY=:99

# RUN apt-get update && apt-get install -y \
#     xvfb \
#     x11-utils \
#     x11vnc \
#     novnc \
#     websockify \
#     pulseaudio \
#     pulseaudio-utils \
#     dbus \
#     libportaudio2 \
#     portaudio19-dev \
#     libasound2 \
#     libasound2-plugins \
#     alsa-utils \
#     libnss3 \
#     libnspr4 \
#     libgbm1 \
#     libatk1.0-0 \
#     libatk-bridge2.0-0 \
#     libcups2 \
#     libdbus-1-3 \
#     libxcomposite1 \
#     libxdamage1 \
#     libxrandr2 \
#     libxss1 \
#     libxtst6 \
#     fonts-liberation \
#     xdg-utils \
#     wget \
#     curl \
#     ca-certificates \
#     build-essential \
#     gcc \
#     && rm -rf /var/lib/apt/lists/*

# RUN echo 'pcm.!default {\n    type pulse\n}\nctl.!default {\n    type pulse\n}' \
#     > /etc/asound.conf

# WORKDIR /app

# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# RUN playwright install --with-deps chromium

# COPY . .

# # ── Fix Windows CRLF line endings + make executable ───────────────────────────
# RUN sed -i 's/\r//' start.sh && chmod +x start.sh

# EXPOSE 6080
# EXPOSE 8000

# CMD ["/bin/bash", "-c", "sed -i 's/\\r//' /app/start.sh && /bin/bash /app/start.sh"]



























FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99

RUN apt-get update && apt-get install -y \
    xvfb \
    x11-utils \
    pulseaudio \
    pulseaudio-utils \
    dbus \
    libportaudio2 \
    portaudio19-dev \
    libasound2 \
    libasound2-plugins \
    alsa-utils \
    libnss3 \
    libnspr4 \
    libgbm1 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libxss1 \
    libxtst6 \
    fonts-liberation \
    xdg-utils \
    wget \
    curl \
    ca-certificates \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# ── Update CA certificates (fixes SSL errors with external WebSocket APIs) ────
RUN update-ca-certificates

# ── Tell ALSA to use PulseAudio as default device ─────────────────────────────
# This makes Chrome automatically route audio through PulseAudio
RUN echo 'pcm.!default {\n    type pulse\n}\nctl.!default {\n    type pulse\n}' \
    > /etc/asound.conf

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install --with-deps chromium

COPY . .
RUN chmod +x start.sh

CMD ["./start.sh"]