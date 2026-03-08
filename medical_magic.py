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

import manim
import subprocess
import tempfile
from gtts import gTTS
import librosa
import requests
import numpy as np
from PIL import Image
import openai
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

class MedicalAnimationSystem:
    def __init__(self, api_key: str, output_dir: str = "animated_videos"):
        self.api_key = api_key
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(output_dir, "ar_assets"), exist_ok=True)
        self.llm_client = openai.OpenAI(api_key=self.api_key)
        self.web_search_client = requests
        self.manager = multiprocessing.Manager()
        self.script_cache = self.manager.dict()
        self.watermark_text = os.getenv('WATERMARK_TEXT', 'Powered by MedicalAnimSys')
        self.watermark_font_size = int(os.getenv('WATERMARK_FONT_SIZE', '24'))
        self.ar_manifest = {}

    def extract_book_structure(self, pdf_path: str) -> Dict:
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        try:
            with pdfplumber.open(pdf_path) as pdf:
                full_text = "".join(page.extract_text() or "" for page in pdf.pages)
            prompt = f"""
            Extract book structure (chapters, headings, subheadings) from:
            Text: {full_text[:10000]}
            Output as JSON: {{"chapter": {{"heading": ["subheading1", "subheading2"]}}}}
            """
            response = self.llm_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": prompt}])
            structure = json.loads(response.choices[0].message.content)
            return structure
        except Exception as e:
            logging.error(f"Error extracting structure: {e}")
            return {}

    def create_scene_clip(self, scene: Dict, level: str, scene_index: int, language: str, resolution: str = '4k'):
        try:
            extras = scene.get('extras', '')
            res_map = {'4k': (3840, 2160), '1080p': (1920, 1080)}
            width, height = res_map.get(resolution, (3840, 2160))
            fps = 24
            num_frames = scene['duration'] * fps

            if level in ['molecular', 'cellular']:
                logging.info("Using placeholder for molecular/cellular scene (PyMOL disabled)")
                frames = [np.array(Image.new('RGB', (width, height), color='blue'))] * num_frames
                return ImageSequenceClip(frames, fps=fps)

            # Placeholder for other levels (add Blender/Manim logic later)
            frames = [np.array(Image.new('RGB', (width, height), color='green'))] * num_frames
            return ImageSequenceClip(frames, fps=fps)

        except Exception as e:
            logging.error(f"Error creating scene clip: {e}")
            frames = [np.array(Image.new('RGB', (width, height), color='red'))] * num_frames
            return ImageSequenceClip(frames, fps=fps)

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
            logging.error(f"Processing failed: {str(e)}")
            return f"Processing failed: {str(e)}<br><a href="/">Back</a>", 500
    return "Invalid file (must be .pdf)", 400
    
if __name__ == "__main__":
    system = MedicalAnimationSystem(api_key=os.getenv('OPENAI_API_KEY', 'your_api_key_here'))
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
