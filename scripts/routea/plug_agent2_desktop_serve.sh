#!/bin/bash
# Start the 5080 Glimmer server for the next-action runs (same GGUF as the laptop). Run only after the
# coordinator relays that Plug's GPU work is done. Stops with stop_desktop.sh on "D2 start".
cd ~/work/plug2
W=$HOME/work; G=$W/glimmer-gguf; BIN=$(dirname $(find $W/llamacpp -name llama-server -type f | head -1))
export LD_LIBRARY_PATH=$BIN:$(dirname $(find $W/llamacpp -name 'libcudart*' | head -1))
echo "gguf sha256 $(sha256sum $G/Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf | cut -c1-64)" > desktop-server.txt
$BIN/llama-server --version 2>&1 | head -1 >> desktop-server.txt
setsid nohup $BIN/llama-server -m $G/Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf --alias Muse-Glimmer-30B-KQuant-17GB-Q4_K_M \
  --host 127.0.0.1 --port 8098 -ngl 48 -c 32768 -np 1 -fa on -fit off --jinja -t 12 > desktop-server.log 2>&1 < /dev/null &
echo $! > desktop-server.pid
for i in $(seq 1 150); do curl -s localhost:8098/health | grep -q ok && break; sleep 2; done
cat > run_next_desktop.sh <<'EOS'
#!/bin/bash
cd ~/work/plug2
export OPENAI_API_KEY=none SYMBIONT_GLIMMER_URL=http://127.0.0.1:8098/v1 PLUG2_SERVER=desktop
export PYTHONPATH=$PWD/code/src:$PWD/code/scripts/routea:$PWD/code/scripts/calibration
~/work/.venv/bin/python -u code/scripts/routea/plug_agent2_smoke.py next-rows.json next-runs --workers 1 >> next-runs-desktop.log 2>&1
EOS
setsid nohup bash run_next_desktop.sh < /dev/null > /dev/null 2>&1 &
echo $! > desktop-runner.pid; date -Is
