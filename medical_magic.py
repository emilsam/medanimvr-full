import os
import logging
import numpy as np
from PIL import Image
from flask import Flask, request

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
    def __init__(self, api_key: str = None, output_dir: str = "animated_videos"):
        self.api_key = api_key
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def process_book(self, pdf_path: str, languages: List[str] = ['en'], num_processes: int = 1, resolution: str = '1080p'):
        logging.info(f"process_book started: {pdf_path} (resolution={resolution})")
        try:
            # Fake structure & script for testing
            structure = {"Chapter 1": {"Test": ["Section 1"]}}
            sections = [(pdf_path, "Chapter 1", "Test")]
            logging.info(f"Processing {len(sections)} section(s)")

            pdf_path, chapter, section = sections[0]
            script = {"scenes": [{"description": "Test", "duration": 5, "visuals": "placeholder", "narration": "Hello"}]}
            topic = f"{chapter} - {section}"

            for lang in languages:
                video_path = self.create_animated_video(script, topic, 'anatomical', lang, resolution)
                logging.info(f"Generated: {video_path}")

            logging.info("process_book finished")
        except Exception as e:
            logging.error(f"process_book error: {str(e)}", exc_info=True)
            raise

    def create_animated_video(self, script: Dict, topic: str, level: str, language: str, resolution: str) -> str:
        logging.info(f"Creating video: {topic} ({level}, {language}, {resolution})")
        try:
            width = 1920 if resolution == '1080p' else 3840
            height = 1080 if resolution == '1080p' else 2160
            frames = [np.array(Image.new('RGB', (width, height), color='green')) for _ in range(120)]  # 5s @ 24fps
            clip = ImageSequenceClip(frames, fps=24)
            video_path = os.path.join(self.output_dir, f"{topic.replace(' ', '_')}_{level}_{language}_{resolution}.mp4")
            clip.write_videofile(video_path, codec='libx264', fps=24, logger=None)
            logging.info(f"Video created: {video_path}")
            return video_path
        except Exception as e:
            logging.error(f"Video failed: {str(e)}")
            return ""

@app.route('/')
def index():
    return """
    <html>
    <head><title>MedAnimVR</title></head>
    <body style="font-family:Arial; text-align:center; padding:50px;">
        <h1>MedAnimVR is Running! 🚀</h1>
        <p>Upload a PDF to generate animations (placeholder for now).</p>
        <form method="post" enctype="multipart/form-data" action="/upload">
            <input type="file" name="pdf" accept=".pdf" required><br><br>
            <input type="submit" value="Upload & Process" style="padding:12px 24px; font-size:18px;">
        </form>
        <p><small>Check Render Logs for results.</small></p>
    </body>
    </html>
    """

@app.route('/upload', methods=['POST'])
def upload_pdf():
    if 'pdf' not in request.files:
        return "No file", 400
    file = request.files['pdf']
    if file.filename == '':
        return "No file selected", 400
    if not file.filename.lower().endswith('.pdf'):
        return "Must be .pdf", 400

    pdf_path = os.path.join('/tmp', file.filename)
    file.save(pdf_path)
    logging.info(f"PDF saved: {pdf_path}")

    system = MedicalAnimationSystem()
    try:
        system.process_book(pdf_path)
        return f"""
        <h1>Success!</h1>
        <p>Processed: {file.filename}</p>
        <p>Check logs for video paths (search "Generated" or "animated_videos").</p>
        <a href="/">Back</a>
        """, 200
    except Exception as e:
        logging.error(f"Upload processing error: {str(e)}", exc_info=True)
        return f"""
        <h1>Error</h1>
        <p>{str(e)}</p>
        <a href="/">Back</a>
        """, 500

if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
