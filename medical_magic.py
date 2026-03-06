import os
import json
from typing import List, Dict
import multiprocessing
import hashlib
import logging
import pdfplumber
from rdkit import Chem
from rdkit.Chem import Draw, AllChem
from Bio import PDB, SeqIO
from Bio.PDB import PDBList
try:
    from moviepy.editor import VideoFileClip, AudioFileClip, ImageSequenceClip, concatenate_videoclips, CompositeVideoClip, TextClip
    from moviepy.video.tools.subtitles import SubtitlesClip
    from moviepy.audio.fx.all import audio_fadein, audio_fadeout
except ImportError as e:
    logging.error(f"MoviePy import error: {e}. Install with pip install moviepy.")
import manim
import subprocess
import tempfile
from gtts import gTTS
import librosa
import pymol
import requests
import numpy as np
from PIL import Image, ImageDraw
import openai
import PySimpleGUI as sg
from pydub import AudioSegment
import molecular_nodes as mn
from flask import Flask, request, render_template, jsonify, send_file
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
import stripe
import boto3
import firebase_admin
from firebase_admin import credentials, analytics as fb_analytics

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
sentry_sdk.init(
    dsn=os.getenv('SENTRY_DSN', 'your-sentry-dsn'),
    integrations=[FlaskIntegration()],
    traces_sample_rate=1.0,
    environment="production"
)

