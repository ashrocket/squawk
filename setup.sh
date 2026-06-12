#!/bin/bash
# squawk setup: local ears (whisper.cpp), local voices (say/Kokoro), claude CLI brain.
set -euo pipefail
cd "$(dirname "$0")"

echo "==> Checking requirements"
command -v brew >/dev/null || { echo "Homebrew required: https://brew.sh"; exit 1; }
command -v claude >/dev/null || { echo "Claude Code CLI required: https://claude.com/claude-code"; exit 1; }

echo "==> Installing whisper.cpp (Metal-accelerated speech-to-text)"
brew list whisper-cpp >/dev/null 2>&1 || brew install whisper-cpp

echo "==> Python environment"
python3 -m venv .venv
.venv/bin/pip install --quiet sounddevice numpy

echo "==> Whisper model (base.en, ~142MB)"
mkdir -p models logs
[ -f models/ggml-base.en.bin ] || curl -L -o models/ggml-base.en.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin

read -r -p "Also install Kokoro neural TTS voices (~340MB, optional)? [y/N] " kokoro
if [[ "$kokoro" =~ ^[Yy] ]]; then
  .venv/bin/pip install --quiet kokoro-onnx
  [ -f models/kokoro-v1.0.onnx ] || curl -L -o models/kokoro-v1.0.onnx \
    https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
  [ -f models/voices-v1.0.bin ] || curl -L -o models/voices-v1.0.bin \
    https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
fi

chmod +x voice speak
echo
echo "Done. Start a conversation:   ./voice --user YourName"
echo "Let an agent speak:           ./speak --as my-agent --announce \"Build finished.\""
echo "Fix a pronunciation:          ./speak --teach \"cmux=sea mux\""
echo "Settings app (optional):      ./app/build_app.sh && open app/Squawk.app"
