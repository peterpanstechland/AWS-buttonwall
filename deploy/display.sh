#!/bin/bash
set -euo pipefail

# RDK's vs-drm connector cache can stay "unknown" after boot until a DRM
# client probes it. Merely reading sysfs forever will never start the kiosk.
if command -v modetest >/dev/null 2>&1; then
    echo 'Probing and waiting for an HDMI display'
    while true; do
        timeout 5 modetest -M vs-drm -c >/dev/null 2>&1 || true
        if grep -qs '^connected$' /sys/class/drm/card*-HDMI-*/status; then
            break
        fi
        sleep 3
    done
fi
# If modetest is absent, Xorg performs the probe and systemd retries on failure.

# Xorg owns the VT; Chromium runs separately as sunrise with cookie auth.
auth=/run/aws-wall-display/Xauthority
umask 027
touch "$auth"
xauth -f "$auth" add :0 . "$(mcookie)"
chgrp sunrise "$auth"
chmod 640 "$auth"
chvt 7
exec /usr/bin/Xorg :0 -auth "$auth" -nolisten tcp -noreset -s 0 -dpms vt7
