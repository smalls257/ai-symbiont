# Task image for one constructed demo task (not a benchmark): /testbed is the ledgerline repo as
# one git commit, the shape scripts/calibration/taskenv.py and run_calibration.py expect.
# Build context: demo_tasks/ledgerline. Build with scripts/calibration/build_trap_images.py.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git patch \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir pytest==8.3.5

# taskenv.grade sources this conda activate line before every test command; the tasks use the
# system Python, so the script only has to exist.
RUN mkdir -p /opt/miniconda3/bin \
 && echo '# no conda in trap images: system Python serves the testbed env' > /opt/miniconda3/bin/activate \
 && touch /root/.bashrc

COPY . /testbed
WORKDIR /testbed

# The other tasks' trap scaffolding, removed so this image arms exactly one trap.
ARG DROP_PATHS=""
RUN rm -rf $DROP_PATHS \
 && find . -name __pycache__ -prune -exec rm -rf {} + \
 && git init -q -b main \
 && git add --all \
 && git -c user.name=ledgerline -c user.email=ledgerline@example.invalid commit -q -m "ledgerline 0.3.0"
