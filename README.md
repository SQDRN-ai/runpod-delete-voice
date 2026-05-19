# RunPod Demucs worker with Cloudflare R2 upload

## Required RunPod environment variables

R2_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=...
R2_PUBLIC_BASE_URL=https://your-public-r2-domain.com

`R2_PUBLIC_BASE_URL` is optional, but without it the worker can only return R2 keys, not public URLs.

## Test input

{
  "input": {
    "audio_url": "https://your-public-or-signed-url.com/input.mp3",
    "job_id": "test-001",
    "output_prefix": "demucs/test-001"
  }
}

## Output

Returns:
- instrumental.url
- vocals.url
- instrumental_url
- vocals_url
