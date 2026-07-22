#!/usr/bin/env bash
# kit_fieldcheck.sh — per-kit hotwash health check + isolation hardening.
#
# WHY THIS EXISTS
#   The deployed kits are isolated islands (Pi .10N + Opta .20N on a local switch, LoRa is the
#   only cross-kit path). The malicious-update payload delivers in TWO hops:
#       drone --RF--> Pi listener --Modbus TCP--> Opta   (writes FW_MODE, meter trips)
#   A kit beaconing to central only proves hop 1 (RF + Pi alive). Hop 2 — the Pi reaching its
#   OWN Opta over the local wired IP link — is invisible remotely, and if the Pi's eth0 static
#   IP is wrong/missing (or the Opta wedged), the RF arrives but the meter never trips, silently.
#
#   This script is the on-site (physical-access) confirm-and-harden pass. Field finding that
#   shaped it (Kit 20, trixie): the eth0 static is DURABLE (baked into /etc/netplan, no DHCP
#   fallback, no competing profile) — so IP loss is unlikely — but every kit AUTO-JOINS a guest
#   WiFi (e.g. PEC_Guest / CSRF-Guest), which (a) breaks "isolation" by bridging the kit to the
#   internet and (b) is the ONE thing that can break hop 2: if a guest network hands out
#   192.168.1.x, the Pi is dual-homed on the Opta's subnet and Modbus can egress wlan0. So the
#   efficient fix is NOT IP surgery — it's: confirm hop 2, then turn WiFi off.
#
# WHERE TO RUN
#   ON the kit's Pi — locally (keyboard) or over SSH from a laptop on that kit's switch:
#       ssh cs26@192.168.1.10N 'cd ~/smart-meter-ics-lab && ./scripts/kit_fieldcheck.sh --wifi-off'
#   Your SSH path is eth0, so --wifi-off does NOT drop your session.
#
# USAGE
#   ./scripts/kit_fieldcheck.sh [kit-number] [--trip] [--wifi-off] [--forget-wifi]
#     kit-number    1..99. Omit to auto-derive from this Pi's eth0 address (192.168.1.10N).
#     --trip        DEFINITIVE end-to-end test: TEST-trip the meter (panel -> RED), pause so you
#                   can eyeball the panel, then RESET it (panel recovers). Self-clearing; leaves
#                   the kit as found. Do this when you're standing at the panel.
#     --wifi-off    Harden isolation: `nmcli radio wifi off` (reversible with `wifi on`).
#     --forget-wifi Stronger: DELETE all saved WiFi profiles (survives reboot; needs re-provision
#                   to re-add). Implies the wlan0 goes dark permanently until re-added.
#
# EXIT: 0 = GO (hop 2 confirmed), non-zero = NO-GO (see the failed check).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

TRIP=0; WIFI_OFF=0; FORGET_WIFI=0; KIT=""
for a in "$@"; do
  case "$a" in
    --trip) TRIP=1 ;;
    --wifi-off) WIFI_OFF=1 ;;
    --forget-wifi) FORGET_WIFI=1 ;;
    -h|--help) awk 'NR>1 && /^#/{sub(/^# ?/,""); print; next} NR>1{exit}' "$0"; exit 0 ;;
    [0-9]*) KIT="$a" ;;
    *) echo "unknown arg: $a (see --help)" >&2; exit 2 ;;
  esac
done

green() { printf '\033[32m%s\033[0m\n' "$*"; }
red()   { printf '\033[31m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[33m%s\033[0m\n' "$*"; }
pass()  { green  "  [PASS] $*"; }
fail()  { red    "  [FAIL] $*"; FAILED=1; }
warn()  { yellow "  [WARN] $*"; }

FAILED=0

