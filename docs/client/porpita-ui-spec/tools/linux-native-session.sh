#!/usr/bin/env bash
set -euo pipefail
umask 077

mode=$1
stage=$(realpath "$2")
name=$3
[[ "$stage" =~ ^/tmp/porpita-ui[0-9]+\.[A-Za-z0-9]{8}$ && "$name" =~ ^native-[a-z0-9-]+$ ]]
run="$stage/$name"
tools="$stage/os-tools/usr"
libs="$tools/lib/x86_64-linux-gnu"

if [[ "$mode" == run || "$mode" == run-wayland || "$mode" == run-gnome ]]; then
  mkdir "$run"
  mkdir -m 700 "$run/home" "$run/cache" "$run/config" "$run/data" "$run/runtime" "$run/tmp"
  unset DISPLAY XAUTHORITY WAYLAND_DISPLAY SWAYSOCK DBUS_SESSION_BUS_ADDRESS AT_SPI_BUS_ADDRESS
  export HOME="$run/home" XDG_CACHE_HOME="$run/cache" XDG_CONFIG_HOME="$run/config"
  export XDG_DATA_HOME="$run/data" XDG_RUNTIME_DIR="$run/runtime" TMPDIR="$run/tmp"
  export LANG=C.UTF-8 LANGUAGE=en LC_ALL=C.UTF-8
  export PATH="$tools/bin:$PATH" LD_LIBRARY_PATH="$libs:$libs/pulseaudio"
  export XDG_DATA_DIRS="$tools/share:/usr/local/share:/usr/share"
  export PYTHONPATH="$tools/lib/python3/dist-packages"
  if [[ "$mode" != run ]]; then
    reader_prefix="$stage/reader51/usr"
    reader_libs="$reader_prefix/lib/x86_64-linux-gnu"
    export GI_TYPELIB_PATH="$reader_libs/girepository-1.0"
    export XDG_DATA_DIRS="$reader_prefix/share:$XDG_DATA_DIRS"
    export PORPITA_NATIVE_DISPLAY=wayland XDG_SESSION_TYPE=wayland GDK_BACKEND=wayland
    if [[ "$mode" == run-gnome ]]; then
      unset GNOME_KEYRING_CONTROL
      export LD_LIBRARY_PATH="$reader_libs:$LD_LIBRARY_PATH"
      export PORPITA_NATIVE_COMPOSITOR=gnome XDG_CURRENT_DESKTOP=GNOME LIBGL_ALWAYS_SOFTWARE=1
    else
      compositor="$stage/compositor/usr"
      export PORPITA_NATIVE_COMPOSITOR=sway
      export PATH="$compositor/bin:$PATH"
      export LD_LIBRARY_PATH="$reader_libs:$compositor/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"
    fi
    exec dbus-run-session -- bash "$0" inside "$stage" "$name" "${@:4}"
  fi
  export PORPITA_NATIVE_DISPLAY=x11 PORPITA_NATIVE_COMPOSITOR=openbox XDG_SESSION_TYPE=x11 GDK_BACKEND=x11
  exec xvfb-run -a -s '-screen 0 1280x900x24 -nolisten tcp' \
    dbus-run-session -- bash "$0" inside "$stage" "$name" "${@:4}"
fi

[[ "$mode" == inside ]]
test "$HOME" = "$run/home"
test "$XDG_RUNTIME_DIR" = "$run/runtime"

