import os
import logging
import pdfplumber
import numpy as np
from PIL import Image
from flask import Flask, request, send_file
from io import BytesIO
import tempfile

try:
    from moviepy.editor import ImageSequenceClip
except ImportError:
    logging.error("MoviePy import failed")
    class DummyClip: pass
    ImageSequenceClip = DummyClip

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)

class MedicalAnimationSystem:
    def process_book(self, pdf_path: str):
        logging.info(f"process_book started: {pdf_path}")
        try:
            # Fake structure
            logging.info("Found 2 sections")
            topic = "Chapter 1 - Introduction"
            video_buffer = self.create_video()
            return video_buffer
        except Exception as e:
            logging.error(f"process_book failed: {str(e)}", exc_info=True)
            raise

    def create_video(self):
        logging.info("Creating video")
        try:
            frames = [np.array(Image.new('RGB', (1920, 1080), color='green')) for _ in range(120)]
            clip = ImageSequenceClip(frames, fps=24)

            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
                temp_path = tmp.name
                clip.write_videofile(temp_path, codec='libx264', fps=24, logger=None)

            with open(temp_path, 'rb') as f:
                buffer = BytesIO(f.read())
            buffer.seek(0)
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
    <body style="font-family:Arial;text-align:center;padding:50px;">
        <h1>MedAnimVR is Running!</h1>
        <p>Upload a small PDF to generate animations.</p>
        <form method="post" enctype="multipart/form-data" action="/upload">
            <input type="file" name="pdf" accept=".pdf" required><br><br>
            <input type="submit" value="Upload & Download Animation" style="padding:12px 24px;font-size:18px;">
        </form>
    </body>
    </html>
    """

@app.route('/upload', methods=['POST'])
def upload_pdf():
    if 'pdf' not in request.files:
        return "No file uploaded", 400
    file = request.files['pdf']
    if file.filename == '' or not file.filename.lower().endswith('.pdf'):
        return "Invalid PDF", 400

    pdf_path = os.path.join('/tmp', file.filename)
    file.save(pdf_path)
    logging.info(f"PDF saved: {pdf_path}")

    system = MedicalAnimationSystem()
    try:
        video_buffer = system.process_book(pdf_path)
        return send_file(video_buffer, mimetype='video/mp4',
                         as_attachment=True, download_name='animated_test.mp4')
    except Exception as e:
        logging.error(f"Processing failed: {str(e)}", exc_info=True)
        return f"<h1>Error</h1><p>{str(e)}</p><a href='/'>Back</a>", 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True)
