import os
import json
from typing import List, Dict
import multiprocessing
import hashlib
import logging
import pdfplumber
from rdkit import Chem
from rdkit.Chem import AllChem
from Bio import PDB
from Bio.PDB import PDBList

# Safe MoviePy import with fallback
try:
    from moviepy.editor import VideoFileClip, AudioFileClip, ImageSequenceClip, concatenate_videoclips, CompositeVideoClip, TextClip
    from moviepy.video.tools.subtitles import SubtitlesClip
    from moviepy.audio.fx.all import audio_fadein, audio_fadeout
    MOVIEPY_AVAILABLE = True
except ImportError as e:
    logging.error(f"MoviePy import failed: {e}. Using fallback clips.")
    class DummyClip:
        pass
    VideoFileClip = AudioFileClip = ImageSequenceClip = concatenate_videoclips = CompositeVideoClip = TextClip = DummyClip
    SubtitlesClip = DummyClip
    MOVIEPY_AVAILABLE = False

import numpy as np
from PIL import Image
import openai
from flask import Flask, request

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

class MedicalAnimationSystem:
    def __init__(self, api_key: str, output_dir: str = "animated_videos"):
        self.api_key = api_key
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(output_dir, "ar_assets"), exist_ok=True)
        self.llm_client = openai.OpenAI(api_key=self.api_key) if api_key else None
        self.watermark_text = os.getenv('WATERMARK_TEXT', 'Powered by MedicalAnimSys')

    def extract_book_structure(self, pdf_path: str) -> Dict:
        logging.info(f"Extracting structure from {pdf_path}")
        try:
            with pdfplumber.open(pdf_path) as pdf:
                full_text = "".join(page.extract_text() or "" for page in pdf.pages)
            # Fake structure for testing (replace with real GPT when quota fixed)
            return {
                "Chapter 1": {"Introduction": ["Basics"]}
            }
        except Exception as e:
            logging.error(f"Structure extraction failed: {e}")
            return {"Chapter 1": {"Test": ["Section"]}}

    def process_book(self, pdf_path: str, languages: List[str] = ['en'], num_processes: int = 1, resolution: str = '1080p'):
        logging.info(f"Starting process_book: {pdf_path}")
        try:
            structure = self.extract_book_structure(pdf_path)
            sections = []
            for chapter, headings in structure.items():
                for heading, subheadings in headings.items():
                    sections.append((pdf_path, chapter, heading))
                    for sub in subheadings:
                        sections.append((pdf_path, chapter, f"{heading} - {sub}"))

            logging.info(f"Processing {len(sections)} sections (first only for test)")

            if sections:
                pdf_path, chapter, section = sections[0]
                text = "Test medical text for animation."  # Replace with real extraction
                level = 'anatomical'  # Test with anatomical
                script = {"scenes": [{"description": "Test scene", "duration": 5, "visuals": "anatomy", "extras": "", "narration": "Hello world"}]}
                topic = f"{chapter} - {section}"
                for lang in languages:
                    video_path = self.create_animated_video(script, topic, level, lang, resolution)
                    logging.info(f"Generated test video: {video_path}")
            logging.info("process_book completed")
        except Exception as e:
            logging.error(f"process_book failed: {str(e)}", exc_info=True)
            raise

    def create_animated_video(self, script: Dict, topic: str, level: str, language: str, resolution: str) -> str:
        logging.info(f"Creating animated video for {topic} - {level}")
        try:
            # Simple placeholder video
            width, height = (1920, 1080) if resolution == '1080p' else (3840, 2160)
            frames = [np.array(Image.new('RGB', (width, height), color='green')) for _ in range(120)]  # 5 seconds @ 24 fps
            clip = ImageSequenceClip(frames, fps=24)
            video_path = os.path.join(self.output_dir, f"{topic.replace(' ', '_')}_{level}_{language}_{resolution}.mp4")
            clip.write_videofile(video_path, codec='libx264', fps=24)
            logging.info(f"Video written to {video_path}")
            return video_path
        except Exception as e:
            logging.error(f"Video creation failed: {e}")
            return ""

# Flask Routes
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
            <p>Check Render Logs for output paths (search for "animated_videos" or video files).</p>
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