children=()
cleanup() {
  for ((i=${#children[@]}-1; i>=0; i--)); do
    kill -TERM "${children[i]}" 2>/dev/null || :
  done
  sleep .4
  for pid in "${children[@]}"; do
    if [[ -r "/proc/$pid/environ" ]] &&
      grep -azFxq "HOME=$run/home" "/proc/$pid/environ"; then
      kill -KILL "$pid" 2>/dev/null || :
    fi
  done
  wait || :
}
trap cleanup EXIT
trap 'exit 130' INT TERM

start_sway() {
  cat > "$run/sway.conf" <<'CONF'
xwayland disable
output HEADLESS-1 mode 1060x790
default_border none
focus_follows_mouse no
input type:keyboard xkb_layout us
CONF
  WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_LIBINPUT_NO_DEVICES=1 \
    sway --unsupported-gpu --config "$run/sway.conf" > "$run/wm.log" 2>&1 &
  children+=("$!")
  for _ in {1..60}; do
    ipc=("$XDG_RUNTIME_DIR"/sway-ipc.*.sock)
    display=("$XDG_RUNTIME_DIR"/wayland-*)
    if [[ -S "${ipc[0]}" && -S "${display[0]}" ]]; then break; fi
    sleep .1
  done
  if [[ ! -S "${ipc[0]}" || ! -S "${display[0]}" ]]; then
    tail -20 "$run/wm.log" >&2
    exit 1
  fi
  export SWAYSOCK="${ipc[0]}" WAYLAND_DISPLAY="${display[0]##*/}"
  dbus-update-activation-environment WAYLAND_DISPLAY SWAYSOCK XDG_SESSION_TYPE GDK_BACKEND
  printf '%s\n' "$WAYLAND_DISPLAY" > "$run/display"
  swaymsg -rt get_version > "$run/compositor.json"
  wayland-info > "$run/wayland-globals.txt"
  grep -q zwp_virtual_keyboard_manager_v1 "$run/wayland-globals.txt"
  wtype -M shift -m shift -s 300000 > "$run/keyboard.log" 2>&1 &
  children+=("$!")
}

start_gnome() {
  /usr/bin/python3 -c 'import secrets; print(secrets.token_hex(32), end="")' | \
    env -u LD_LIBRARY_PATH gnome-keyring-daemon --foreground --unlock --components=secrets \
      > "$run/keyring.log" 2>&1 &
  children+=("$!")
  for _ in {1..40}; do
    if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
      --method org.freedesktop.DBus.NameHasOwner org.freedesktop.secrets | grep -q true; then
      break
    fi
    sleep .15
  done
  gdbus call --session --dest org.freedesktop.secrets --object-path /org/freedesktop/secrets \
    --method org.freedesktop.Secret.Service.ReadAlias default | grep -Fq /org/freedesktop/secrets/collection/login
  gdbus call --session --dest org.freedesktop.secrets --object-path /org/freedesktop/secrets/collection/login \
    --method org.freedesktop.DBus.Properties.Get org.freedesktop.Secret.Collection Locked | grep -q false
  pipewire > "$run/pipewire.log" 2>&1 &
  children+=("$!")
  for _ in {1..40}; do
    [[ -S "$XDG_RUNTIME_DIR/pipewire-0" ]] && break
    sleep .15
  done
  test -S "$XDG_RUNTIME_DIR/pipewire-0"
  wireplumber -c policy.conf > "$run/wireplumber.log" 2>&1 &
  children+=("$!")
  gsettings set org.gnome.desktop.input-sources sources "[('xkb', 'us')]"
  env -u LD_LIBRARY_PATH -u PYTHONPATH -u GI_TYPELIB_PATH gnome-shell --headless --wayland --no-x11 \
    --wayland-display wayland-0 --virtual-monitor 1440x900 > "$run/wm.log" 2>&1 &
  children+=("$!")
  for _ in {1..60}; do
    if [[ -S "$XDG_RUNTIME_DIR/wayland-0" ]] &&
      gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner org.gnome.Mutter.ScreenCast | grep -q true; then
      break
    fi
    sleep .2
  done
  test -S "$XDG_RUNTIME_DIR/wayland-0"
  export WAYLAND_DISPLAY=wayland-0
  dbus-update-activation-environment WAYLAND_DISPLAY XDG_SESSION_TYPE GDK_BACKEND XDG_CURRENT_DESKTOP
  printf '%s\n' "$WAYLAND_DISPLAY" > "$run/display"
  /usr/bin/python3 - "$run/wm.log" > "$run/compositor.json" <<'PY'
import json
import re
import sys
from pathlib import Path

log = Path(sys.argv[1]).read_text()
version = re.search(r"Running GNOME Shell \(using mutter ([^)]+)\) as a Wayland display server", log)
if not version:
    raise SystemExit("GNOME Shell Wayland identity missing")
print(json.dumps({"human_readable": "GNOME Shell / Mutter " + version[1],
                  "monitor": [1440, 900], "xwayland": False}))
PY
  /usr/bin/python3 "$stage/gnome-wayland-control.py" serve > "$run/mutter-control.log" 2>&1 &
  children+=("$!")
  for _ in {1..75}; do
    [[ -S "$XDG_RUNTIME_DIR/mutter-observer.sock" ]] && break
    sleep .2
  done
  if [[ ! -S "$XDG_RUNTIME_DIR/mutter-observer.sock" ]]; then
    cat "$run/mutter-control.log" >&2
    exit 1
  fi
}

if [[ "$PORPITA_NATIVE_DISPLAY" == wayland ]]; then
  test -z "${DISPLAY:-}"
  reader_prefix="$stage/reader51/usr"
  "$reader_prefix/libexec/at-spi-bus-launcher" --launch-immediately \
    > "$run/atspi-bus.log" 2>&1 &
  children+=("$!")
  for _ in {1..40}; do
    owner=$(gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
      --method org.freedesktop.DBus.NameHasOwner org.a11y.Bus)
    if [[ "$owner" == '(true,)' ]]; then break; fi
    sleep .1
  done
  [[ "$owner" == '(true,)' ]]
  AT_SPI_BUS_ADDRESS=$(gdbus call --session --dest org.a11y.Bus --object-path /org/a11y/bus \
    --method org.a11y.Bus.GetAddress | cut -d "'" -f 2)
  export AT_SPI_BUS_ADDRESS
  test -n "$AT_SPI_BUS_ADDRESS"
  DBUS_SESSION_BUS_ADDRESS="$AT_SPI_BUS_ADDRESS" "$reader_prefix/libexec/at-spi2-registryd" \
    > "$run/atspi-registry.log" 2>&1 &
  children+=("$!")
  export PORPITA_NATIVE_RUN="$run"
  if [[ "$PORPITA_NATIVE_COMPOSITOR" == gnome ]]; then
    start_gnome
  else
    start_sway
  fi
else
  [[ "$DISPLAY" =~ ^:[0-9]+$ && "$XAUTHORITY" == "$run/tmp/"*/Xauthority ]]
  test -O "$XAUTHORITY"
  display_pid=$(tr -d ' ' < "/tmp/.X${DISPLAY#:}-lock")
  [[ "$(tr '\0' ' ' < "/proc/$display_pid/cmdline")" == *"Xvfb $DISPLAY "* ]]
  printf '%s\n' "$DISPLAY" > "$run/display"
  setxkbmap -layout us
  openbox --sm-disable --config-file "$stage/os-tools/etc/xdg/openbox/rc.xml" > "$run/wm.log" 2>&1 &
  children+=("$!")
  for _ in {1..40}; do
    xprop -root _NET_SUPPORTING_WM_CHECK | grep -q 'window id' && break
    sleep .1
  done
  xprop -root _NET_SUPPORTING_WM_CHECK | grep -q 'window id'
fi
gsettings set org.gnome.desktop.interface toolkit-accessibility true
gdbus call --session --dest org.a11y.Bus --object-path /org/a11y/bus \
  --method org.a11y.Bus.GetAddress >/dev/null

export PULSE_SERVER="unix:$XDG_RUNTIME_DIR/pulse.sock"
modules=$(dirname "$(find "$tools/lib" -name module-null-sink.so -print -quit)")
LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$modules" "$tools/bin/pulseaudio" \
  --daemonize=no --exit-idle-time=-1 -n -p "$modules" \
  -L "module-native-protocol-unix socket=$XDG_RUNTIME_DIR/pulse.sock auth-anonymous=1" \
  -L 'module-null-sink sink_name=porpita-validation' > "$run/pulse.log" 2>&1 &
children+=("$!")
for _ in {1..40}; do
  pactl info >/dev/null 2>&1 && break
  sleep .25
done
pactl list short sinks | grep -q 'porpita-validation'
pactl set-default-sink porpita-validation

export SPEECHD_ADDRESS="unix_socket:$XDG_RUNTIME_DIR/speech"
speech-dispatcher --run-single --timeout 0 --socket-path "$XDG_RUNTIME_DIR/speech" \
  --pid-file "$XDG_RUNTIME_DIR/speech.pid" --log-dir "$run" > "$run/speechd.log" 2>&1 &
children+=("$!")
for _ in {1..40}; do
  [[ -S "$XDG_RUNTIME_DIR/speech" ]] && break
  sleep .25
done
test -S "$XDG_RUNTIME_DIR/speech"

reader=(/usr/bin/orca)
reader_options=(--user-prefs "$run/orca" --enable=speech --disable=braille)
if [[ "$PORPITA_NATIVE_DISPLAY" == wayland ]]; then
  reader=(/usr/bin/python3 -c
    'import runpy,sys; root=sys.argv.pop(1); sys.path.insert(0, root+"/usr/lib/python3/dist-packages"); runpy.run_path(root+"/usr/bin/orca", run_name="__main__")'
    "$stage/reader51")
  reader_options=()
fi
"${reader[@]}" --version > "$run/orca-version.txt"
"${reader[@]}" "${reader_options[@]}" \
  --debug-file "$run/orca-private.log" > "$run/orca.log" 2>&1 &
children+=("$!")
printf '%s\n' "$!" > "$run/orca.pid"
for _ in {1..60}; do
  if grep -Fq 'SPEECH OUTPUT:' "$run/orca-private.log" 2>/dev/null; then break; fi
  sleep .25
done
if ! grep -Fq 'SPEECH OUTPUT:' "$run/orca-private.log"; then
  tail -20 "$run/orca.log" >&2
  exit 1
fi
kill -0 "$(cat "$run/orca.pid")"

export PORPITA_NATIVE_RUN="$run"
export PORPITA_NATIVE_STAGE="$stage"
"${@:4}"
