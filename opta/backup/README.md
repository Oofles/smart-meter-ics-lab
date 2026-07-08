# Opta factory/preloaded firmware backup

Full flash backup of the **Arduino Opta (AFX00003, Opta WiFi)** as it shipped from
plccable.com, taken **before** repurposing the board for this lab. Provisioning the
board for the Arduino PLC IDE overwrites the M7 application slot, so this is the restore
point for the original demo.

> **This is a binary image, not source.** DFU can only read the compiled firmware back
> off the chip; the original `.ino`/C++ source is not recoverable from it. For editable
> source, request it from plccable.com / Arduino. This backup lets us *restore* the
> original behavior, not read it.

## Files

| File | Region | Size | SHA-256 |
|------|--------|------|---------|
| `opta_internal_flash.bin` | Internal flash `0x08000000` | 2 MiB | `86fb32b4ac208304b07d7d6dfcf75dc374fcd3bc1784b4aa8986028adc73b869` |
| `opta_qspi_flash.bin` | External QSPI `0x90000000` | 16 MiB | `dffab0dd410657cb30c7b2fd7f2586a4792e8472e58882b3532581f8111a646d` |
| `SHA256SUMS.txt` | — | — | checksums for `sha256sum -c` |

`opta_qspi_flash.bin` (16 MiB) is **git-ignored** by default to avoid bloating the repo —
it is mostly the stock WiFi/BLE firmware + FAT filesystem and is largely identical across
Opta units. It is kept locally in this folder and its checksum is recorded here. If you
want it version-controlled, track it via Git LFS. The **internal flash image is the one
that matters** (it is the actual program) and it *is* committed.

## What the preloaded program is (from image analysis)

- **Arduino sketch**, built with the `arduino:mbed_opta` core **3.5.4** (build path
  `.../packages/arduino/hardware/mbed_opta/3.5.4/...` is embedded in the binary).
- Acts as a **Modbus server** (`read_input_bits`, `read_input_registers`,
  `Unknown Modbus function code: 0x%0X`).
- **WiFi-enabled** (WiFi scan/connect logic, `WiFiFirmwareUpdater` reference).
- Banner strings: `>>> Finder OPTA`, `>>> Arduino OPTA`, `>>> OPTA - 2023-07-13 15:38:21 <<<`
  — the official Finder/Arduino OPTA demonstration example, build-dated 2023-07-13.
- Single-core: **M7 app only**, the M4 slot (`0x08180000`) is erased.

## Flash layout (from `dfu-util -l`)

DFU device in bootloader mode: **`2341:0364`** (DfuSe, DFU 1.1a).

| alt | Region | Base | Geometry | Notes |
|-----|--------|------|----------|-------|
| 0 | Internal Flash | `0x08000000` | `01*128Ka,15*128Kg` = 16 × 128 KiB = 2 MiB | bootloader + apps |
| 1 | External Flash (QSPI) | `0x90000000` | `4096*4Kg` = 16 MiB | WiFi fw + filesystem |
| 2 | Bootloader | `0x00000000` | info only | MCUboot "version 22" |

Non-empty internal-flash sectors (128 KiB each):

| Sector | Address | Contents |
|--------|---------|----------|
| 0 | `0x08000000` | MCUboot bootloader (~112 KiB used) |
| 2–4 | `0x08040000`–`0x08083FFF` | M7 application (~270 KiB) |
| 12 | `0x08180000` | M4 slot — **empty** |
| others | — | erased (`0xFF`) |

M7 app vector table @ `0x08040000`: initial SP `0x24080000`, reset vector `0x0806CD81`
(both valid) — confirms a complete, bootable image.

## How this backup was made

1. Board was in its normal running state (slow-green LED, USB CDC on a COM port).
   The **user button does not enter the bootloader** on this unit (the sketch owns it) —
   use one of:
   - **1200-baud touch** on the COM port (what we used): open the serial port at 1200 bps
     and close it → the mbed core resets into the DFU bootloader (green reset LED breathes).
   - **Double-tap the recessed RESET button** (not the user button) as a hardware fallback.
2. Confirm the DFU device: `dfu-util -l` → `Found DFU: [2341:0364] ... alt=0 "@Internal Flash"`.
3. Read (upload) each region — **non-destructive**, reads only:
   ```
   dfu-util -a 0 -s 0x08000000:0x200000  -U opta_internal_flash.bin   # 2 MiB internal
   dfu-util -a 1 -s 0x90000000:0x1000000 -U opta_qspi_flash.bin       # 16 MiB QSPI
   ```
   (dfu-util path in this setup:
   `…/Arduino15/packages/arduino/tools/dfu-util/0.10.0-arduino1/dfu-util.exe`.)

## Restore procedure

To put the original demo back on the board later:

1. Enter DFU (1200-baud touch, or double-tap RESET).
2. Write the internal flash image back (**do not interrupt** a download):
   ```
   dfu-util -a 0 -s 0x08000000 -D opta_internal_flash.bin
   ```
   This restores bootloader + M7 app (an exact copy of what was read). To touch only the
   application and leave the bootloader alone, flash just the app region instead
   (slice the file from offset `0x40000` and write with `-s 0x08040000`).
3. Only if the WiFi/filesystem was disturbed, also restore QSPI:
   ```
   dfu-util -a 1 -s 0x90000000 -D opta_qspi_flash.bin
   ```
4. Reset / power-cycle → the board boots back into the original slow-green demo.

Verify integrity any time with: `sha256sum -c SHA256SUMS.txt`.
