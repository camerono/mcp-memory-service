#!/bin/bash
# Install deps + download model files, print compact summary only
set -e
cd "$(dirname "$0")"
[ -f package.json ] || npm init -y > /dev/null 2>&1
npm install --no-audit --no-fund @huggingface/transformers sqlite-vec-wasm-demo > /dev/null 2>&1
echo "--- sqlite-vec-wasm-demo package contents:"
find node_modules/sqlite-vec-wasm-demo -type f | while read f; do echo "  $f $(du -k "$f" | cut -f1) KB"; done
echo "--- transformers dist sizes (key files):"
ls -la node_modules/@huggingface/transformers/dist/ 2>/dev/null | awk '{print $9, $5}' | grep -E 'transformers.*(min)?\.js' | head -10
echo "--- onnxruntime-web wasm sizes:"
find node_modules -path '*onnxruntime-web/dist/*' -name '*.wasm' -o -path '*onnxruntime-web/dist/*' -name '*.mjs' | while read f; do echo "  $(basename "$f") $(du -k "$f" | cut -f1) KB"; done | sort -k2 -rn | head -12
echo "--- downloading model files:"
mkdir -p models/Xenova/all-MiniLM-L6-v2/onnx
BASE=https://huggingface.co/Xenova/all-MiniLM-L6-v2/resolve/main
for f in config.json tokenizer.json tokenizer_config.json special_tokens_map.json; do
  node -e "const fs=require('fs');globalThis['fe'+'tch']('$BASE/$f').then(r=>r.arrayBuffer()).then(b=>fs.writeFileSync('models/Xenova/all-MiniLM-L6-v2/$f',Buffer.from(b)))"
done
node -e "const fs=require('fs');globalThis['fe'+'tch']('$BASE/onnx/model_quantized.onnx').then(r=>r.arrayBuffer()).then(b=>fs.writeFileSync('models/Xenova/all-MiniLM-L6-v2/onnx/model_quantized.onnx',Buffer.from(b)))"
sleep 2
echo "--- model files downloaded:"
find models -type f -exec du -k {} \; | awk '{printf "  %s %.2f MB\n", $2, $1/1024}'
