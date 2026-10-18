# voice-studio-ai

Minimal deploy service for [VoiceStudio](https://github.com/debpalash/VoiceStudio)
on the AI server (RTX 3090). Pulls the pre-built `ghcr.io/debpalash/voicestudio:stable`
image — no source build, nothing else needed on the server.

## Files

- `Jenkinsfile` — pipeline: copies `docker-compose.yml` + `.env` (from a Jenkins
  secret) to `~/apps/voice-studio-ai` on the AI server, then
  `docker compose pull && up -d`.
- `docker-compose.yml` — single `omnivoice` service, NVIDIA GPU, port 3900 on the LAN,
  named volume `omnivoice-data` for persistent data (DB, voices, HF cache).
- `.env.example` — template for the Jenkins secret; the real `.env` is never committed.

## Setup

1. Jenkins secret-text credential `voice-studio-env-file` containing:

   ```
   OMNIVOICE_API_KEY=<long random string>
   HF_TOKEN=
   ```

2. Jenkins pipeline job → this repo (Jenkinsfile at root). Existing credentials are
   reused: `github-access-token`, `tosinlab-ai-private-key`, `jenkins-job-webhook-url`.

3. Run the job. Service: `http://<ai-server-ip>:3900` (admin routes need the API key).

To use a gated model later (diarization, PocketTTS): add `HF_TOKEN=hf_...` to the
Jenkins secret (accept the model's license first) and redeploy.