class MedicalAnimationSystem:
    def __init__(self, api_key: str, output_dir: str = "animated_videos"):
        try:
            self.api_key = api_key
            self.output_dir = output_dir
            os.makedirs(output_dir, exist_ok=True)
            os.makedirs(os.path.join(output_dir, "ar_assets"), exist_ok=True)
            self.llm_client = openai.OpenAI(api_key=self.api_key)
            self.web_search_client = requests
            pymol.finish_launching(['pymol', '-qcxi'])
            self.manager = multiprocessing.Manager()
            self.script_cache = self.manager.dict()
            self.bgm_path = os.path.join(self.output_dir, "bgm.mp3")
            self._download_bgm()
            self.stripe = stripe
            self.watermark_text = os.getenv('WATERMARK_TEXT', 'Powered by MedicalAnimSys')
            self.watermark_font_size = int(os.getenv('WATERMARK_FONT_SIZE', '24'))
            self.ar_manifest = {}
            self.s3_client = boto3.client('s3')
            cred = credentials.Certificate(os.getenv('FIREBASE_CREDENTIALS_PATH'))
            firebase_admin.initialize_app(cred)
        except Exception as e:
            logging.error(f"Initialization error: {e}")
            sentry_sdk.capture_exception(e)
            raise

    def _download_bgm(self):
        """Download royalty-free BGM if not present."""
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
                sentry_sdk.capture_exception(e)

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
        except json.JSONDecodeError as e:
            logging.error(f"JSON decode error: {e}")
            sentry_sdk.capture_exception(e)
            return {}
        except Exception as e:
            logging.error(f"Error extracting structure from {pdf_path}: {e}")
            sentry_sdk.capture_exception(e)
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
            logging.error(f"Error extracting section text for {section}: {e}")
            sentry_sdk.capture_exception(e)
            return ""

    def supplement_with_web_info(self, query: str) -> str:
        try:
            url = f"https://pubmed.ncbi.nlm.nih.gov/?term={query.replace(' ', '+')}"
            response = self.web_search_client.get(url, timeout=10)
            response.raise_for_status()
            prompt = f"Summarize medical details from: {response.text[:10000]}"
            summ_response = self.llm_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": prompt}])
            return summ_response.choices[0].message.content
        except Exception as e:
            logging.error(f"Error supplementing info for query '{query}': {e}")
            sentry_sdk.capture_exception(e)
            return ""

    def translate_text(self, text: str, target_language: str) -> str:
        try:
            if target_language == 'en':
                return text
            prompt = f"Translate to {target_language}: '{text}'"
            response = self.llm_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": prompt}])
            return response.choices[0].message.content
        except Exception as e:
            logging.error(f"Error translating text to {target_language}: {e}")
            sentry_sdk.capture_exception(e)
            return text

    def generate_animation_script(self, text: str, level: str, language: str = 'en') -> Dict:
        cache_key = self._cache_key('generate_animation_script', text, level, language)
        if cache_key in self.script_cache:
            return self.script_cache[cache_key]
        try:
            extra = {
                'molecular': "Include SMILES strings in 'extras' for molecules.",
                'cellular': "Include PDB IDs or sequences in 'extras' for cellular components.",
                'anatomical': "Include anatomical models in 'extras' for Blender/Molecular Nodes with VR/AR metadata (e.g., organ names, grab points, animation triggers)."
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
            script = self.validate_script(script, text)  # Anti-hallucination check
            for scene in script['scenes']:
                scene['narration'] = self.translate_text(scene['narration'], language)
            self.script_cache[cache_key] = script
            return script
        except json.JSONDecodeError as e:
            logging.error(f"JSON decode error in script generation: {e}")
            sentry_sdk.capture_exception(e)
            return {"scenes": []}
        except Exception as e:
            logging.error(f"Error generating script for {level}/{language}: {e}")
            sentry_sdk.capture_exception(e)
            return {"scenes": []}

    def validate_script(self, script: Dict, original_text: str) -> Dict:
        """Prevent hallucinations by validating script against original text."""
        prompt = f"Check if this script matches the text without made-up facts: {original_text[:2000]}. Fix any errors or omissions. Be very strict and only use facts from the text or known medical knowledge."
        response = self.llm_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": prompt + json.dumps(script)}])
        validated_script = json.loads(response.choices[0].message.content)
        return validated_script

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
            logging.info(f"Generated H5P quiz: {h5p_path}")
            return h5p_path
        except Exception as e:
            logging.error(f"Error generating H5P quiz for {topic}: {e}")
            sentry_sdk.capture_exception(e)
            return ""

    def generate_manim_code(self, scene: Dict, level: str, image_path: str) -> str:
        cache_key = self._cache_key('generate_manim_code', json.dumps(scene), level, image_path)
        if cache_key in self.script_cache:
            return self.script_cache[cache_key]
        try:
            img_info = f"Use ImageMobject('{image_path}') for visualization." if image_path else ""
            prompt = f"""
            Generate Manim code for {level} scene:
            Duration: {scene['duration']}s, Visuals: {scene['visuals']}, Narration: {scene['narration']}
            {img_info}
            Output only the code.
            """
            response = self.llm_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": prompt}])
            code = response.choices[0].message.content
            self.script_cache[cache_key] = code
            return code
        except Exception as e:
            logging.error(f"Error generating Manim code: {e}")
            sentry_sdk.capture_exception(e)
            return ""

    def generate_blender_script(self, scene: Dict) -> str:
        cache_key = self._cache_key('generate_blender_script', json.dumps(scene))
        if cache_key in self.script_cache:
            return self.script_cache[cache_key]
        try:
            vr_metadata = json.dumps(scene.get('vr_metadata', {}))
            prompt = f"""
            Generate Blender Python script for medical animation:
            import bpy, molecular_nodes as mn
            # Enable Molecular Nodes: bpy.ops.preferences.addon_enable(module="molecular_nodes")
            # Load models: {scene['extras']} using mn.io.load for PDB/SMILES, apply electrostatic surfaces or lipophilicity.
            # Animate: {scene['visuals']}, with keyframes, modifiers (cloth/fluid).
            # Add VR metadata as custom properties: {vr_metadata}
            # Duration: {scene['duration']}s, FPS: 60, 4K resolution (3840x2160), Cycles samples: 64, GPU rendering.
            # Export PNG sequence and GLTF (with animations, materials, and metadata) to output_dir.
            Output only the code.
            """
            response = self.llm_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": prompt}])
            code = response.choices[0].message.content
            self.script_cache[cache_key] = code
            return code
        except Exception as e:
            logging.error(f"Error generating Blender code: {e}")
            sentry_sdk.capture_exception(e)
            return ""

    def generate_pymol_script(self, extras: str, visuals: str, duration: int) -> str:
        cache_key = self._cache_key('generate_pymol_script', extras, visuals, duration)
        if cache_key in self.script_cache:
            return self.script_cache[cache_key]
        try:
            prompt = f"""
            Generate advanced PyMOL script for animation:
            Use mset, mdo, movie for ligand binding, conformational changes, surface visualizations: {visuals}
            Extras: {extras}
            Duration: {duration}s, FPS: 24
            Optimize: ray_trace_mode=1, cache_frames=1
            Export PNGs with mpng.
            Output only the code.
            """
            response = self.llm_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": prompt}])
            code = response.choices[0].message.content
            self.script_cache[cache_key] = code
            return code
        except Exception as e:
            logging.error(f"Error generating PyMOL script: {e}")
            sentry_sdk.capture_exception(e)
            return ""

    def generate_pymol_frames(self, extras: str, visuals: str, duration: int, scene_index: int) -> List[str]:
        try:
            pdb_path = os.path.join(self.output_dir, 'model.pdb')
            if 'SMILES:' in extras:
                smiles = extras.split('SMILES:')[1].strip()
                mol = Chem.MolFromSmiles(smiles)
                AllChem.EmbedMultipleConfs(mol, numConfs=10, numThreads=4)
                writer = Chem.PDBWriter(pdb_path)
                for confId in range(mol.GetNumConformers()):
                    writer.write(mol, confId=confId)
                writer.close()
            elif 'PDB:' in extras:
                pdb_id = extras.split('PDB:')[1].strip()
                pdbl = PDBList()
                pdb_file = pdbl.retrieve_pdb_file(pdb_id, pdir=self.output_dir, file_format='pdb')
                os.rename(pdb_file, pdb_path)

            pymol_script = self.generate_pymol_script(extras, visuals, duration)
            if not pymol_script:
                raise ValueError("Failed to generate PyMOL script")

            with tempfile.NamedTemporaryFile(suffix='.pml', delete=False) as temp:
                temp.write(pymol_script.encode())
                temp_path = temp.name

            try:
                pymol.cmd.do(f'run {temp_path}')
                fps = 24
                num_frames = duration * fps
                prefix = os.path.join(self.output_dir, f'frame_{scene_index}_')
                pymol.cmd.set('cache_frames', 1)
                pymol.cmd.mpng(prefix)
                frame_paths = [f"{prefix}{i:04d}.png" for i in range(1, num_frames + 1) if os.path.exists(f"{prefix}{i:04d}.png")]
                return frame_paths
            finally:
                os.remove(temp_path)
                if os.path.exists(pdb_path):
                    os.remove(pdb_path)
        except Exception as e:
            logging.error(f"Error generating PyMOL frames: {e}")
            sentry_sdk.capture_exception(e)
            return []

    def create_scene_clip(self, scene: Dict, level: str, scene_index: int, language: str, resolution: str = '4k') -> VideoFileClip:
        try:
            extras = scene.get('extras', '')
            res_map = {'4k': (3840, 2160), '1080p': (1920, 1080)}
            width, height = res_map.get(resolution, (3840, 2160))
            if level in ['molecular', 'cellular']:
                frame_paths = self.generate_pymol_frames(extras, scene['visuals'], scene['duration'], scene_index)
                if frame_paths:
                    fps = 24
                    clip = ImageSequenceClip(frame_paths, fps=fps).resize((width, height))
                    return clip
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
                        result = subprocess.run(['blender', '-b', '-P', temp_path], capture_output=True, timeout=600)
                        if result.returncode != 0:
                            logging.error(f"Blender stderr: {result.stderr.decode()}")
                            raise RuntimeError(f"Blender failed: {result.stderr.decode()}")
                        fps = 24
                        num_frames = scene['duration'] * fps
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
                                logging.info(f"Exported GLTF for VR/AR: {gltf_path}")
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
                        raise RuntimeError(f"Manim failed: {result.stderr.decode()}")
                    manim_video_path = os.path.join('media', 'videos', os.path.basename(temp_path)[:-3], '1080p60', 'SceneAnim.mp4')
                    if not os.path.exists(manim_video_path):
                        raise FileNotFoundError("Manim video not found")
                    clip = VideoFileClip(manim_video_path).resize((width, height))
                    return clip
                finally:
                    os.remove(temp_path)
        except Exception as e:
            logging.error(f"Error creating scene clip for {level}: {e}")
            sentry_sdk.capture_exception(e)
            fps = 24
            num_frames = scene['duration'] * fps
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
            logging.error(f"Error generating audio for {language}: {e}")
            sentry_sdk.capture_exception(e)
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
            logging.error(f"Error generating subtitles for {language}: {e}")
            sentry_sdk.capture_exception(e)
            return []

    def generate_srt_file(self, subtitles: List[tuple], video_path: str, language: str):
        try:
            srt_path = video_path.replace('.mp4', f'_{language}.srt')
            with open(srt_path, 'w', encoding='utf-8') as f:
                for i, ((start, end), text) in enumerate(subtitles, 1):
                    f.write(f"{i}\n{self._format_time(start)} --> {self._format_time(end)}\n{text}\n\n")
            logging.info(f"Generated SRT: {srt_path}")
        except Exception as e:
            logging.error(f"Error generating SRT for {video_path}: {e}")
            sentry_sdk.capture_exception(e)

    def _format_time(self, seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def _create_video_wrapper(self, args):
        script, topic, level, language, resolution = args
        return self.create_animated_video(script, topic, level, language, resolution)

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
                final_clip = self.add_watermark(final_clip)
                video_path = os.path.join(self.output_dir, f"{topic.replace(' ', '_')}_{level}_{language}_{resolution}.mp4")
                final_clip.write_videofile(video_path, codec='libx264', threads=4, bitrate='8000k', fps=24)
                self.generate_srt_file(self.generate_subtitles(script, language), video_path, language)
                self.generate_h5p_quiz(script, topic, language)
                return video_path
            return ""
        except Exception as e:
            logging.error(f"Error creating video for {topic}/{level}/{language}: {e}")
            sentry_sdk.capture_exception(e)
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
            logging.error(f"Error processing book {pdf_path}: {e}")
            sentry_sdk.capture_exception(e)

    def _process_section(self, pdf_path: str, chapter: str, section: str, languages: List[str], resolution: str):
        try:
            text = self.extract_section_text(pdf_path, section)
            prompt = f"Is this text complete for medical topic '{section}'? If not, suggest query."
            response = self.llm_client.chat.completions.create(model="gpt-4", messages=[{"role": "user", "content": prompt + f" Text: {text[:2000]}"}])
            if "incomplete" in response.choices[0].message.content.lower():
                query = response.choices[0].message.content.split("query:")[1].strip() if "query:" in response.choices[0].message.content else f"Additional details on {section} physiology and pathology"
                text += self.supplement_with_web_info(query)
            
            levels = ['molecular', 'cellular', 'anatomical']
            tasks = []
            for level in levels:
                script = self.generate_animation_script(text, level, 'en')
                topic = f"{chapter} - {section}"
                for lang in languages:
                    tasks.append((script, topic, level, lang, resolution))
            with multiprocessing.Pool(len(languages)) as pool:
                video_paths = pool.map(self._create_video_wrapper, tasks)
                for video_path in video_paths:
                    if video_path:
                        print(f"Generated: {video_path}")
        except Exception as e:
            logging.error(f"Error processing section {section}: {e}")
            sentry_sdk.capture_exception(e)

def run_gui(system):
    layout = [
        [sg.Text('PDF Path:'), sg.Input(key='-PDF-'), sg.FileBrowse(file_types=(("PDF Files", "*.pdf"),))],
        [sg.Text('Languages (comma-separated):'), sg.Input(default_text='en,es,fr', key='-LANGS-')],
        [sg.Text('Num Processes:'), sg.Input(default_text='4', key='-PROCS-')],
        [sg.Text('Resolution:'), sg.Combo(['4k', '1080p'], default_value='4k', key='-RES-')],
        [sg.Text('BGM File (optional, default provided):'), sg.Input(key='-BGM-'), sg.FileBrowse(file_types=(("MP3 Files", "*.mp3"),))],
        [sg.Text('Tweak Prompt (optional for fixes):'), sg.Input(key='-TWEAK-', tooltip="Type things like 'add more heart facts' to tweak")],
        [sg.Button('Process'), sg.Button('Tweak Script'), sg.Button('Review Approve'), sg.Button('Exit')],
        [sg.Text('', key='-STATUS-', size=(50, 2), tooltip="This shows what's happening")]
    ]
    window = sg.Window('MedAnimVR - Easy Video Maker', layout)
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
                sentry_sdk.capture_exception(e)
        if event == 'Tweak Script':
            script_path = sg.popup_get_file('Pick script JSON to tweak', file_types=(("JSON Files", "*.json"),))
            if script_path:
                with open(script_path, 'r') as f:
                    script = json.load(f)
                tweak = values['-TWEAK-']
                if tweak:
                    for scene in script['scenes']:
                        scene['narration'] += f" {tweak}"
                    new_path = script_path.replace('.json', '_tweaked.json')
                    with open(new_path, 'w') as f:
                        json.dump(script, f)
                sg.popup('Script tweaked! Re-run Process to make new video.')
        if event == 'Review Approve':
            video_path = sg.popup_get_file('Pick video to review', file_types=(("Video Files", "*.mp4"),))
            if video_path:
                os.system(f"start {video_path}")  # Opens in default player
                approve = sg.popup_yes_no('Approve video? (Yes to finalize, No to tweak)')
                if approve == 'Yes':
                    sg.popup('Approved! Video is ready.')
                else:
                    sg.popup('Tweak the script and redo.')
    window.close()

# Flask Routes
@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_pdf():
    try:
        if 'pdf' not in request.files:
            return jsonify({'error': 'No PDF uploaded'}), 400
        pdf = request.files['pdf']
        pdf_path = os.path.join(system.output_dir, 'uploaded.pdf')
        pdf.save(pdf_path)
        langs = request.form.get('languages', 'en').split(',')
        resolution = request.form.get('resolution', '4k')
        bgm = request.files.get('bgm')
        if bgm:
            bgm.save(system.bgm_path)
        system.process_book(pdf_path, languages=langs, resolution=resolution)
        videos = [f for f in os.listdir(system.output_dir) if f.endswith('.mp4')]
        quizzes = [f for f in os.listdir(system.output_dir) if f.endswith('.json') and 'quiz' in f]
        gltfs = list(system.ar_manifest.keys())
        return jsonify({'videos': videos, 'quizzes': quizzes, 'ar_models': gltfs})
    except Exception as e:
        logging.error(f"Upload error: {e}")
        sentry_sdk.capture_exception(e)
        return jsonify({'error': str(e)}), 500

@app.route('/video/<filename>')
def serve_video(filename):
    try:
        return send_file(os.path.join(system.output_dir, filename))
    except Exception as e:
        logging.error(f"Video serve error: {e}")
        sentry_sdk.capture_exception(e)
        return jsonify({'error': 'Video not found'}), 404

@app.route('/ar/<model_id>')
def serve_ar(model_id):
    try:
        model_info = system.ar_manifest.get(model_id, {})
        if not model_info:
            return jsonify({'error': 'AR model not found'}), 404
        return send_file(model_info['path'])
    except Exception as e:
        logging.error(f"AR serve error: {e}")
        sentry_sdk.capture_exception(e)
        return jsonify({'error': 'AR model not found'}), 404

@app.route('/ar_manifest')
def serve_ar_manifest():
    try:
        return jsonify(system.ar_manifest)
    except Exception as e:
        logging.error(f"AR manifest error: {e}")
        sentry_sdk.capture_exception(e)
        return jsonify({'error': 'Manifest not found'}), 404

@app.route('/player/<filename>')
def video_player(filename):
    return render_template('player.html', filename=filename)

@app.route('/metadata/<topic>')
def video_metadata(topic):
    try:
        overlays = [{'time': 30, 'label': 'Heart Valve', 'vr_link': '/vr/heart_valve'}]
        return jsonify({'overlays': overlays})
    except Exception as e:
        logging.error(f"Metadata error: {e}")
        sentry_sdk.capture_exception(e)
        return jsonify({'error': 'Metadata not found'}), 404

@app.route('/register', methods=['POST'])
def register():
    try:
        email = request.json['email']
        institution = request.json.get('institution', '')
        plan = request.json.get('plan', 'individual')
        sub_id = system.create_subscription(email, institution, plan)
        lang = request.json.get('language', 'en')
        return jsonify({'success': True, 'sub_id': sub_id, 'language': lang})
    except Exception as e:
        logging.error(f"Registration error: {e}")
        sentry_sdk.capture_exception(e)
        return jsonify({'error': str(e)}), 500

@app.route('/dashboard/viewers/<user_id>')
def viewer_dashboard(user_id):
    try:
        analytics = system.get_viewer_analytics(user_id)
        return jsonify(analytics)
    except Exception as e:
        logging.error(f"Dashboard error: {e}")
        sentry_sdk.capture_exception(e)
        return jsonify({'error': 'Unauthorized'}), 403

@app.route('/lti/launch', methods=['POST'])
def lti_launch():
    try:
        content_id = request.form['content_id']
        user_id = request.form['user_id']
        launch_data = system.generate_lti_launch(content_id, user_id)
        return jsonify(launch_data)
    except Exception as e:
        logging.error(f"LTI launch error: {e}")
        sentry_sdk.capture_exception(e)
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    system = MedicalAnimationSystem(api_key=os.getenv('OPENAI_API_KEY', 'your_api_key_here'))
    run_gui(system)
    app.run(debug=False, host='0.0.0.0', port=5000)
