FROM ubuntu:22.04

# Install system dependencies (including pkg-config and cairo dev)
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv wget \
    pkg-config \
    libcairo2-dev libpango1.0-dev libgdk-pixbuf2.0-dev \
    libxi6 libgconf-2-4 libxrender1 libxext6 \
    libgl1-mesa-glx libfontconfig1 libdbus-glib-1-2 libxt6 \
    ffmpeg libavcodec-dev libavformat-dev libswscale-dev \
    build-essential meson ninja-build \
    && rm -rf /var/lib/apt/lists/*

# Create virtualenv
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

# Upgrade pip and install wheel first (helps with build dependencies)
RUN pip install --upgrade pip wheel setuptools

# Install Python packages
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Blender (headless)
ENV BLENDER_VERSION=4.2.2
RUN wget https://download.blender.org/release/Blender${BLENDER_VERSION%.*}/blender-${BLENDER_VERSION}-linux-x64.tar.xz \
    && tar -xf blender-${BLENDER_VERSION}-linux-x64.tar.xz \
    && mv blender-${BLENDER_VERSION}-linux-x64 /blender \
    && rm blender-${BLENDER_VERSION}-linux-x64.tar.xz

# Copy your code
COPY . .

# Start the app
CMD ["python", "medical_magic.py"]
