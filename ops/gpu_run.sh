#!/usr/bin/env bash
# Run one GPU job with Glimmer (the `llama` container) out of the way, then put
# `llama` back exactly as it was found.
#
#   ops/gpu_run.sh -- <command> [args...]
#
# Exists because a crashed or interrupted overnight job can leave Glimmer stopped, with
# nobody told. Every exit path (normal,
# job failure, INT, TERM) restores the recorded state and releases the lock.
# SIGKILL cannot be trapped; it leaves the lock behind on purpose, and the
# next run refuses and prints the recorded state so a human restores it.
#
# Touches only the container named below. Never uses privilege escalation;
# comfyui, open-webui and gpu_watch are left alone.
#
# INT, TERM and HUP (an ssh drop) all mean "stop": the job gets TERM to its whole
# process group, then KILL after GPU_RUN_GRACE seconds (default 30) if it is
# still there; only once the job group is gone is llama restored and the lock
# released. A signal before the job starts aborts without starting it. To make
# a job outlive the session, run the wrapper under nohup/tmux, not the job.
# The job runs in the background (job control), so it must not read the tty.
#
# The other project on this box (llm-symbiont) runs GPU jobs under flock on its own lock files.
# This wrapper takes every one of them too (polling `flock -n`, so a signal still stops the wait)
# before it stops llama, so either project's jobs wait for the other's.
#
# Exit status: the job's; 128+n if stopped by signal n; 75 lock held or foreign wait timed out;
# 64 usage; 69 docker state unreadable, stop failed, no flock, or a foreign lock dir missing;
# 70 restore failed.
#
# Environment (tests point these at temp paths):
#   GPU_RUN_LOG   default ~/gpu_run.log
#   GPU_RUN_LOCK  default ~/.gpu_run.lock  (a directory: mkdir is atomic)
#   GPU_RUN_GRACE default 30 seconds between TERM and KILL of the job
#   GPU_RUN_FOREIGN_LOCKS  space-separated flock files of other projects; default
#                          ~/llm-symbiont/gpu.lock and gpu.lock.1 (its two job slots)
#   GPU_RUN_FOREIGN_WAIT   seconds to wait for them; default 0 (wait as long as it takes)

readonly CONTAINER=llama
readonly LOG="${GPU_RUN_LOG:-$HOME/gpu_run.log}"
readonly GRACE="${GPU_RUN_GRACE:-30}"
readonly LOCK="${GPU_RUN_LOCK:-$HOME/.gpu_run.lock}"
readonly FOREIGN_LOCKS="${GPU_RUN_FOREIGN_LOCKS-$HOME/llm-symbiont/gpu.lock $HOME/llm-symbiont/gpu.lock.1}"
readonly FOREIGN_WAIT="${GPU_RUN_FOREIGN_WAIT:-0}"

holding_lock=false
llama_was_running=""   # "true" / "false" once recorded
job_pid=""
job_status=0
signaled=""

stamp() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { printf '%s %s\n' "$(stamp)" "$*" >>"$LOG"; }
die() { printf 'gpu_run: %s\n' "$*" >&2; }

llama_running() { docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null; }

acquire_lock() {
  if ! mkdir "$LOCK" 2>/dev/null; then
    die "lock held ($LOCK, pid $(cat "$LOCK/pid" 2>/dev/null || echo unknown)); one GPU job at a time"
    if [ -f "$LOCK/llama_was_running" ]; then
      die "the holder recorded llama_was_running=$(cat "$LOCK/llama_was_running"); if no job is alive, restore that state by hand and remove $LOCK"
    fi
    return 1
  fi
  holding_lock=true
  echo "$$" >"$LOCK/pid"
}

release_lock() {
  if $holding_lock; then
    rm -rf "$LOCK"
    holding_lock=false
  fi
}

restore_llama() {
  [ "$llama_was_running" = "true" ] || return 0
  if ! docker start "$CONTAINER" >/dev/null; then
    die "FAILED to start $CONTAINER; it was running before this job"
    return 1
  fi
  [ "$(llama_running)" = "true" ] || { die "$CONTAINER not running after start"; return 1; }
}

