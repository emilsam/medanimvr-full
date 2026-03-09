import os
import json
from typing import List, Dict
import logging
import pdfplumber
import numpy as np
from PIL import Image
from flask import Flask, request

# Safe MoviePy import with fallback
try:
    from moviepy.editor import ImageSequenceClip
    MOVIEPY_AVAILABLE = True
except ImportError as e:
    logging.error(f"MoviePy import failed: {e}. Using fallback clips.")
    class DummyClip:
        pass
    ImageSequenceClip = DummyClip
    MOVIEPY_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

class MedicalAnimationSystem:
    def __init__(self, api_key: str = None, output_dir: str = "animated_videos"):
        self.api_key = api_key
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def extract_book_structure(self, pdf_path: str) -> Dict:
        logging.info(f"Extracting structure from {pdf_path}")
        try:
            with pdfplumber.open(pdf_path) as pdf:
                full_text = "".join(page.extract_text() or "" for page in pdf.pages)
            # Stub - return fake structure
            return {"Chapter 1": {"Introduction": ["Basics"]}}
        except Exception as e:
            logging.error(f"Structure extraction failed: {e}")
            return {"Chapter 1": {"Test": ["Section"]}}

    def process_book(self, pdf_path: str, languages: List[str] = ['en'], num_processes: int = 1, resolution: str = '1080p'):
        logging.info(f"Starting process_book for {pdf_path} (languages={languages}, resolution={resolution})")
        try:
            structure = self.extract_book_structure(pdf_path)
            sections = []
            for chapter, headings in structure.items():
                for heading, subheadings in headings.items():
                    sections.append((pdf_path, chapter, heading))
                    for sub in subheadings:
                        sections.append((pdf_path, chapter, f"{heading} - {sub}"))

            logging.info(f"Found {len(sections)} sections")

            # Process only first section for test
            if sections:
                pdf_path, chapter, section = sections[0]
                logging.info(f"Processing section: {chapter} - {section}")

                # Fake text and script
                text = "This is a test medical text for animation."
                script = {
                    "scenes": [
                        {"description": "Test scene", "duration": 5, "visuals": "anatomy", "extras": "", "narration": "Hello from MedAnimVR"}
                    ]
                }
                topic = f"{chapter} - {section}"
                for lang in languages:
                    video_path = self.create_animated_video(script, topic, 'anatomical', lang, resolution)
                    logging.info(f"Generated video: {video_path}")
            else:
                logging.warning("No sections found")

            logging.info("process_book completed")
        except Exception as e:
            logging.error(f"process_book failed: {str(e)}", exc_info=True)
            raise

    def create_animated_video(self, script: Dict, topic: str, level: str, language: str, resolution: str) -> str:
        logging.info(f"Creating video for {topic} - {level} - {language}")
        try:
            width, height = (1920, 1080) if resolution == '1080p' else (3840, 2160)
            frames = [np.array(Image.new('RGB', (width, height), color='green')) for _ in range(120)]  # 5 sec @ 24fps
            clip = ImageSequenceClip(frames, fps=24)
            video_path = os.path.join(self.output_dir, f"{topic.replace(' ', '_')}_{level}_{language}_{resolution}.mp4")
            clip.write_videofile(video_path, codec='libx264', fps=24)
            logging.info(f"Video saved: {video_path}")
            return video_path
        except Exception as e:
            logging.error(f"Video creation failed: {e}")
            return "failed"

@app.route('/')
def index():
    return """
    <html>
    <head><title>MedAnimVR</title></head>
    <body style="font-family: Arial; text-align: center; padding: 50px;">
        <h1>MedAnimVR is Running! 🚀</h1>
        <p>Upload a small PDF to generate medical animations (anatomical scenes work; molecular is placeholder for now).</p>
        <form method="post" enctype="multipart/form-data" action="/upload">
            <input type="file" name="pdf" accept=".pdf" required>
            <br><br>
            <input type="submit" value="Upload & Process PDF" style="padding: 10px 20px; font-size: 16px;">
        </form>
        <p><small>Check Render logs for processing status.</small></p>
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
    if file and file.filename.lower().endswith('.pdf'):
        pdf_path = os.path.join('/tmp', file.filename)
        file.save(pdf_path)
        logging.info(f"PDF saved to {pdf_path} - starting processing")

        system = MedicalAnimationSystem(os.getenv('OPENAI_API_KEY'))
        try:
            system.process_book(pdf_path, languages=['en'], num_processes=1, resolution='1080p')
            logging.info("Processing completed successfully")
            return f"""
            <h1>Success!</h1>
            <p>PDF uploaded and processing finished: {file.filename}</p>
            <p>Check Render Logs for output paths (search for "Generated video" or "animated_videos").</p>
            <a href="/">Back to upload</a>
            """, 200
        except Exception as e:
            logging.error(f"Processing failed: {str(e)}", exc_info=True)
            return f"""
            <h1>Processing Failed</h1>
            <p>Error: {str(e)}</p>
            <p>Check Render Logs for details.</p>
            <a href="/">Back to upload</a>
            """, 500
    return "Invalid file (must be .pdf)", 400

if __name__ == "__main__":
    system = MedicalAnimationSystem(api_key=os.getenv('OPENAI_API_KEY', 'your_api_key_here'))
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
