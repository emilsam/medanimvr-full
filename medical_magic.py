import os
import json
from typing import List, Dict
import logging
import pdfplumber
import numpy as np
from PIL import Image
from flask import Flask, request, send_file
from io import BytesIO
import tempfile

# Safe MoviePy import with fallback
try:
    from moviepy.editor import ImageSequenceClip
    MOVIEPY_AVAILABLE = True
except ImportError as e:
    logging.error(f"MoviePy import failed: {e}. Using fallback.")
    class DummyClip:
        pass
    ImageSequenceClip = DummyClip
    MOVIEPY_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

class MedicalAnimationSystem:
    def __init__(self, api_key: str = None):
        self.api_key = api_key

    def extract_book_structure(self, pdf_path: str) -> Dict:
        logging.info(f"Extracting structure from {pdf_path}")
        try:
            with pdfplumber.open(pdf_path) as pdf:
                full_text = "".join(page.extract_text() or "" for page in pdf.pages)
            return {
                "Chapter 1": {
                    "Introduction": ["Basic concepts"]
                }
            }
        except Exception as e:
            logging.error(f"Structure extraction failed: {e}")
            return {"Chapter 1": {"Test": ["Section 1"]}}

    def process_book(self, pdf_path: str, languages: List[str] = ['en'], num_processes: int = 1, resolution: str = '1080p'):
        logging.info(f"process_book started: {pdf_path}")
        try:
            structure = self.extract_book_structure(pdf_path)
            sections = []
            for chapter, headings in structure.items():
                for heading, subheadings in headings.items():
                    sections.append((pdf_path, chapter, heading))
                    for sub in subheadings:
                        sections.append((pdf_path, chapter, f"{heading} - {sub}"))

            logging.info(f"Found {len(sections)} sections")

            if not sections:
                raise ValueError("No sections found")

            pdf_path, chapter, section = sections[0]
            script = {
                "scenes": [
                    {"description": "Test scene", "duration": 5, "visuals": "placeholder", "narration": "Test narration"}
                ]
            }
            topic = f"{chapter} - {section}"
            video_buffer = self.create_animated_video_in_memory(script, topic, 'anatomical', languages[0], resolution)
            return video_buffer
        except Exception as e:
            logging.error(f"process_book failed: {str(e)}", exc_info=True)
            raise

    def create_animated_video_in_memory(self, script: Dict, topic: str, level: str, language: str, resolution: str) -> BytesIO:
        logging.info(f"Creating video: {topic}")
        try:
            width = 1920 if resolution == '1080p' else 3840
            height = 1080 if resolution == '1080p' else 2160
            frames = [np.array(Image.new('RGB', (width, height), color='green')) for _ in range(120)]
            clip = ImageSequenceClip(frames, fps=24)

            # Write to temporary file (moviepy requires a path)
            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_file:
                temp_path = tmp_file.name
                clip.write_videofile(
                    temp_path,
                    codec='libx264',
                    audio_codec='aac',
                    fps=24,
                    logger=None
                )

            # Read into memory buffer
            with open(temp_path, 'rb') as f:
                buffer = BytesIO(f.read())
            buffer.seek(0)

            # Clean up temp file
            os.remove(temp_path)

            logging.info("Video generated and loaded into memory")
            return buffer
        except Exception as e:
            logging.error(f"Video creation failed: {str(e)}")
            raise

@app.route('/')
def index():
    return """
    <html>
    <head><title>MedAnimVR</title></head>
    <body style="font-family:Arial; text-align:center; padding:50px;">
        <h1>MedAnimVR is Running!</h1>
        <p>Upload a small PDF to generate animations.</p>
        <form method="post" enctype="multipart/form-data" action="/upload">
            <input type="file" name="pdf" accept=".pdf" required><br><br>
            <input type="submit" value="Upload & Download Animation" style="padding:12px 24px; font-size:18px;">
        </form>
    </body>
    </html>
    """

@app.route('/upload', methods=['POST'])
def upload_pdf():
    if 'pdf' not in request.files:
        return "No file uploaded", 400
    file = request.files['pdf']
    if file.filename == '':
        return "No file selected", 400
    if not file.filename.lower().endswith('.pdf'):
        return "File must be .pdf", 400

    pdf_path = os.path.join('/tmp', file.filename)
    file.save(pdf_path)
    logging.info(f"PDF saved: {pdf_path}")

    system = MedicalAnimationSystem(os.getenv('OPENAI_API_KEY'))
    try:
        video_buffer = system.process_book(pdf_path)
        return send_file(
            video_buffer,
            mimetype='video/mp4',
            as_attachment=True,
            download_name='animated_test.mp4'
        )
    except Exception as e:
        logging.error(f"Processing failed: {str(e)}", exc_info=True)
        return f"<h1>Error</h1><p>{str(e)}</p><a href='/'>Back</a>", 500

# Only used for local development — Railway uses Gunicorn via Dockerfile CMD
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
