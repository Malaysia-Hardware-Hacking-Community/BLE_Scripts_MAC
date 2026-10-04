#!/usr/bin/env bash
#
# ble_tui.sh — orchestrator TUI for the WAMBLE toolkit and BLE-Exploits PoCs.
#
# A clean, keyboard-driven terminal UI (arrow keys / j,k / Enter / q) in the
# spirit of a Ratatui app: bordered panels, a highlighted selection, nested
# menus. It just launches the existing Python tools — no Bluetooth logic lives
# here. Authorized/educational use only; the exploit PoCs are for devices you
# own or have written permission to test.
#
# Usage:  ./ble_tui.sh
#
set -uo pipefail

# --- paths -----------------------------------------------------------------
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOLKIT="$HERE"
EXPLOITS="$HERE/BLE-Exploits"
CAPTURES="$EXPLOITS/captures"

if [[ -x "$HERE/.venv/bin/python" ]]; then
  PY="$HERE/.venv/bin/python"
else
  PY="python3"
fi

# --- style -----------------------------------------------------------------
if [[ -t 1 ]]; then
  RESET=$'\033[0m'; BOLD=$'\033[1m'; DIM=$'\033[2m'
  CYAN=$'\033[36m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
  RED=$'\033[31m'; MAGENTA=$'\033[35m'; BLUE=$'\033[34m'
  HL=$'\033[1;30;46m'   # bold black on cyan — the selected row
else
  RESET=''; BOLD=''; DIM=''; CYAN=''; GREEN=''; YELLOW=''; RED=''; MAGENTA=''; BLUE=''; HL=''
fi
W=66   # panel width

cleanup(){ printf '\033[?25h%s' "$RESET"; }   # show cursor, reset colour
trap cleanup EXIT INT TERM

clear_screen(){ printf '\033[H\033[2J'; }
hide_cursor(){ printf '\033[?25l'; }
show_cursor(){ printf '\033[?25h'; }

repeat(){ local n=$1 c=$2 out=''; while (( n-- > 0 )); do out+="$c"; done; printf '%s' "$out"; }

top(){    printf '%s╭%s╮%s\n' "$CYAN" "$(repeat $((W-2)) '─')" "$RESET"; }
bottom(){ printf '%s╰%s╯%s\n' "$CYAN" "$(repeat $((W-2)) '─')" "$RESET"; }
mid(){    printf '%s├%s┤%s\n' "$CYAN" "$(repeat $((W-2)) '─')" "$RESET"; }

# row CONTENT [selected]  — full-width line inside the panel
row(){
  local s=" $1" n sel="${2:-0}" pad
  n=${#s}; pad=$((W-2-n)); (( pad<0 )) && pad=0
  if [[ "$sel" == 1 ]]; then
    printf '%s│%s%s%s%s│%s\n' "$CYAN" "$RESET$HL" "$s$(repeat $pad ' ')" "$RESET" "$CYAN" "$RESET"
  else
    printf '%s│%s%s%s│%s\n' "$CYAN" "$RESET" "$s$(repeat $pad ' ')" "$CYAN" "$RESET"
  fi
}
title_row(){
  local s=" $1" n pad; n=${#s}; pad=$((W-2-n)); (( pad<0 )) && pad=0
  printf '%s│%s%s%s%s│%s\n' "$CYAN" "$BOLD$MAGENTA" "$s$(repeat $pad ' ')" "$RESET" "$CYAN" "$RESET"
}

banner(){
  clear_screen
  printf '%s%s  WAMBLE  %s·%s  Windows And Mac BLE toolkit & PoCs%s\n\n' \
    "$BOLD" "$CYAN" "$DIM" "$RESET$BOLD$CYAN" "$RESET"
}
footer(){ printf '\n %s%s%s\n' "$DIM" "$1" "$RESET"; }

# --- menu engine -----------------------------------------------------------
# menu "Title" item1 item2 ...   -> sets REPLY_INDEX (-1 on q/back)
REPLY_INDEX=-1
menu(){
  local title="$1"; shift
  local opts=("$@") n=$# sel=0 key k2
  hide_cursor
  while true; do
    banner
    top; title_row "$title"; mid
    local i
    for i in "${!opts[@]}"; do
      if [[ $i -eq $sel ]]; then row "► ${opts[$i]}" 1; else row "  ${opts[$i]}" 0; fi
    done
    bottom
    footer "↑/↓ or j/k · Enter select · q back"
    IFS= read -rsn1 key
    case "$key" in
      $'\033') IFS= read -rsn2 -t 0.05 k2
               case "$k2" in '[A') ((sel=(sel-1+n)%n));; '[B') ((sel=(sel+1)%n));; esac;;
      ''|$'\n'|$'\r') REPLY_INDEX=$sel; show_cursor; return 0;;
      k|K) ((sel=(sel-1+n)%n));;
      j|J) ((sel=(sel+1)%n));;
      q|Q) REPLY_INDEX=-1; show_cursor; return 0;;
    esac
  done
}

