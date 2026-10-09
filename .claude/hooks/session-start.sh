#!/bin/bash
# SessionStart hook for Claude Code cloud sessions: installs Python + Remotion
# dependencies and lets Remotion's Chromium trust the sandbox egress CA.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

# ---- Python (virtualenv + dev deps for tests) ----
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -q -r requirements-dev.txt
echo "export VIRTUAL_ENV=\"$PWD/.venv\"" >> "${CLAUDE_ENV_FILE:-/dev/null}"
echo "export PATH=\"$PWD/.venv/bin:\$PATH\"" >> "${CLAUDE_ENV_FILE:-/dev/null}"

# ---- Optional local tools: Piper TTS, transcription, reference-video analysis ----
# Best effort: a blocked host must not fail the session.
.venv/bin/python -m pip install -q piper-tts faster-whisper "yt-dlp[default]" \
  youtube-transcript-api scenedetect opencv-python-headless \
  || echo "warning: optional Python tools failed to install" >&2

# piper_tts passes the voice name to `piper --model`, which looks for
# <name>.onnx in the working directory (repo root; *.onnx is gitignored).
# The model lives on the Hugging Face CDN, which the network policy may block.
PIPER_VOICE=en_US-lessac-medium
if [ ! -f "$PIPER_VOICE.onnx" ]; then
  timeout 300 .venv/bin/python -m piper.download_voices --download-dir . "$PIPER_VOICE" >/dev/null 2>&1 \
    || { rm -f "$PIPER_VOICE.onnx" "$PIPER_VOICE.onnx.json"; echo "warning: Piper voice download failed (is *.hf.co allowed?)" >&2; }
fi

# ---- Remotion composer ----
(cd remotion-composer && npm install --no-audit --no-fund --loglevel=error)

# ---- Chromium for Remotion ----
# remotion.media (Remotion's Chrome download host) is blocked here, so register
# the pre-installed Playwright headless shell in Remotion's browser cache.
HEADLESS_SHELL="$(ls -d /opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell 2>/dev/null | head -1 || true)"
if [ -n "$HEADLESS_SHELL" ]; then
  remotion_version="$(sed -n "s/^exports.TESTED_VERSION = '\(.*\)';/\1/p" remotion-composer/node_modules/@remotion/renderer/dist/browser/get-chrome-download-url.js)"
  shell_dir=remotion-composer/node_modules/.remotion/chrome-headless-shell
  mkdir -p "$shell_dir/linux64/chrome-headless-shell-linux64"
  ln -sfn "$HEADLESS_SHELL" "$shell_dir/linux64/chrome-headless-shell-linux64/chrome-headless-shell"
  printf '%s' "$remotion_version" > "$shell_dir/VERSION"
fi

# Remotion launches Chrome with --no-proxy-server, so direct TLS is signed by the
# sandbox egress CA. It is in the system bundle but not in Chrome's NSS store;
# add it so Google Fonts load during renders (verification stays on).
NSSDB="sql:$HOME/.pki/nssdb"
CA_BUNDLE=/root/.ccr/ca-bundle.crt
if command -v certutil >/dev/null 2>&1 && [ -f "$CA_BUNDLE" ] && [ -d "$HOME/.pki/nssdb" ]; then
  tmp="$(mktemp -d)"
  awk -v d="$tmp" '/BEGIN CERT/{n++} n{print > (d "/c" n ".pem")}' "$CA_BUNDLE"
  for f in "$tmp"/c*.pem; do
    subject="$(openssl x509 -in "$f" -noout -subject 2>/dev/null || true)"
    case "$subject" in
      *"sandbox-egress-gateway-production Egress Gateway CA"*) nick=egress-gateway-prod ;;
      *"sandbox-egress-production TLS Inspection CA"*) nick=egress-tls-inspect-prod ;;
      *) continue ;;
    esac
    certutil -L -d "$NSSDB" -n "$nick" >/dev/null 2>&1 || certutil -A -d "$NSSDB" -n "$nick" -t "C,," -i "$f"
  done
  rm -rf "$tmp"
fi

echo "OpenMontage session setup complete."
