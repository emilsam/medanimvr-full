import os
import logging
from typing import List, Dict
import pdfplumber
import numpy as np
from PIL import Image
from flask import Flask, request, send_file
from io import BytesIO

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
        # No output_dir anymore — we generate in memory

    def extract_book_structure(self, pdf_path: str) -> Dict:
        logging.info(f"Extracting structure from {pdf_path}")
        try:
            with pdfplumber.open(pdf_path) as pdf:
                full_text = "".join(page.extract_text() or "" for page in pdf.pages)
            # Minimal fake structure so processing can continue
            return {
                "Chapter 1": {
                    "Introduction": ["Basic concepts"]
                }
            }
        except Exception as e:
            logging.error(f"Structure extraction failed: {e}")
            return {"Chapter 1": {"Test": ["Section 1"]}}

    def process_book(self, pdf_path: str, languages: List[str] = ['en'], num_processes: int = 1, resolution: str = '1080p'):
        logging.info(f"process_book started: {pdf_path} (languages={languages}, resolution={resolution})")
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
                raise ValueError("No sections found in PDF structure")

            # Process only first section for speed / testing
            pdf_path, chapter, section = sections[0]
            logging.info(f"Processing section: {chapter} - {section}")

            # Fake script (replace later with real content)
            script = {
                "scenes": [
                    {
                        "description": "Test scene",
                        "duration": 5,
                        "visuals": "placeholder anatomy",
                        "extras": "",
                        "narration": "This is a test narration"
                    }
                ]
            }

            topic = f"{chapter} - {section}"
            # We only generate one video for the first language for simplicity
            video_buffer = self.create_animated_video_in_memory(script, topic, 'anatomical', languages[0], resolution)
            return video_buffer

        except Exception as e:
            logging.error(f"process_book failed: {str(e)}", exc_info=True)
            raise

    def create_animated_video_in_memory(self, script: Dict, topic: str, level: str, language: str, resolution: str) -> BytesIO:
        logging.info(f"Creating video in memory: {topic} - {level} - {language} - {resolution}")
        try:
            width = 1920 if resolution == '1080p' else 3840
            height = 1080 if resolution == '1080p' else 2160

            # Your current 5-second green placeholder (120 frames @ 24 fps = 5 s)
            frames = [np.array(Image.new('RGB', (width, height), color='green')) for _ in range(120)]
            clip = ImageSequenceClip(frames, fps=24)

            # Write directly to memory buffer
            buffer = BytesIO()
            clip.write_videofile(
                buffer,
                codec='libx264',
                audio_codec='aac',      # safe even without audio
                fps=24,
                logger=None,
                verbose=False
            )
            buffer.seek(0)
            logging.info("Video generated in memory successfully")
            return buffer

        except Exception as e:
            logging.error(f"Video creation failed: {str(e)}")
            raise


@app.route('/')
def index():
    return "Test - app is alive on Railway"
    <html>
    <head><title>MedAnimVR</title></head>
    <body style="font-family:Arial; text-align:center; padding:50px;">
        <h1>MedAnimVR is Running! 🚀</h1>
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

    # Save uploaded file temporarily (Render allows /tmp)
    pdf_path = os.path.join('/tmp', file.filename)
    file.save(pdf_path)
    logging.info(f"PDF saved temporarily: {pdf_path}")

    system = MedicalAnimationSystem(os.getenv('OPENAI_API_KEY'))

    try:
        video_buffer = system.process_book(
            pdf_path=pdf_path,
            languages=['en'],
            num_processes=1,
            resolution='1080p'
        )

        # Clean up the temporary PDF
        try:
            os.remove(pdf_path)
        except:
            pass

        # Return the video as download
        return send_file(
            video_buffer,
            mimetype='video/mp4',
            as_attachment=True,
            download_name='animated_test.mp4'
        )

    except Exception as e:
        logging.error(f"Processing failed: {str(e)}", exc_info=True)
        return f"""
        <h1>Processing Failed</h1>
        <p>Error: {str(e)}</p>
        <a href="/">Back to upload</a>
        """, 500


if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