# --- input + run helpers ---------------------------------------------------
ask(){ # ask "Prompt" [default] -> echoes answer (reads from the terminal)
  local p="$1" d="${2:-}" v
  if [[ -n "$d" ]]; then
    printf '%s %s[%s]%s: ' "$p" "$DIM" "$d" "$RESET" >/dev/tty
    IFS= read -r v </dev/tty; echo "${v:-$d}"
  else
    printf '%s: ' "$p" >/dev/tty; IFS= read -r v </dev/tty; echo "$v"
  fi
}
confirm(){ local a; a="$(ask "$1 (y/N)")"; [[ "$a" == [yY]* ]]; }

run(){ # run a command, show output, pause
  show_cursor; banner
  printf ' %s▶ %s%s\n\n' "$GREEN" "$*" "$RESET"
  "$@"; local rc=$?
  printf '\n %s[exit %d] Press Enter to return…%s' "$DIM" "$rc" "$RESET"
  IFS= read -r _ </dev/tty
}

need_device(){ # echoes a device name or empty (cancelled)
  banner; ask "Target device (name substring or address)"
}

# --- toolkit actions -------------------------------------------------------
t_scan(){ banner; local s; s="$(ask 'Scan seconds' '8')"; run "$PY" "$TOOLKIT/scan_ble.py" -t "$s"; }
t_watch(){ banner; local to; to="$(ask 'Timeout seconds (blank=until Ctrl-C)' '20')"; run "$PY" "$TOOLKIT/watch_ble.py" --timeout "$to"; }
t_enum(){ local d; d="$(need_device)"; [[ -z $d ]] && return; run "$PY" "$TOOLKIT/enum_ble.py" "$d" --readable; }
t_cli(){ local d; d="$(need_device)"; [[ -z $d ]] && return; run "$PY" "$TOOLKIT/gatt_cli.py" "$d"; }
t_find(){ local d u; d="$(need_device)"; [[ -z $d ]] && return; u="$(ask 'UUID substring')"; run "$PY" "$TOOLKIT/gatt_find.py" "$d" "$u"; }
t_batt(){ local d; d="$(need_device)"; [[ -z $d ]] && return; run "$PY" "$TOOLKIT/gatt_battery.py" "$d"; }
t_info(){ local d; d="$(need_device)"; [[ -z $d ]] && return; run "$PY" "$TOOLKIT/read_device_info.py" "$d"; }
t_mtu(){ local d; d="$(need_device)"; [[ -z $d ]] && return; run "$PY" "$TOOLKIT/gatt_mtu.py" "$d"; }
t_params(){ local d; d="$(need_device)"; [[ -z $d ]] && return; run "$PY" "$TOOLKIT/gatt_params.py" "$d" --get; }

toolkit_menu(){
  while true; do
    menu "BLE Toolkit (gatttool/BlueZ-style, read-oriented)" \
      "Scan advertisements        (scan_ble)" \
      "Watch advertisements live  (watch_ble)" \
      "Enumerate GATT + reads     (enum_ble)" \
      "Interactive GATT client    (gatt_cli)" \
      "Find UUID                  (gatt_find)" \
      "Battery level              (gatt_battery)" \
      "Device information         (read_device_info)" \
      "ATT MTU                    (gatt_mtu)" \
      "Connection params (--get)  (gatt_params)" \
      "← Back"
    case $REPLY_INDEX in
      0) t_scan;; 1) t_watch;; 2) t_enum;; 3) t_cli;; 4) t_find;;
      5) t_batt;; 6) t_info;; 7) t_mtu;; 8) t_params;;
      9|-1) return;;
    esac
  done
}

