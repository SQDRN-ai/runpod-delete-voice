import os
import uuid
import subprocess
import requests
import runpod


# -----------------------------
# R2 helpers
# -----------------------------
def r2_client():
    try:
        import boto3
    except Exception as e:
        raise RuntimeError(f"boto3 import failed. Add boto3 to requirements.txt. Details: {e}")

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


def upload_to_r2(local_path: str, key: str, content_type: str = "audio/wav"):
    bucket = os.environ["R2_BUCKET"]
    s3 = r2_client()

    extra_args = {"ContentType": content_type}
    s3.upload_file(local_path, bucket, key, ExtraArgs=extra_args)

    public_base = os.environ.get("R2_PUBLIC_BASE_URL", "").rstrip("/")
    url = f"{public_base}/{key}" if public_base else None

    return {
        "bucket": bucket,
        "key": key,
        "url": url,
    }


def download_url(url: str, local_path: str):
    r = requests.get(url, timeout=180)
    r.raise_for_status()

    with open(local_path, "wb") as f:
        f.write(r.content)


# -----------------------------
# Main RunPod handler
# -----------------------------
def handler(event):
    try:
        inp = (event or {}).get("input", {}) or {}

        audio_url = inp.get("audio_url")
        if not audio_url:
            return {
                "error": "Missing required input: audio_url"
            }

        job_id = str(inp.get("job_id") or uuid.uuid4())
        model = str(inp.get("model") or "htdemucs")
        output_prefix = str(inp.get("output_prefix") or f"demucs/{job_id}").strip("/")
        input_ext = str(inp.get("input_ext") or "mp3").lstrip(".").lower()

        input_path = f"/tmp/{job_id}.{input_ext}"
        output_dir = f"/tmp/{job_id}_out"

        download_url(audio_url, input_path)

        subprocess.run(
            [
                "python", "-m", "demucs",
                "--two-stems", "vocals",
                "-n", model,
                "-o", output_dir,
                input_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        # Demucs uses the input filename without extension as folder name
        stem_name = os.path.splitext(os.path.basename(input_path))[0]
        separated_dir = os.path.join(output_dir, model, stem_name)

        vocals_path = os.path.join(separated_dir, "vocals.wav")
        instrumental_path = os.path.join(separated_dir, "no_vocals.wav")

        if not os.path.exists(vocals_path):
            raise RuntimeError(f"vocals.wav not found at {vocals_path}")

        if not os.path.exists(instrumental_path):
            raise RuntimeError(f"no_vocals.wav not found at {instrumental_path}")

        vocals_key = f"{output_prefix}/vocals.wav"
        instrumental_key = f"{output_prefix}/instrumental.wav"

        vocals_uploaded = upload_to_r2(vocals_path, vocals_key, "audio/wav")
        instrumental_uploaded = upload_to_r2(instrumental_path, instrumental_key, "audio/wav")

        return {
            "status": "ok",
            "job_id": job_id,
            "model": model,
            "input_url": audio_url,
            "vocals": vocals_uploaded,
            "instrumental": instrumental_uploaded,
            "instrumental_url": instrumental_uploaded.get("url"),
            "vocals_url": vocals_uploaded.get("url"),
        }

    except subprocess.CalledProcessError as e:
        return {
            "error": "demucs failed",
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