# Holds one foreign flock file open on fd $2 for the rest of the run (the job inherits it).
# Numbered fds, not {fd}: bash 3.2 (the tests' macOS shell) has no fd allocation.
take_foreign_lock() {
  local file=$1 fd=$2 waited=0
  [ -d "$(dirname "$file")" ] || { die "foreign lock dir missing for $file (set GPU_RUN_FOREIGN_LOCKS)"; return 69; }
  eval "exec $fd>>\"\$file\"" || { die "cannot open foreign lock $file"; return 69; }
  until flock -n "$fd"; do
    [ -z "$signaled" ] || return $((128 + signaled))
    if [ "$FOREIGN_WAIT" -gt 0 ] && [ "$waited" -ge "$FOREIGN_WAIT" ]; then
      die "foreign lock $file still held after ${FOREIGN_WAIT}s"
      return 75
    fi
    [ $((waited % 60)) -eq 0 ] && log "waiting for foreign lock $file (${waited}s)"
    sleep 1
    waited=$((waited + 1))
  done
  log "holding foreign lock $file"
}

take_foreign_locks() {
  local file rc fd=20
  command -v flock >/dev/null || { die "flock not found; it is how the other project locks the GPU"; return 69; }
  for file in $FOREIGN_LOCKS; do
    take_foreign_lock "$file" "$fd" || { rc=$?; return "$rc"; }
    fd=$((fd + 1))
  done
}

job_group_alive() { [ -n "$job_pid" ] && kill -0 -- "-$job_pid" 2>/dev/null; }

# Leave nothing of the job running: TERM was sent by on_signal (or is sent
# now), KILL after the grace period. Polling, not `wait`, so a second signal
# cannot cut this short and let llama restart under a live job.
stop_job() {
  job_group_alive || return 0
  kill -TERM -- "-$job_pid" 2>/dev/null
  local ticks=0 limit=$((GRACE * 10))
  while job_group_alive; do
    if [ "$ticks" -ge "$limit" ]; then
      die "job ignored TERM for ${GRACE}s; sending KILL"
      log "kill job group $job_pid after ${GRACE}s grace"
      kill -KILL -- "-$job_pid" 2>/dev/null
      limit=$((ticks + 50))   # then give KILL five seconds to take effect
    fi
    sleep 0.1
    ticks=$((ticks + 1))
  done
  wait "$job_pid" 2>/dev/null
}

finish() {
  local code=$job_status
  if [ -n "$signaled" ]; then code=$((128 + signaled)); fi
  stop_job
  if [ -n "$llama_was_running" ]; then
    if ! restore_llama; then code=70; fi
    log "end exit=$code llama_was_running=$llama_was_running restored_running=$(llama_running)"
  fi
  release_lock
  exit "$code"
}

# The first signal decides the exit code; later ones only re-send TERM.
on_signal() {
  [ -n "$signaled" ] || signaled=$1
  # Negative pid: the job's whole process group, so its children die with it.
  [ -n "$job_pid" ] && kill -TERM -- "-$job_pid" 2>/dev/null
}

main() {
  if [ "${1:-}" != "--" ] || [ $# -lt 2 ]; then
    die "usage: gpu_run.sh -- <command> [args...]"
    exit 64
  fi
  shift
  # Armed before the lock: a signal between mkdir and the traps would leave the lock behind.
  # Until llama's state is recorded there is nothing to restore: a signal only ends the wait.
  trap 'on_signal 2' INT
  trap 'on_signal 15' TERM
  trap 'on_signal 1' HUP
  acquire_lock || exit 75
  if [ -n "$signaled" ]; then release_lock; exit $((128 + signaled)); fi
  local rc=0
  take_foreign_locks || rc=$?
  if [ "$rc" -ne 0 ]; then release_lock; exit "$rc"; fi

  local state
  state=$(llama_running)
  case "$state" in
    true | false) ;;
    *) die "cannot read $CONTAINER Running state (got '$state'); not touching anything"; release_lock; exit 69 ;;
  esac
  llama_was_running=$state
  echo "$state" >"$LOCK/llama_was_running"
  trap finish EXIT
  trap 'on_signal 2' INT
  trap 'on_signal 15' TERM
  trap 'on_signal 1' HUP
  log "start llama_was_running=$state job: $*"

  if [ "$state" = "true" ] && ! docker stop "$CONTAINER" >/dev/null; then
    die "failed to stop $CONTAINER"
    job_status=69
    exit 69
  fi
  if [ -n "$signaled" ]; then
    log "signal $signaled before the job started; job not started"
    exit   # finish restores llama and releases the lock
  fi

  # Background + wait so a signal reaches our trap at once.
  set -m   # job control: the job leads its own process group
  "$@" &
  job_pid=$!
  [ -z "$signaled" ] || kill -TERM -- "-$job_pid" 2>/dev/null   # signal landed before job_pid was set
  wait "$job_pid"
  job_status=$?
  exit "$job_status"   # finish: after a signal, stop_job reaps the job first
}

main "$@"
