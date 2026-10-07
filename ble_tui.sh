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
# Scan results are cached here so one scan can feed many actions (see
# pick_device). Per-PID path keeps concurrent TUIs from clobbering each other.
SCAN_CACHE="${TMPDIR:-/tmp}/wamble_scan.$$.json"
SCAN_SECONDS=8   # default scan duration for the picker

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
  EL=$'\033[K'          # erase to end of line (kills leftovers without a full clear)
else
  RESET=''; BOLD=''; DIM=''; CYAN=''; GREEN=''; YELLOW=''; RED=''; MAGENTA=''; BLUE=''; HL=''; EL=''
fi
VERSION="0.1.1"
MIN_W=40   # narrowest the panel is allowed to get
MAX_W=72   # widest it will grow, so lines stay readable on a big terminal
# Layout globals recomputed each frame by compute_layout, so the UI follows a
# terminal resize: COLS/LINES_ hold the terminal size, W the panel width, PAD
# the left margin that centers the panel, and COMPACT/BANNER_H the banner size.
COLS=80; LINES_=24; W=$MAX_W; PAD=''; COMPACT=0; BANNER_H=9

cleanup(){ printf '\033[?25h%s' "$RESET"; rm -f "$SCAN_CACHE"; }   # show cursor, reset colour, drop scan cache
trap cleanup EXIT INT TERM

clear_screen(){ printf '\033[H\033[2J'; }
home(){ printf '\033[H'; }            # cursor home, no erase — the basis of flicker-free redraw
clear_below(){ printf '\033[J'; }     # erase from cursor to end of screen
hide_cursor(){ printf '\033[?25l'; }
show_cursor(){ printf '\033[?25h'; }

# Visible terminal rows, read from the controlling tty so it is correct even
# when stdout is redirected (as in the device picker's `menu >/dev/tty`).
term_lines(){
  local sz; sz=$(stty size </dev/tty 2>/dev/null) || sz=""
  sz=${sz%% *}
  [[ $sz =~ ^[0-9]+$ ]] && printf '%s' "$sz" || printf '24'
}

