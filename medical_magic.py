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
import PySimpleGUI as sg
from pydub import AudioSegment
from flask import Flask, request, render_template, jsonify, send_file

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
        self.bgm_path = os.path.join(self.output_dir, "bgm.mp3")
        self._download_bgm()
        self.watermark_text = os.getenv('WATERMARK_TEXT', 'Powered by MedicalAnimSys')
        self.watermark_font_size = int(os.getenv('WATERMARK_FONT_SIZE', '24'))
        self.ar_manifest = {}
        self.s3_client = boto3.client('s3')

    def _download_bgm(self):
        if not os.path.exists(self.bgm_path):
            try:
                bgm_url = "https://freesound.org/data/previews/587/587708_10819258-lq.mp3"
                response = requests.get(bgm_url, timeout=10)
                response.raise_for_status()
                with open(self.bgm_path, "wb") as f:
                    f.write(response.content)
                logging.info(f"Downloaded BGM to {self.bgm_path}")
            except Exception as e:
                logging.error(f"Error downloading BGM: {e}")

    def _cache_key(self, func_name: str, *args) -> str:
        return hashlib.sha256(f"{func_name}:{args}".encode()).hexdigest()

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

    def extract_section_text(self, pdf_path: str, section: str) -> str:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                full_text = "".join(page.extract_text() or "" for page in pdf.pages)
            prompt = f"""
            Extract content for section '{section}' from:
            Text: {full_text[:10000]}
            Output only the extracted text.
            """
            response = self.llm_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": prompt}])
            return response.choices[0].message.content
        except Exception as e:
            logging.error(f"Error extracting section text: {e}")
            return ""

    def supplement_with_web_info(self, query: str) -> str:
        try:
            url = f"https://pubmed.ncbi.nlm.nih.gov/?term={query.replace(' ', '+')}"
            response = self.web_search_client.get(url, timeout=10)
            prompt = f"Summarize medical details from: {response.text[:10000]}"
            summ_response = self.llm_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": prompt}])
            return summ_response.choices[0].message.content
        except Exception as e:
            logging.error(f"Error supplementing info: {e}")
            return ""

    def translate_text(self, text: str, target_language: str) -> str:
        try:
            if target_language == 'en':
                return text
            prompt = f"Translate to {target_language}: '{text}'"
            response = self.llm_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": prompt}])
            return response.choices[0].message.content
        except Exception as e:
            logging.error(f"Error translating text: {e}")
            return text

    def generate_animation_script(self, text: str, level: str, language: str = 'en') -> Dict:
        cache_key = self._cache_key('generate_animation_script', text, level, language)
        if cache_key in self.script_cache:
            return self.script_cache[cache_key]
        try:
            extra = {
                'molecular': "Include SMILES strings in 'extras' for molecules.",
                'cellular': "Include PDB IDs or sequences in 'extras' for cellular components.",
                'anatomical': "Include anatomical models in 'extras' for Blender with VR/AR metadata."
            }.get(level, "")
            prompt = f"""
            Generate animation script for {level} level from: '{text}'
            Style: David Attenborough documentary, engaging, step-by-step, dyslexia-friendly.
            Include narration in English and quiz questions (H5P format) per scene.
            {extra}
            Output as JSON: {{'scenes': [{{'description': str, 'duration': int, 'visuals': str, 'extras': str, 'narration': str, 'quiz': {{'question': str, 'options': [str], 'correct': str}}, 'vr_metadata': {{'model_name': str, 'grab_points': [{{'name': str, 'position': [float, float, float], 'animation_trigger': str}}], 'scale_factor': float}}}}]}}
            """
            response = self.llm_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": prompt}])
            script = json.loads(response.choices[0].message.content)
            for scene in script['scenes']:
                scene['narration'] = self.translate_text(scene['narration'], language)
            self.script_cache[cache_key] = script
            return script
        except Exception as e:
            logging.error(f"Error generating script: {e}")
            return {"scenes": []}

    def generate_h5p_quiz(self, script: Dict, topic: str, language: str) -> str:
        try:
            h5p_content = {
                "title": f"Quiz: {topic}",
                "language": language,
                "questions": []
            }
            for scene in script['scenes']:
                quiz = scene.get('quiz', {})
                if quiz:
                    question = {
                        "params": {
                            "question": quiz['question'],
                            "answers": [{"text": opt, "correct": opt == quiz['correct']} for opt in quiz['options']]
                        },
                        "type": "multiple-choice"
                    }
                    h5p_content['questions'].append(question)
            h5p_path = os.path.join(self.output_dir, f"{topic.replace(' ', '_')}_quiz_{language}.json")
            with open(h5p_path, 'w', encoding='utf-8') as f:
                json.dump(h5p_content, f, indent=2)
            return h5p_path
        except Exception as e:
            logging.error(f"Error generating H5P quiz: {e}")
            return ""

    def generate_manim_code(self, scene: Dict, level: str, image_path: str) -> str:
        try:
            img_info = f"Use ImageMobject('{image_path}') for visualization." if image_path else ""
            prompt = f"""
            Generate Manim code for {level} scene:
            Duration: {scene['duration']}s, Visuals: {scene['visuals']}, Narration: {scene['narration']}
            {img_info}
            Output only the code.
            """
            response = self.llm_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": prompt}])
            return response.choices[0].message.content
        except Exception as e:
            logging.error(f"Error generating Manim code: {e}")
            return ""

    def generate_blender_script(self, scene: Dict) -> str:
        try:
            vr_metadata = json.dumps(scene.get('vr_metadata', {}))
            prompt = f"""
            Generate Blender Python script for medical animation:
            import bpy
            # Load models: {scene['extras']}
            # Animate: {scene['visuals']}, with keyframes, modifiers.
            # Add VR metadata as custom properties: {vr_metadata}
            # Duration: {scene['duration']}s, FPS: 60, 4K resolution, Cycles samples: 64.
            # Export PNG sequence and GLTF to output_dir.
            Output only the code.
            """
            response = self.llm_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": prompt}])
            return response.choices[0].message.content
        except Exception as e:
            logging.error(f"Error generating Blender script: {e}")
            return ""

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

            elif level == 'anatomical':
                blender_code = self.generate_blender_script(scene)
                if not blender_code:
                    raise ValueError("Failed to generate Blender code")
                with tempfile.TemporaryDirectory(dir=self.output_dir) as temp_dir:
                    gltf_path = os.path.join(self.output_dir, "ar_assets", f"scene_{scene_index}_{level}_{language}.gltf")
                    blender_code += f"\nbpy.ops.export_scene.gltf(filepath='{gltf_path}', export_format='GLTF_SEPARATE', export_animations=True, export_materials='EXPORT', export_extras=True)"
                    with tempfile.NamedTemporaryFile(suffix='.py', delete=False) as temp:
                        temp.write(blender_code.encode())
                        temp_path = temp.name
                    try:
                        result = subprocess.run(['/blender/blender', '-b', '-P', temp_path], capture_output=True, timeout=600)
                        if result.returncode != 0:
                            logging.error(f"Blender failed: {result.stderr.decode()}")
                            raise RuntimeError("Blender failed")
                        frame_paths = [os.path.join(temp_dir, f'frame_{i:04d}.png') for i in range(1, num_frames + 1)]
                        frame_paths = [p for p in frame_paths if os.path.exists(p)]
                        if frame_paths:
                            clip = ImageSequenceClip(frame_paths, fps=fps).resize((width, height))
                            if os.path.exists(gltf_path):
                                self.ar_manifest[f"{scene_index}_{level}_{language}"] = {
                                    'path': gltf_path,
                                    'metadata': scene.get('vr_metadata', {})
                                }
                                with open(os.path.join(self.output_dir, "ar_manifest.json"), 'w') as f:
                                    json.dump(self.ar_manifest, f, indent=2)
                            return clip
                        raise FileNotFoundError("No frames generated by Blender.")
                    finally:
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
            else:
                manim_code = self.generate_manim_code(scene, level, None)
                if not manim_code:
                    raise ValueError("Failed to generate Manim code")
                with tempfile.NamedTemporaryFile(suffix='.py', delete=False) as temp:
                    temp.write(manim_code.encode())
                    temp_path = temp.name
                try:
                    result = subprocess.run(['manim', '-qh', temp_path, 'SceneAnim'], capture_output=True)
                    if result.returncode != 0:
                        raise RuntimeError(f"Manim failed")
                    manim_video_path = os.path.join('media', 'videos', os.path.basename(temp_path)[:-3], '1080p60', 'SceneAnim.mp4')
                    if not os.path.exists(manim_video_path):
                        raise FileNotFoundError("Manim video not found")
                    clip = VideoFileClip(manim_video_path).resize((width, height))
                    return clip
                finally:
                    os.remove(temp_path)
        except Exception as e:
            logging.error(f"Error creating scene clip: {e}")
            frames = [np.array(Image.new('RGB', (width, height), color='blue'))] * num_frames
            return ImageSequenceClip(frames, fps=fps)

    def generate_scene_audio(self, narration: str, scene_index: int, language: str) -> str:
        try:
            tts = gTTS(text=narration, lang=language, slow=False)
            audio_path = os.path.join(self.output_dir, f'temp_audio_{scene_index}_{language}.mp3')
            tts.save(audio_path)
            if os.path.exists(self.bgm_path):
                narration_audio = AudioSegment.from_mp3(audio_path)
                bgm = AudioSegment.from_mp3(self.bgm_path).apply_gain(-10)
                combined = narration_audio.overlay(bgm[:len(narration_audio)])
                combined.export(audio_path, format="mp3")
            return audio_path
        except Exception as e:
            logging.error(f"Error generating audio: {e}")
            return None

    def generate_subtitles(self, script: Dict, language: str) -> List[tuple]:
        try:
            subtitles = []
            current_time = 0
            for scene in script['scenes']:
                text = self.translate_text(scene['narration'], language)
                start = current_time
                end = current_time + scene['duration']
                subtitles.append(((start, end), text))
                current_time = end
            return subtitles
        except Exception as e:
            logging.error(f"Error generating subtitles: {e}")
            return []

    def generate_srt_file(self, subtitles: List[tuple], video_path: str, language: str):
        try:
            srt_path = video_path.replace('.mp4', f'_{language}.srt')
            with open(srt_path, 'w', encoding='utf-8') as f:
                for i, ((start, end), text) in enumerate(subtitles, 1):
                    f.write(f"{i}\n{self._format_time(start)} --> {self._format_time(end)}\n{text}\n\n")
        except Exception as e:
            logging.error(f"Error generating SRT: {e}")

    def _format_time(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def create_animated_video(self, script: Dict, topic: str, level: str, language: str = 'en', resolution: str = '4k') -> str:
        try:
            clips = []
            audio_paths = []
            for i, scene in enumerate(script['scenes']):
                clip = self.create_scene_clip(scene, level, i, language, resolution)
                audio_path = self.generate_scene_audio(scene['narration'], i, language)
                if audio_path:
                    audio = AudioFileClip(audio_path).fx(audio_fadein, 0.5).fx(audio_fadeout, 0.5)
                    if abs(clip.duration - audio.duration) > 0.1:
                        clip = clip.set_duration(audio.duration)
                    clip = clip.set_audio(audio)
                    audio_paths.append(audio_path)
                clips.append(clip)
            
            if clips:
                final_clip = concatenate_videoclips(clips, method="compose")
                video_path = os.path.join(self.output_dir, f"{topic.replace(' ', '_')}_{level}_{language}_{resolution}.mp4")
                final_clip.write_videofile(video_path, codec='libx264', threads=4, bitrate='8000k', fps=24)
                self.generate_srt_file(self.generate_subtitles(script, language), video_path, language)
                self.generate_h5p_quiz(script, topic, language)
                return video_path
            return ""
        except Exception as e:
            logging.error(f"Error creating video: {e}")
            return ""
        finally:
            for path in audio_paths:
                if path and os.path.exists(path):
                    os.remove(path)

    def process_book(self, pdf_path: str, languages: List[str] = ['en'], num_processes: int = 4, resolution: str = '4k'):
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        try:
            structure = self.extract_book_structure(pdf_path)
            sections = []
            for chapter, headings in structure.items():
                for heading, subheadings in headings.items():
                    sections.append((pdf_path, chapter, heading))
                    for sub in subheadings:
                        sections.append((pdf_path, chapter, f"{heading} - {sub}"))
            with multiprocessing.Pool(num_processes) as pool:
                pool.starmap(self._process_section, [(pdf_path, chapter, section, languages, resolution) for pdf_path, chapter, section in sections])
        except Exception as e:
            logging.error(f"Error processing book: {e}")

    def _process_section(self, pdf_path: str, chapter: str, section: str, languages: List[str], resolution: str):
        try:
            text = self.extract_section_text(pdf_path, section)
            levels = ['molecular', 'cellular', 'anatomical']
            tasks = []
            for level in levels:
                script = self.generate_animation_script(text, level, 'en')
                topic = f"{chapter} - {section}"
                for lang in languages:
                    tasks.append((script, topic, level, lang, resolution))
            with multiprocessing.Pool(len(languages)) as pool:
                video_paths = pool.map(self._create_video_wrapper, tasks)
        except Exception as e:
            logging.error(f"Error processing section: {e}")

    def _create_video_wrapper(self, args):
        script, topic, level, language, resolution = args
        return self.create_animated_video(script, topic, level, language, resolution)

def run_gui(system):
    layout = [
        [sg.Text('PDF Path:'), sg.Input(key='-PDF-'), sg.FileBrowse(file_types=(("PDF Files", "*.pdf"),))],
        [sg.Text('Languages (comma-separated):'), sg.Input(default_text='en,es,fr', key='-LANGS-')],
        [sg.Text('Num Processes:'), sg.Input(default_text='4', key='-PROCS-')],
        [sg.Text('Resolution:'), sg.Combo(['4k', '1080p'], default_value='4k', key='-RES-')],
        [sg.Text('BGM File (optional):'), sg.Input(key='-BGM-'), sg.FileBrowse(file_types=(("MP3 Files", "*.mp3"),))],
        [sg.Button('Process'), sg.Button('Exit')],
        [sg.Text('', key='-STATUS-', size=(50, 2))]
    ]
    window = sg.Window('MedAnimVR - Video Maker', layout)
    while True:
        event, values = window.read()
        if event in (sg.WIN_CLOSED, 'Exit'):
            break
        if event == 'Process':
            try:
                if not values['-PDF-']:
                    raise ValueError("PDF path required.")
                langs = [l.strip() for l in values['-LANGS-'].split(',')]
                num_procs = int(values['-PROCS-'])
                if values['-BGM-'] and os.path.exists(values['-BGM-']):
                    system.bgm_path = values['-BGM-']
                window['-STATUS-'].update('Processing...')
                window.refresh()
                system.process_book(values['-PDF-'], languages=langs, num_processes=num_procs, resolution=values['-RES-'])
                window['-STATUS-'].update('Processing complete!')
            except Exception as e:
                window['-STATUS-'].update(f"Error: {e}")
    window.close()

# Flask Routes
@app.route('/')
def index():
    return "MedAnimVR running - upload a PDF via /upload or use GUI locally."

@app.route('/upload', methods=['POST'])
def upload_pdf():
    return jsonify({"message": "Upload endpoint ready - implement file handling as needed"})

if __name__ == "__main__":
    system = MedicalAnimationSystem(api_key=os.getenv('OPENAI_API_KEY', 'your_api_key_here'))
    # run_gui(system)  # Uncomment for local GUI testing
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
