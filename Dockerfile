FROM ubuntu:22.04

# Minimal system dependencies — enough for Flask, pdfplumber, moviepy, PIL, ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv wget ffmpeg libfontconfig1 libgl1-mesa-glx \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python3 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

WORKDIR /app

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Use Gunicorn to serve the app — binds to $PORT automatically
CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "medical_magic:app", "--workers", "2", "--timeout", "120"]
