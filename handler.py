import os
import uuid
import subprocess
import requests
import runpod

def handler(event):
    data = event["input"]
    audio_url = data["audio_url"]

    job_id = str(uuid.uuid4())
    input_path = f"/tmp/{job_id}.mp3"
    output_dir = f"/tmp/{job_id}"

    r = requests.get(audio_url, timeout=120)
    r.raise_for_status()

    with open(input_path, "wb") as f:
        f.write(r.content)

    subprocess.run([
        "python", "-m", "demucs",
        "--two-stems", "vocals",
        "-n", "htdemucs",
        "-o", output_dir,
        input_path
    ], check=True)

    separated_dir = f"{output_dir}/htdemucs/{job_id}"

    return {
        "status": "done",
        "vocals_path": f"{separated_dir}/vocals.wav",
        "instrumental_path": f"{separated_dir}/no_vocals.wav"
    }

runpod.serverless.start({"handler": handler})
