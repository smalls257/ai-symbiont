# GPU queue

One GPU job at a time, always through the wrapper:

    ops/gpu_run.sh -- <command> [args...]

The wrapper stops `llama` (Glimmer) if it is running, runs the job, and puts
`llama` back as found, on success, failure, INT and TERM. A second job is
refused while the lock is held. If a run was killed with SIGKILL the lock stays;
the next run prints the state `llama` was in, restore that by hand, then remove
the lock directory. Log: `~/gpu_run.log`.

Do not touch comfyui, open-webui or gpu_watch. No sudo.

## Tonight

| Order | Job | Command | Notes |
|-------|-----|---------|-------|
| 1 | Wrapper dry-run | `ops/gpu_run.sh -- sleep 5` | Then repeat and `kill` the wrapper (TERM); check `llama` comes back as recorded. Not yet run on the Strix. |
| 2 | Route B serving check | (Task 30) | Separate `llama-server` with Glimmer GGUF plus a tiny test adapter. |
| 3 | Route B LoRA training | (Task 30) | Cap steps to fit the night. |
