FROM ubuntu:22.04

# Install system dependencies (keep minimal — remove unused ones if possible)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv wget \
    ffmpeg libfontconfig1 libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

# Create venv early
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional: Blender — only if actually needed right now (it's huge!)
# ENV BLENDER_VERSION=4.2.2
# RUN wget https://download.blender.org/release/Blender${BLENDER_VERSION%.*}/blender-${BLENDER_VERSION}-linux-x64.tar.xz \
#     && tar -xf blender-${BLENDER_VERSION}-linux-x64.tar.xz \
#     && mv blender-${BLENDER_VERSION}-linux-x64 /blender \
#     && rm blender-${BLENDER_VERSION}-linux-x64.tar.xz

COPY . .

# Use shell form CMD → allows $PORT expansion + easier debugging
# Run with gunicorn for production (recommended on Railway)
# Adjust "medical_magic:app" → your module name + Flask instance name
CMD gunicorn medical_magic:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120