# --- exploit actions (authorized / own-device) -----------------------------
e_recon(){ local d; d="$(need_device)"; [[ -z $d ]] && return; run "$PY" "$EXPLOITS/ble_recon_dump.py" "$d"; }
e_posture(){ local d; d="$(need_device)"; [[ -z $d ]] && return; run "$PY" "$EXPLOITS/ble_posture_scan.py" "$d"; }
e_notify(){ local d s; d="$(need_device)"; [[ -z $d ]] && return; s="$(ask 'Capture seconds' '12')"; run "$PY" "$EXPLOITS/ble_notify_capture.py" "$d" --duration "$s"; }
e_adv(){ local d s; d="$(need_device)"; [[ -z $d ]] && return; s="$(ask 'Listen seconds' '25')"; run "$PY" "$EXPLOITS/ble_adv_harvest.py" "$d" --timeout "$s"; }
e_led(){
  local d; d="$(need_device)"; [[ -z $d ]] && return
  banner
  if ! confirm "Authorized: do you own '$d' / have permission?"; then
    printf '\n %sNot authorized — aborting.%s\n' "$YELLOW" "$RESET"; IFS= read -r _ </dev/tty; return
  fi
  run "$PY" "$EXPLOITS/ble_led_unauth_control.py" "$d" --authorized --demo
}
e_replay(){
  local d cap; d="$(need_device)"; [[ -z $d ]] && return
  banner
  if ! confirm "Authorized: do you own '$d' / have permission?"; then
    printf '\n %sNot authorized — aborting.%s\n' "$YELLOW" "$RESET"; IFS= read -r _ </dev/tty; return
  fi
  cap="$(ask 'Capture file to replay (path under captures/)')"
  [[ -z $cap ]] && return
  [[ -f $cap ]] || cap="$CAPTURES/$cap"
  run "$PY" "$EXPLOITS/ble_replay.py" "$d" --authorized --from-capture "$cap"
}
e_deface(){
  local d; d="$(need_device)"; [[ -z $d ]] && return
  banner
  if ! confirm "Authorized: do you own '$d' / have permission?"; then
    printf '\n %sNot authorized — aborting.%s\n' "$YELLOW" "$RESET"; IFS= read -r _ </dev/tty; return
  fi
  menu "Deface $d (Device Name -> PWNED!)" "deface (write PWNED!)" "restore original name" "← Back"
  case $REPLY_INDEX in
    0) run "$PY" "$EXPLOITS/ble_deface.py" "$d" --authorized;;
    1) run "$PY" "$EXPLOITS/ble_deface.py" "$d" --authorized --restore;;
    *) return;;
  esac
}
e_persist(){
  local d phase; d="$(need_device)"; [[ -z $d ]] && return
  banner
  if ! confirm "Authorized: do you own '$d' / have permission?"; then
    printf '\n %sNot authorized — aborting.%s\n' "$YELLOW" "$RESET"; IFS= read -r _ </dev/tty; return
  fi
  menu "Persistence phase for $d" "arm (set state, then power-cycle)" "verify (after reboot)" "← Back"
  case $REPLY_INDEX in
    0) local hex; hex="$(ask 'Value to persist, hex (known-valid!)')"; [[ -z $hex ]] && return
       run "$PY" "$EXPLOITS/ble_persistence_test.py" arm "$d" --authorized --write "$hex";;
    1) run "$PY" "$EXPLOITS/ble_persistence_test.py" verify "$d" --authorized;;
    *) return;;
  esac
}

exploit_menu(){
  while true; do
    menu "BLE-Exploits  ·  authorized / own-device only" \
      "Unauthenticated GATT harvest   (recon, read-only)" \
      "Security-posture assessment    (posture, read-only)" \
      "Notification capture           (notify, read-only)" \
      "Passive advertisement harvest  (adv, no connection)" \
      "LED control PoC                (led, gated)" \
      "Capture-replay / forgery       (replay, gated)" \
      "Persistence across reboot      (persistence, gated)" \
      "Device-name deface → PWNED!    (deface, gated)" \
      "← Back"
    case $REPLY_INDEX in
      0) e_recon;; 1) e_posture;; 2) e_notify;; 3) e_adv;; 4) e_led;; 5) e_replay;; 6) e_persist;; 7) e_deface;;
      8|-1) return;;
    esac
  done
}

