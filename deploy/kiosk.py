#!/usr/bin/env python3
"""Dedicated X11 kiosk: EDID-based landscape mode and a supervised browser."""
import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen


def output_modes(query):
    """Return connected HDMI outputs and their non-interlaced landscape modes."""
    outputs = {}
    active = None
    for line in query.splitlines():
        if line and not line[0].isspace():
            fields = line.split()
            active = fields[0] if len(fields) > 1 and fields[1] == 'connected' and fields[0].startswith('HDMI') else None
            if active:
                outputs[active] = []
        elif active:
            match = re.match(r'\s+(\d+)x(\d+)\s+', line)
            if match:
                width, height = map(int, match.groups())
                if width >= height and width <= 1920 and height <= 1080:
                    outputs[active].append((width, height))
    return outputs


def configure_display():
    query = subprocess.check_output(['xrandr', '--query'], text=True, stderr=subprocess.DEVNULL)
    for output, modes in output_modes(query).items():
        if not modes:
            print(f'{output}: no supported landscape mode at or below 1080p', flush=True)
            continue
        # Preserve the panel's native aspect where possible: EDID lists its
        # preferred mode first. Select the first supported mode within X5 limits.
        width, height = modes[0]
        mode = f'{width}x{height}'
        current = re.search(rf'^{re.escape(output)} connected(?: primary)? (\d+x\d+)\+', query, re.M)
        if not current or current.group(1) != mode:
            subprocess.run(['xrandr', '--output', output, '--mode', mode, '--rotate', 'normal', '--primary'], check=True)
            print(f'HDMI mode: {output} {mode}', flush=True)
    return query


def preferred_usb_sink(sinks):
    """Ignore HDMI/built-in audio while choosing an attached USB speaker."""
    return next((sink for sink in sinks if sink.get('properties', {}).get('device.bus') == 'usb'), None)


def configure_audio():
    """Follow a USB speaker plugged in after boot; leave its volume to the user."""
    def pactl(*args):
        return subprocess.check_output(['pactl', *args], text=True, stderr=subprocess.DEVNULL, timeout=3)

    sink = preferred_usb_sink(json.loads(pactl('-f', 'json', 'list', 'sinks')))
    if not sink:
        return
    if pactl('get-default-sink').strip() != sink['name']:
        pactl('set-default-sink', sink['name'])
        print(f'Audio output: {sink["name"]}', flush=True)
    for stream in json.loads(pactl('-f', 'json', 'list', 'sink-inputs')):
        props = stream.get('properties', {})
        application = (props.get('application.process.binary', '') + ' ' + props.get('application.name', '')).lower()
        if ('chromium' in application or 'chrome' in application) and stream.get('sink') != sink['index']:
            pactl('move-sink-input', str(stream['index']), sink['name'])


def main():
    port = int(os.environ.get('WALL_PORT', '8091'))
    url = f'http://127.0.0.1:{port}/'
    while True:
        try:
            configure_display()
            with urlopen(url + 'api/health', timeout=2) as response:
                if response.status == 200:
                    break
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(2)
    subprocess.run(['xset', 's', 'off'], check=False)
    subprocess.run(['xset', '-dpms'], check=False)
    # Chromium's fullscreen request needs an EWMH window manager. Bare Xorg
    # otherwise leaves the kiosk at its restored/default window dimensions.
    manager = subprocess.Popen(['/usr/bin/xfwm4', '--compositor=off'])
    for _ in range(50):
        if manager.poll() is not None:
            raise SystemExit('Window manager exited before becoming ready')
        wm_state = subprocess.run(['xprop', '-root', '_NET_SUPPORTING_WM_CHECK'], capture_output=True, text=True)
        if 'window id #' in wm_state.stdout:
            break
        time.sleep(0.2)
    else:
        manager.terminate()
        raise SystemExit('Window manager did not become ready')
    profile = Path('/var/lib/aws-wall-kiosk/chromium')
    profile.mkdir(parents=True, exist_ok=True)
    args = [
        '/usr/bin/chromium', '--ozone-platform=x11', '--kiosk', '--no-first-run',
        '--no-default-browser-check', '--disable-session-crashed-bubble',
        '--disable-background-networking', '--disable-component-update',
        '--disable-sync', '--password-store=basic', '--disable-features=Translate',
        '--disable-gpu', '--force-device-scale-factor=1',
        '--autoplay-policy=no-user-gesture-required',
        f'--user-data-dir={profile}',
    ]
    if os.environ.get('WALL_REDUCED_MOTION', '0') == '1':
        args.append('--force-prefers-reduced-motion')
    # Optional diagnostics bind only to loopback; normally disabled.
    debug_port = os.environ.get('WALL_DEBUG_PORT')
    if debug_port:
        args.extend(['--remote-debugging-address=127.0.0.1', f'--remote-debugging-port={int(debug_port)}'])
    url += '?kiosk=1'
    if os.environ.get('WALL_EFFECTS', 'off') == 'off':
        url += '&effects=off'
    args.append(url)
    print(f'Starting Chromium kiosk: {url}', flush=True)
    try:
        configure_audio()
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    browser = subprocess.Popen(args)

    def stop(_signum, _frame):
        browser.terminate()
        manager.terminate()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while browser.poll() is None:
        if manager.poll() is not None:
            browser.terminate()
            raise SystemExit('Window manager exited; restarting kiosk')
        time.sleep(5)
        try:
            configure_display()
        except (OSError, subprocess.SubprocessError) as error:
            print(f'Display unavailable, waiting for reconnect: {error}', flush=True)
        try:
            configure_audio()
        except (OSError, ValueError, subprocess.SubprocessError):
            # An absent speaker/PulseAudio must not interrupt the game.
            pass
    manager.terminate()
    raise SystemExit(browser.returncode)


if __name__ == '__main__':
    main()