# Visible terminal columns, read from the controlling tty like term_lines.
term_cols(){
  local sz; sz=$(stty size </dev/tty 2>/dev/null) || sz=""
  sz=${sz##* }
  [[ $sz =~ ^[0-9]+$ ]] && printf '%s' "$sz" || printf '80'
}

# Recompute the responsive layout from the current terminal size. Called at the
# top of every menu frame and by banner_body, so panel width, centering and
# banner height all track a live resize.
compute_layout(){
  COLS=$(term_cols); LINES_=$(term_lines)
  W=$MAX_W
  (( W > COLS - 2 )) && W=$(( COLS - 2 ))
  (( W < MIN_W ))    && W=$MIN_W
  (( W > COLS ))     && W=$COLS          # pathologically narrow terminal
  local lp=$(( (COLS - W) / 2 )); (( lp < 0 )) && lp=0
  PAD=$(repeat "$lp" ' ')
  # Drop the wombat on a short or narrow terminal so the list keeps its room.
  if (( LINES_ >= 20 && COLS >= 24 )); then COMPACT=0; BANNER_H=9; else COMPACT=1; BANNER_H=2; fi
}

repeat(){ local n=$1 c=$2 out=''; while (( n-- > 0 )); do out+="$c"; done; printf '%s' "$out"; }

# Each primitive ends its line with $EL so a redraw overwrites in place and
# wipes any trailing characters, instead of blanking the whole screen first.
top(){    printf '%s%s╭%s╮%s'"$EL"'\n' "$PAD" "$CYAN" "$(repeat $((W-2)) '─')" "$RESET"; }
bottom(){ printf '%s%s╰%s╯%s'"$EL"'\n' "$PAD" "$CYAN" "$(repeat $((W-2)) '─')" "$RESET"; }
mid(){    printf '%s%s├%s┤%s'"$EL"'\n' "$PAD" "$CYAN" "$(repeat $((W-2)) '─')" "$RESET"; }

# row CONTENT [selected]  — full-width line inside the panel, PAD-centered.
# Content longer than the panel is truncated so it never breaks the border.
row(){
  local s=" $1" sel="${2:-0}" max=$((W-2)) pad
  (( ${#s} > max )) && s="${s:0:max}"
  pad=$(( max - ${#s} )); (( pad<0 )) && pad=0
  if [[ "$sel" == 1 ]]; then
    printf '%s%s│%s%s%s%s│%s'"$EL"'\n' "$PAD" "$CYAN" "$RESET$HL" "$s$(repeat $pad ' ')" "$RESET" "$CYAN" "$RESET"
  else
    printf '%s%s│%s%s%s│%s'"$EL"'\n' "$PAD" "$CYAN" "$RESET" "$s$(repeat $pad ' ')" "$CYAN" "$RESET"
  fi
}
title_row(){
  local s=" $1" max=$((W-2)) pad
  (( ${#s} > max )) && s="${s:0:max}"
  pad=$(( max - ${#s} )); (( pad<0 )) && pad=0
  printf '%s%s│%s%s%s%s│%s'"$EL"'\n' "$PAD" "$CYAN" "$BOLD$MAGENTA" "$s$(repeat $pad ' ')" "$RESET" "$CYAN" "$RESET"
}

# cline TEXT [COLOR] — print TEXT centered across the whole terminal width, with
# $EL so a redraw overwrites cleanly. Used for the banner's single-line rows.
cline(){
  local text="$1" color="${2:-}" lp
  lp=$(( (COLS - ${#text}) / 2 )); (( lp < 0 )) && lp=0
  printf '%s%s%s%s'"$EL"'\n' "$(repeat "$lp" ' ')" "$color" "$text" "$RESET"
}

# banner_body draws without clearing (for flicker-free redraw); banner clears
# first, for one-shot screens (run output, prompts). It recomputes the layout so
# a direct caller (banner/run) centers correctly too, and shows the wombat only
# when the terminal is big enough, falling back to a one-line banner otherwise.
banner_body(){
  compute_layout
  if (( COMPACT )); then
    cline "WAMBLE v$VERSION  Windows And Mac BLE" "$BOLD$CYAN"
    printf '%s'"$EL"'\n'
    return
  fi
  # The wombat mascot, centered as a block so its shape is preserved. Drawn
  # squat and broad with a big nose and small rounded ears, the way a wombat is.
  local art=('   __      __   ' '  /  \____/  \  ' ' / o        o \ ' '(     (__)     )' ' \            / ' "  '-||----||-'  ")
  local art_w=16 line alp ap
  alp=$(( (COLS - art_w) / 2 )); (( alp < 0 )) && alp=0
  ap=$(repeat "$alp" ' ')
  for line in "${art[@]}"; do
    printf '%s%s%s%s'"$EL"'\n' "$ap" "$CYAN" "$line" "$RESET"
  done
  cline "WAMBLE  v$VERSION" "$BOLD$CYAN"
  cline "Windows And Mac BLE toolkit & PoCs" "$DIM"
  printf '%s'"$EL"'\n'
}
banner(){ clear_screen; banner_body; }
footer(){ printf '%s'"$EL"'\n%s %s%s%s'"$EL"'\n' '' "$PAD" "$DIM" "$1" "$RESET"; }

# --- menu engine -----------------------------------------------------------
# menu "Title" item1 item2 ...   -> sets REPLY_INDEX (-1 on q/back)
REPLY_INDEX=-1
menu(){
  local title="$1"; shift
  local opts=("$@") n=$# sel=0 top0=0 key k2 i win avail H last_size=""
  hide_cursor
  clear_screen            # one clean slate on entry; every frame after redraws in place
  while true; do
    # Fit the list to the terminal: show a scrolling window of `win` rows around
    # the selection rather than letting a long list overflow and scroll.
    compute_layout; H=$LINES_
    # Full clear on a resize so no stale wider/taller frame is left behind.
    if [[ "${COLS}x${LINES_}" != "$last_size" ]]; then clear_screen; last_size="${COLS}x${LINES_}"; fi
    # chrome below the banner: top/title/mid(3)+bottom(1)+footer(2)+2 scroll hints
    avail=$(( H - BANNER_H - 8 ))
    (( avail < 3 )) && avail=3
    win=$n; (( win > avail )) && win=$avail
    (( sel < top0 )) && top0=$sel
    (( sel >= top0 + win )) && top0=$(( sel - win + 1 ))
    (( top0 > n - win )) && top0=$(( n - win ))
    (( top0 < 0 )) && top0=0

    home; banner_body
    top; title_row "$title"; mid
    (( top0 > 0 )) && row "  ▲ $top0 more above" 0
    for (( i = top0; i < top0 + win; i++ )); do
      if (( i == sel )); then row "► ${opts[$i]}" 1; else row "  ${opts[$i]}" 0; fi
    done
    (( top0 + win < n )) && row "  ▼ $(( n - top0 - win )) more below" 0
    bottom
    footer "↑/↓ or j/k · Enter select · q back"
    clear_below           # wipe anything left from a taller previous screen
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

# --- device picker ---------------------------------------------------------
# need_device is called as  d="$(need_device)"  so ONLY the chosen identifier
# may reach stdout. Every bit of UI (banner, menu, prompts) is therefore drawn
# to /dev/tty — writing it to stdout would capture the ANSI banner into the
# device name and break the match. The scan is cached in $SCAN_CACHE so one
# scan feeds many actions; "Rescan now" refreshes it.

run_scan_to_cache(){ # $1 = seconds; progress + table shown on the tty
  local secs="${1:-$SCAN_SECONDS}"
  "$PY" "$TOOLKIT/scan_ble.py" -t "$secs" --write-to "$SCAN_CACHE" >/dev/tty 2>&1
  printf '\n %sPress Enter to choose a device…%s' "$DIM" "$RESET" >/dev/tty
  IFS= read -r _ </dev/tty
}

# Emit "addr<TAB>rssi<TAB>name" per cached device, strongest signal first.
parse_scan_cache(){
  [[ -s "$SCAN_CACHE" ]] || return 0
  "$PY" - "$SCAN_CACHE" <<'PYEOF'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
devs = data.get("devices", []) or []
devs.sort(key=lambda d: d.get("rssi") if d.get("rssi") is not None else -999,
          reverse=True)
for d in devs:
    addr = str(d.get("address", "")).strip()
    if not addr:
        continue
    rssi = d.get("rssi")
    # Never emit an empty field: IFS=<tab> in the bash reader collapses runs of
    # tabs, so an empty RSSI would merge columns and misalign the row.
    rssi = "—" if rssi is None else str(rssi)
    name = (d.get("name") or "(unnamed)").replace("\t", " ").replace("\n", " ")
    print(f"{addr}\t{rssi}\t{name}")
PYEOF
}

pick_device(){ # echoes a device identifier, or nothing if cancelled
  [[ -s "$SCAN_CACHE" ]] || run_scan_to_cache "$SCAN_SECONDS"
  while true; do
    local addrs=() labels=() addr rssi name lbl
    while IFS=$'\t' read -r addr rssi name; do
      [[ -z $addr ]] && continue
      addrs+=("$addr")
      printf -v lbl '%-28.28s %6s dBm  %.8s…' "$name" "$rssi" "$addr"
      labels+=("$lbl")
    done < <(parse_scan_cache)

    local opts=("↻ Rescan now")
    [[ ${#addrs[@]} -gt 0 ]] && opts+=("${labels[@]}")
    opts+=("⌨  Type a name/address manually")

    menu "Target device — pick from last scan" "${opts[@]}" >/dev/tty
    local idx=$REPLY_INDEX ndev=${#addrs[@]}

    if (( idx < 0 )); then
      return                                   # q/back → cancel
    elif (( idx == 0 )); then
      run_scan_to_cache "$SCAN_SECONDS"; continue
    elif (( idx == ndev + 1 )); then
      ask "Target device (name substring or address)"; return   # manual
    else
      printf '%s\n' "${addrs[idx-1]}"; return   # picked a scanned device
    fi
  done
}

need_device(){ pick_device; }

# --- toolkit actions -------------------------------------------------------
t_scan(){ banner; local s; s="$(ask 'Scan seconds' '8')"; run "$PY" "$TOOLKIT/scan_ble.py" -t "$s" --write-to "$SCAN_CACHE"; }
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
main(){
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
}

# Run the UI only when executed directly; sourcing exposes the functions alone
# (so the picker and menu engine can be driven from a test harness).
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main
fi
