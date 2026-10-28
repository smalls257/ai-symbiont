#!/usr/bin/env bash
# Prevents a Silent Fallback in the gate  # expect: sym-no-framework-names-in-shell-comments
# Violations prevented: see the plan  # expect: sym-no-framework-names-in-shell-comments
# Sensor -> restore timing first  # expect: sym-no-framework-names-in-shell-comments
# a plain why: the filter buffers the sensor input and the engine anchors it
echo "Silent Fallback in a message is fine"
