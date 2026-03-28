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
    gnupg \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*


RUN apt-get update && apt-get install -y \
    x11vnc \
    novnc \
    websockify \
    && rm -rf /var/lib/apt/lists/*






# Update CA certificates
RUN update-ca-certificates

# Tell ALSA to use PulseAudio as default device
RUN echo 'pcm.!default {\n    type pulse\n}\nctl.!default {\n    type pulse\n}' > /etc/asound.conf

# Install Google Chrome Stable
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /usr/share/keyrings/google-linux.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-linux.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# NOTE:
# If v4l2loopback-dkms is already installed on the host, do not install it here.
# Kernel modules should usually be handled on the host, not inside the container.

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install --with-deps chromium

COPY . .
RUN chmod +x start.sh

CMD ["./start.sh"]