# Kit Field Check — Red-Team Quick Card

**Goal:** confirm each kit will actually trip when hit, and harden its isolation — in ~30s per kit.
Full detail + the reasoning live in `scripts/kit_fieldcheck.sh` (`--help`).

---

## Why a kit can be "up" but still not trip

The payload delivers in **two hops**. The dashboard only proves the first one.

```
  drone ──RF──▶ Pi listener ──Modbus TCP──▶ Opta   (writes FW_MODE → panel RED)
        hop 1 (beacon proves this)   hop 2 (INVISIBLE remotely)
```

If the Pi can't reach its **own** Opta over the local wired link (`.10N → .20N`), the RF arrives,
the write silently fails, and **the meter never trips** — with no signal at central. Hop 2 is what
you're here to confirm.

---

## Setup (once)

- Laptop NIC → static **`192.168.1.50/24`**, no gateway. Plug into the kit's switch.
- Kit N: Pi = `192.168.1.10N`, Opta = `192.168.1.20N`, SSH user `cs26`, key `id_ed25519`.

## Per kit — one command

```
ssh cs26@192.168.1.10N 'cd ~/smart-meter-ics-lab && ./scripts/kit_fieldcheck.sh --trip --wifi-off'
```

Reads **GO** (green) or **NO-GO** (red) at the end. Flags:
- `--trip` — trips the panel RED, pauses so you can eyeball it, then resets. **Watch the panel.**
- `--wifi-off` — kills the guest-WiFi internet bridge (safe: your SSH is over eth0). Drop it if
  you're only spot-checking.

---

## Decision flow (if you'd rather do it by hand / no laptop)

```
1. Power-cycle the WHOLE kit at the outlet   ← Pi + Opta together, not just the Pi
        (clears the Opta Modbus wedge; re-asserts an intact static IP)
2. Fire a TEST trip  →  WATCH THE PANEL
        mb_trip.py 192.168.1.20N   (or an RF payload from the drone)

   ┌─ Panel goes RED ──────────▶  GO.  mb_reset.py 192.168.1.20N  → done, move on.
   │
   └─ Panel STAYS normal ──────▶  hop 2 is broken:
            ssh in → ./scripts/kit_fieldcheck.sh --wifi-off   (checks eth0/route/Opta, shows the fault)
            re-trip. Still red-fails after a whole-kit power-cycle → escalate.
```

**Golden rule:** if the Opta stops answering right after a Pi reboot/replug, that's the known
**Modbus wedge** — power-cycle the *whole kit* once and retry before calling it NO-GO.

---

## Notes

- A kit that **tripped during the live exercise already passed hop 2** — don't re-check it. Only
  chase kits that failed to trip.
- Kits **auto-join guest WiFi** (internet bridge). Harmless to hop 2 *unless* that WiFi hands out
  `192.168.1.x` — the script flags this as a hard FAIL (`wlan0 on the Opta subnet`). `--wifi-off`
  removes the risk and restores true isolation.
- Recover a stuck panel by hand: `mb_reset.py <opta>` (TEST) · `mb_unlock.py <opta>` (EXERCISE LOCK).
