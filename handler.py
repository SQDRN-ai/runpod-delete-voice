import os
import re
import uuid
import random
import subprocess
import requests
import runpod


def r2_client():
    import boto3

    required = ["R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required env vars: {missing}")

    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
    )


def safe_filename(name: str, fallback: str = "output.mp3") -> str:
    name = str(name or "").strip() or fallback
    name = os.path.basename(name)
    name = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip(".-_") or fallback

    if not name.lower().endswith(".mp3"):
        name += ".mp3"

    return name


def upload_to_r2(local_path: str, key: str, content_type: str):
    bucket = os.environ["R2_BUCKET"]
    s3 = r2_client()

    s3.upload_file(
        local_path,
        bucket,
        key,
        ExtraArgs={"ContentType": content_type},
    )

    public_base = os.environ.get("R2_PUBLIC_BASE_URL", "").rstrip("/")
    url = f"{public_base}/{key}" if public_base else None

    return {"bucket": bucket, "key": key, "url": url}


def download_url(url: str, local_path: str):
    r = requests.get(url, timeout=180)
    r.raise_for_status()

    with open(local_path, "wb") as f:
        f.write(r.content)


def get_duration_seconds(path: str) -> float:
    p = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1",
            path,
        ],
        capture_output=True,
        text=True,
    )

    try:
        return float(p.stdout.strip())
    except Exception:
        return 0.0


def make_fingerprint_safe_mp3(input_audio: str, output_mp3: str):
    intro_delay_ms = random.randint(150, 350)
    outro_delay_s = round(random.uniform(0.10, 0.30), 2)
    volume = round(random.uniform(0.99, 1.02), 3)

    original_duration = get_duration_seconds(input_audio)
    final_duration = original_duration + (intro_delay_ms / 1000.0) + outro_delay_s

    audio_filter = (
        f"adelay={intro_delay_ms}|{intro_delay_ms},"
        f"volume={volume},"
        f"apad=pad_dur={outro_delay_s}"
    )

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", input_audio,
            "-af", audio_filter,
            "-map_metadata", "-1",
            "-codec:a", "libmp3lame",
            "-b:a", "192k",
            "-t", f"{final_duration:.3f}",
            output_mp3,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    return {
        "intro_delay_ms": intro_delay_ms,
        "outro_delay_seconds": outro_delay_s,
        "volume": volume,
        "original_duration_seconds": original_duration,
        "final_duration_seconds": final_duration,
    }


def create_instrumental(input_path: str, job_id: str, model: str):
    output_dir = f"/tmp/{job_id}_out"

    subprocess.run(
        [
            "python",
            "-m",
            "demucs",
            "--two-stems",
            "vocals",
            "-n",
            model,
            "-o",
            output_dir,
            input_path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    stem_name = os.path.splitext(os.path.basename(input_path))[0]
    separated_dir = os.path.join(output_dir, model, stem_name)
    instrumental_wav = os.path.join(separated_dir, "no_vocals.wav")

    if not os.path.exists(instrumental_wav):
        raise RuntimeError(f"no_vocals.wav not found at {instrumental_wav}")

    return instrumental_wav


def handler(event):
    try:
        inp = (event or {}).get("input", {}) or {}

        audio_url = inp.get("audio_url")
        if not audio_url:
            return {"error": "Missing required input: audio_url"}

        mode = str(inp.get("mode") or "instrumental").lower().strip()

        if mode not in ["instrumental", "original"]:
            return {
                "error": "Invalid mode",
                "allowed_modes": ["instrumental", "original"],
                "received": mode,
            }

        job_id = str(inp.get("job_id") or uuid.uuid4())
        model = str(inp.get("model") or "htdemucs")

        output_prefix = str(inp.get("output_prefix") or f"demucs/{job_id}").strip("/")
        output_filename = safe_filename(
            inp.get("output_filename"),
            fallback=f"{mode}.mp3",
        )

        input_ext = str(inp.get("input_ext") or "mp3").lstrip(".").lower()
        input_path = f"/tmp/{job_id}.{input_ext}"
        output_mp3 = f"/tmp/{job_id}_{mode}.mp3"

        download_url(audio_url, input_path)

        if mode == "instrumental":
            source_audio = create_instrumental(input_path, job_id, model)
        else:
            source_audio = input_path

        variation = make_fingerprint_safe_mp3(
            source_audio,
            output_mp3,
        )

        output_key = f"{output_prefix}/{output_filename}"

        uploaded = upload_to_r2(
            output_mp3,
            output_key,
            "audio/mpeg",
        )

        return {
            "status": "ok",
            "version": "demucs-r2-original-or-instrumental-mp3-v3",
            "mode": mode,
            "job_id": job_id,
            "model": model if mode == "instrumental" else None,
            "input_url": audio_url,
            "output_filename": output_filename,
            "uploaded": uploaded,
            "output_url": uploaded.get("url"),
            "instrumental_url": uploaded.get("url") if mode == "instrumental" else None,
            "original_url": uploaded.get("url") if mode == "original" else None,
            "variation": variation,
        }

    except subprocess.CalledProcessError as e:
        return {
            "error": "subprocess failed",
            "returncode": e.returncode,
            "stdout_tail": (e.stdout or "")[-4000:],
            "stderr_tail": (e.stderr or "")[-4000:],
        }

    except Exception as e:
        return {
            "error": "handler exception",
            "details": str(e),
        }


runpod.serverless.start({"handler": handler})