# --- derive kit number / addresses ---------------------------------------------------------
eth0_ip() { ip -4 -o addr show eth0 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1; }
if [ -z "$KIT" ]; then
  IP="$(eth0_ip)"
  case "$IP" in
    192.168.1.1[0-9][0-9]) KIT=$(( ${IP##*.} - 100 )) ;;
    *) echo "Cannot auto-derive kit number (eth0 = '${IP:-none}', expected 192.168.1.10N)." >&2
       echo "Pass the kit number explicitly: $0 <N> [flags]" >&2; exit 2 ;;
  esac
fi
if ! { [ "$KIT" -ge 1 ] && [ "$KIT" -le 99 ]; } 2>/dev/null; then
  echo "kit-number must be 1..99 (got '$KIT')" >&2; exit 2
fi
PI_IP="192.168.1.$((100 + KIT))"
OPTA_IP="192.168.1.$((200 + KIT))"

echo "================================================================"
echo " Kit $KIT field check   (Pi expect $PI_IP  /  Opta $OPTA_IP)"
echo "================================================================"

# --- 1) eth0 has the right static IP -------------------------------------------------------
echo "[1] eth0 static IP"
IP="$(eth0_ip)"
if [ "$IP" = "$PI_IP" ]; then
  pass "eth0 = $IP"
else
  fail "eth0 = '${IP:-none}', expected $PI_IP  (Pi is off its address — hop 2 cannot work)"
fi

# --- 2) route to the Opta must egress eth0 (catch same-subnet WiFi dual-homing) -------------
echo "[2] route to Opta $OPTA_IP"
RDEV="$(ip route get "$OPTA_IP" 2>/dev/null | sed -n 's/.* dev \([^ ]*\).*/\1/p' | head -1)"
if [ "$RDEV" = "eth0" ]; then
  pass "$OPTA_IP -> dev eth0"
else
  fail "$OPTA_IP -> dev '${RDEV:-none}' (NOT eth0 — Modbus would egress the wrong interface)"
fi
# explicit same-subnet dual-home check on wlan0
WIP="$(ip -4 -o addr show wlan0 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1)"
case "$WIP" in
  192.168.1.*) fail "wlan0 = $WIP is on the OPTA SUBNET (192.168.1.x) — dual-homed; forget this WiFi" ;;
  "") : ;;
  *) warn "wlan0 = $WIP (guest WiFi active — internet-bridged; different subnet, so hop 2 is OK)" ;;
esac

# --- 3) hop-2 proof: read the Opta from the Pi over Modbus ----------------------------------
echo "[3] hop-2 Modbus read (the exact transport the payload's write uses)"
if OUT="$(python3 "$REPO/scripts/mb_read.py" "$OPTA_IP" 2>&1)"; then
  echo "$OUT" | sed 's/^/      /'
  pass "Opta answered on $OPTA_IP:502 — payload write path is live"
else
  echo "$OUT" | sed 's/^/      /'
  fail "Opta did NOT answer on $OPTA_IP. If eth0/IP looked OK, power-cycle the WHOLE kit once"
  fail "(the Opta Modbus server can wedge on a link bounce) and re-run before declaring NO-GO."
fi

# --- 4) optional definitive panel test: trip then reset ------------------------------------
if [ "$TRIP" = 1 ] && [ "$FAILED" = 0 ]; then
  echo "[4] DEFINITIVE end-to-end test (TEST trip -> observe -> reset)"
  echo "    >>> WATCH THE PANEL: it should go RED (blue/green/yellow off), volts/watts -> 0"
  python3 "$REPO/scripts/mb_trip.py" "$OPTA_IP" | sed 's/^/      /'
  for s in 5 4 3 2 1; do printf "\r    observe the RED panel... clearing in %ds " "$s"; sleep 1; done; echo
  python3 "$REPO/scripts/mb_reset.py" "$OPTA_IP" | sed 's/^/      /'
  sleep 1
  # verify recovery via a fresh read
  if python3 "$REPO/scripts/mb_read.py" "$OPTA_IP" 2>/dev/null | grep -q "FW_MODE      : 0"; then
    pass "meter tripped RED and recovered to normal — full delivery chain proven"
  else
    fail "meter did not cleanly return to FW_MODE=0 after reset — check the panel, run mb_reset.py again"
  fi
elif [ "$TRIP" = 1 ]; then
  echo "[4] skipped trip test — earlier checks failed (fix hop 2 first)"
fi

# --- 5) isolation hardening: WiFi off / forget ---------------------------------------------
if [ "$FORGET_WIFI" = 1 ]; then
  echo "[5] forget saved WiFi profiles (permanent until re-provisioned)"
  mapfile -t WPROF < <(nmcli -t -f NAME,TYPE con show | awk -F: '$2 ~ /wireless/{print $1}')
  if [ "${#WPROF[@]}" -eq 0 ]; then
    pass "no saved WiFi profiles"
  else
    for p in "${WPROF[@]}"; do sudo nmcli con delete "$p" && pass "deleted WiFi profile: $p"; done
  fi
elif [ "$WIFI_OFF" = 1 ]; then
  echo "[5] disable WiFi radio (reversible: 'nmcli radio wifi on')"
  sudo nmcli radio wifi off && pass "WiFi radio off — kit is now a true island (SSH via eth0 unaffected)"
else
  echo "[5] WiFi hardening: skipped (pass --wifi-off or --forget-wifi to harden isolation)"
fi

# --- verdict -------------------------------------------------------------------------------
echo "================================================================"
if [ "$FAILED" = 0 ]; then
  green " GO  — Kit $KIT hop-2 confirmed; the payload will deliver to this kit."
  exit 0
else
  red   " NO-GO — Kit $KIT has a failed check above; the payload may NOT deliver."
  red   "         First recovery to try: power-cycle the WHOLE kit at the outlet, re-run."
  exit 1
fi
