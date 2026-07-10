#!/usr/bin/env bash
# Run Qwen/Qwen3.6-27B with vLLM on Lightning AI Studio (L40S, 48GB VRAM)
# FP8 quantization: ~27GB model weight + ~15GB KV cache headroom
set -euo pipefail

MODEL="Qwen/Qwen3.6-27B"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
MAX_LEN="${MAX_LEN:-32768}"
GPU_UTIL="${GPU_UTIL:-0.80}"
TP="${TP:-1}"   # tensor parallel — set to 2 if you have 2x L40S

# --- install / fix deps ---
if ! python -c "import vllm" 2>/dev/null; then
    echo "[setup] Installing vLLM..."
    pip install -q "vllm>=0.6.0" "huggingface_hub"
fi

# scipy 1.11.x uses numpy.Inf removed in numpy 2.0 — upgrade if needed
if python -c "import scipy; assert tuple(int(x) for x in scipy.__version__.split('.')[:2]) >= (1,12)" 2>/dev/null; then
    : # scipy ok
else
    echo "[setup] Upgrading scipy + transformers for numpy 2.x compatibility..."
    pip install -q "scipy>=1.12.0" "transformers>=4.46.0"
fi

# Fast HF download (new env var)
export HF_XET_HIGH_PERFORMANCE=1

echo "[serve] Model      : $MODEL"
echo "[serve] Quant      : fp8"
echo "[serve] Max tokens : $MAX_LEN"
echo "[serve] GPU util   : $GPU_UTIL"
echo "[serve] TP size    : $TP"
echo "[serve] Endpoint   : http://$HOST:$PORT/v1"
echo ""

exec python -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --served-model-name qwen3 \
    --host "$HOST" \
    --port "$PORT" \
    --quantization fp8 \
    --gpu-memory-utilization "$GPU_UTIL" \
    --max-model-len "$MAX_LEN" \
    --tensor-parallel-size "$TP" \
    --enforce-eager \
    --enable-prefix-caching \
    --trust-remote-code
