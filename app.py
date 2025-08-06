import os
import random
import tempfile
from flask import Flask, request, send_file, render_template, jsonify
from moviepy.editor import (
    VideoFileClip,
    concatenate_videoclips,
    CompositeVideoClip,
    AudioFileClip,
    CompositeAudioClip
)
from pydub import AudioSegment, silence
#import whisper

#model = whisper.load_model("base")  # You can use 'tiny', 'base', 'small', 'medium', 'large'
#result = model.transcribe("your_video_audio.mp3")  # or .mp4

# This returns a dict with 'segments' (start, end, text)
#segments = result['segments']


#------------------------------------------------------------------------------------------------------#
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1GB max upload

def cut_silence_from_clip(video_path):
    """Remove silent sections from a video using PyDub"""
    audio = AudioSegment.from_file(video_path)
    nonsilent = silence.detect_nonsilent(audio, min_silence_len=400, silence_thresh=-40)

    full_clip = VideoFileClip(video_path)
    if not nonsilent:
        return full_clip, [full_clip]

    clips = [full_clip.subclip(start / 1000, end / 1000) for start, end in nonsilent]
    return concatenate_videoclips(clips), [full_clip]


@app.route('/generate', methods=['POST'])
def generate():
    uploaded_files = request.files

    # Required clips
    hook_file = uploaded_files.get('hook')
    body_file = uploaded_files.get('body')
    cta_file = uploaded_files.get('cta')

    if not all([hook_file, body_file, cta_file]):
        return "Missing one of the required clips: hook, body, or cta.", 400

    temp_dir = tempfile.mkdtemp()

    # Save required files
    hook_path = os.path.join(temp_dir, 'hook.mp4')
    body_path = os.path.join(temp_dir, 'body.mp4')
    cta_path = os.path.join(temp_dir, 'cta.mp4')
    hook_file.save(hook_path)
    body_file.save(body_path)
    cta_file.save(cta_path)

    # Load required clips
    hook_clip = VideoFileClip(hook_path)
    cta_clip = VideoFileClip(cta_path)

    body_composite, cleanup_refs = cut_silence_from_clip(body_path)

    # Load optional overlay video
    overlay_clips = []
    overlay_file = uploaded_files.get('overlays')
    if overlay_file:
        overlay_path = os.path.join(temp_dir, 'overlay.mp4')
        overlay_file.save(overlay_path)
        overlay_clip = VideoFileClip(overlay_path).resize(height=200).set_position(("right", "bottom"))
        overlay_clips.append(overlay_clip)

    # Load optional b-rolls
    broll_files = request.files.getlist('brolls')
    broll_clips = []
    for idx, broll_file in enumerate(broll_files):
        broll_path = os.path.join(temp_dir, f'broll_{idx}.mp4')
        broll_file.save(broll_path)
        try:
            broll_clip = VideoFileClip(broll_path).subclip(0, min(3, VideoFileClip(broll_path).duration))
            broll_clips.append(broll_clip)
        except:
            continue

    # Add overlays to body if present
    if overlay_clips:
        for overlay in overlay_clips:
            overlay = overlay.set_start(7).set_duration(min(3, body_composite.duration - 7))
            body_composite = CompositeVideoClip([body_composite, overlay.set_opacity(0.9)])

    # Add b-rolls over body video randomly (non-overlapping)
    for broll in broll_clips:
        start_time = random.uniform(7, max(7.1, body_composite.duration - 3))
        broll = broll.set_position("center").set_start(start_time).set_duration(min(3, body_composite.duration - start_time))
        body_composite = CompositeVideoClip([body_composite, broll.set_opacity(0.85)])

    # Combine all into final video
    final = concatenate_videoclips([hook_clip, body_composite, cta_clip])

    # Optional background music
    music_file = uploaded_files.get('music')
    if music_file:
        music_path = os.path.join(temp_dir, 'music.mp3')
        music_file.save(music_path)
        audio_bg = AudioFileClip(music_path).set_duration(final.duration).volumex(0.2)
        original_audio = final.audio.volumex(0.8).audio_fadein(1).audio_fadeout(1)
        # Combine both audio tracks
        combined_audio = CompositeAudioClip([original_audio, audio_bg])
        final = final.set_audio(combined_audio)

    # Export final video
    output_path = os.path.join(tempfile.gettempdir(), 'final_output.mp4')
    final.write_videofile(output_path, codec='libx264', audio_codec='aac')

    # Cleanup
    for clip in [hook_clip, cta_clip, final, body_composite] + cleanup_refs + broll_clips + overlay_clips:
        try:
            clip.close()
        except:
            pass

    return jsonify({ "downloadUrl": f"/download/{os.path.basename(output_path)}" })

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/download/<filename>')
def download_file(filename):
    temp_path = os.path.join(tempfile.gettempdir(), filename)
    if not os.path.exists(temp_path):
        return "File not found", 404
    return send_file(temp_path, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)