# --- BLE CTF client (gatttool-style handle I/O) ----------------------------
ctf_menu(){
  banner
  local dev; dev="$(ask 'CTF device name/address' 'M0DUL0CTF')"
  [[ -z $dev ]] && return
  local C=("$PY" "$TOOLKIT/ble_ctf.py" -b "$dev")
  while true; do
    menu "BLE CTF client — target: $dev" \
      "Enumerate (handles)" \
      "Score (read 0x002a)" \
      "MTU check (flag 16 reachability)" \
      "Read handle" \
      "Write hex to handle" \
      "Write string to handle" \
      "Submit flag string (0x002c)" \
      "Listen notify/indicate + trigger" \
      "Read-loop (flag 10)" \
      "← Back"
    local h v s c
    case $REPLY_INDEX in
      0) run "${C[@]}" enum;;
      1) run "${C[@]}" score;;
      2) run "${C[@]}" mtu;;
      3) h="$(ask 'Handle (e.g. 0x002e)')"; [[ -n $h ]] && run "${C[@]}" read -a "$h";;
      4) h="$(ask 'Handle')"; v="$(ask 'Hex value (e.g. 41)')"; [[ -n $h && -n $v ]] && run "${C[@]}" write -a "$h" -n "$v";;
      5) h="$(ask 'Handle')"; s="$(ask 'String')"; [[ -n $h ]] && run "${C[@]}" writestr -a "$h" -s "$s";;
      6) s="$(ask 'Flag string')"; [[ -n $s ]] && run "${C[@]}" submit -s "$s";;
      7) h="$(ask 'Handle')"; v="$(ask 'Trigger hex (blank = none)')"
         [[ -z $h ]] && continue
         if [[ -n $v ]]; then run "${C[@]}" listen -a "$h" -n "$v"; else run "${C[@]}" listen -a "$h"; fi;;
      8) h="$(ask 'Handle' '0x003e')"; c="$(ask 'Count' '1001')"; run "${C[@]}" readloop -a "$h" -c "$c";;
      9|-1) return;;
    esac
  done
}

# --- captures viewer -------------------------------------------------------
view_captures(){
  if [[ ! -d "$CAPTURES" ]] || [[ -z "$(ls -A "$CAPTURES" 2>/dev/null)" ]]; then
    banner; printf ' %sNo captures yet.%s\n' "$YELLOW" "$RESET"; IFS= read -r _ </dev/tty; return
  fi
  local files=() f
  while IFS= read -r f; do files+=("$(basename "$f")"); done < <(ls -1t "$CAPTURES"/*.json 2>/dev/null)
  files+=("← Back")
  while true; do
    menu "Evidence captures ($CAPTURES)" "${files[@]}"
    local idx=$REPLY_INDEX
    if [[ $idx -lt 0 || $idx -ge $(( ${#files[@]} - 1 )) ]]; then return; fi
    run "$PY" -m json.tool "$CAPTURES/${files[$idx]}"
  done
}

# --- dependency check ------------------------------------------------------
check_deps(){
  if ! "$PY" -c 'import bleak, rich' >/dev/null 2>&1; then
    banner
    printf ' %sbleak/rich not available to %s%s\n\n' "$RED" "$PY" "$RESET"
    printf ' Create the venv first:\n\n   %scd %s\n   python3 -m venv .venv && source .venv/bin/activate\n   pip install -r requirements.txt%s\n\n' \
      "$DIM" "$TOOLKIT" "$RESET"
    printf ' Press Enter to continue anyway, or Ctrl-C to quit… '
    IFS= read -r _ </dev/tty
  fi
}

# --- main ------------------------------------------------------------------
check_deps
while true; do
  menu "Main menu" \
    "BLE Toolkit        — scan, enumerate, read/write" \
    "BLE-Exploits       — authorized vulnerability PoCs" \
    "BLE CTF client     — gatttool-style handle I/O" \
    "View captures      — JSON evidence" \
    "Quit"
  case $REPLY_INDEX in
    0) toolkit_menu;;
    1) exploit_menu;;
    2) ctf_menu;;
    3) view_captures;;
    4|-1) break;;
  esac
done
clear_screen
