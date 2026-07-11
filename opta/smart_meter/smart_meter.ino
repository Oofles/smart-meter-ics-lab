/*
 * smart-meter-ics-lab -- Opta smart-meter simulation + Modbus TCP server.
 *
 * Implemented as a plain Arduino sketch (arduino:mbed_opta) flashed over USB.
 * The Arduino PLC IDE online link would not connect on this bench across three
 * IDE versions, so the IEC 61131-3 path was abandoned for a sketch. Functionally
 * identical rig: same Modbus contract, same FW_MODE trip scenario.
 *
 * Contract: docs/register-map.md   (0-based PDU addresses below)
 *   Coil  0   POWER_STATUS   1=powered 0=fault                 written by Opta
 *   Coil 15   RESET          write 1 to clear fault             written by ops
 *   HReg  0   VOLTAGE_X10    volts x10 (1200 = 120.0 V)         written by Opta
 *   HReg  1   POWER_W        instantaneous watts                written by Opta
 *   HReg  9   FW_MODE        0=normal, !=0=malicious update     written by listener
 *   DIn 0..3  lamp mirror    blue/green/yellow/red states       written by Opta (read-only)
 *   DIn 4..5  switch mirror  I1/I2 switch states                written by Opta (read-only)
 *
 * Operator HMI (blue-team panel). In NORMAL state the panel is operator-driven:
 *   I1 switch  -> O1 BLUE     (operator turns comms/power-present light on)
 *   I2 switch  -> O2 GREEN    (operator turns the second light on)
 *   dial >= 6  -> O3 YELLOW   (voltage dial past 6 of 0-10)
 *   O4 RED is off.
 * On a delivered "malicious firmware update" (FW_MODE != 0, via the listener/Modbus)
 * the meter FAULTS: O1/O2/O3 force OFF, O4 RED on, VOLTAGE_X10/POWER_W -> 0.
 * RESET coil or the I3 button clears FW_MODE and the panel resumes following the inputs.
 * (There is intentionally NO local trip switch: the fault only fires from FW_MODE, so a
 * direct-Modbus attacker or the RF payload is what trips it -- see docs/register-map.md.)
 *
 * Physical I/O (plccable Opta trainer):
 *   O1=D0 blue   O2=D1 green   O3=D2 yellow   O4=D3 red
 *   I1=A0 blue switch   I2=A1 green switch   I3=A2 reset button   I5=A4 voltage dial
 *   Note: relays only switch when the Opta is on its 12-24 V supply.
 */
#include <SPI.h>
#include <Ethernet.h>
#include <ArduinoRS485.h>   // required dependency of ArduinoModbus, even for TCP
#include <ArduinoModbus.h>

// ---- network ----
// Patchable per-kit config: provision/opta_flash.sh <last-octet> stamps the IP host byte into
// the prebuilt firmware at flash time — it finds the "KITCFGv1" magic and rewrites the 4th IP
// octet — so ONE .bin serves every kit (kit N -> 192.168.1.(200+N)). `volatile const` keeps the
// bytes in flash (not constant-folded away) and forces a runtime read. Layout: 8-byte magic +
// IP(4 octets). Do not reorder or the flasher's offset breaks.
__attribute__((used)) volatile const uint8_t KIT_NETCFG[] = {
  'K', 'I', 'T', 'C', 'F', 'G', 'v', '1', 192, 168, 1, 210
};
IPAddress ip;                                  // set from KIT_NETCFG in setup()
IPAddress dnsServer(192, 168, 1, 1);
IPAddress gateway(192, 168, 1, 1);
IPAddress subnet(255, 255, 255, 0);
EthernetServer ethServer(502);
ModbusTCPServer mb;

// ---- modbus map (0-based PDU addresses) ----
enum { COIL_POWER_STATUS = 0, COIL_RESET = 15 };
enum { HREG_VOLTAGE_X10 = 0, HREG_POWER_W = 1, HREG_FW_MODE = 9 };
// FW_MODE values: 0=normal, 1=malicious TEST trip (operator RESET clears it), 2=malicious
// EXERCISE LOCK (operator RESET is IGNORED; cleared only by a direct FW_MODE:=0 write — the
// facilitator "re-flash"). NOTE: RAM only for now, so a power-cycle also clears it; flash
// persistence across reboots is a planned follow-up (KVStore hard-faults on this H7).
enum { FW_NORMAL = 0, FW_TEST = 1, FW_LOCKED = 2 };
// diagnostics (raw ADC counts, 12-bit) so we can see the physical inputs over Modbus
enum { HREG_RAW_BLUE = 20, HREG_RAW_RESET = 21, HREG_RAW_DIAL = 22, HREG_RAW_GREEN = 23 };
// panel mirror for SCADA (read-only discrete inputs the Opta drives)
enum { DIN_LAMP_BLUE = 0, DIN_LAMP_GREEN = 1, DIN_LAMP_YELLOW = 2, DIN_LAMP_RED = 3,
       DIN_SW_BLUE = 4, DIN_SW_GREEN = 5 };

// analog inputs are 0..4095 (12-bit); ~2000 counts ≈ 5.3 V at the terminal.
const int IN_THRESHOLD = 2000;
// yellow comes on when the voltage dial is past 6 on its 0..10 scale.
const float DIAL_YELLOW_V = 6.0f;

// ---- physical I/O ----
const int RLY_BLUE = D0, RLY_GREEN = D1, RLY_YELLOW = D2, RLY_RED = D3;
const int IN_BLUE = A0, IN_GREEN = A1, IN_RESET = A2, IN_DIAL = A4;

// ---- simulation state ----
const int P_MIN = 300, P_MAX = 1500;
uint32_t rng = 0x1234567;
long powerWalk = 750;
uint32_t lastTick = 0;

static uint16_t rnd() { rng = rng * 1103515245u + 12345u; return (uint16_t)(rng >> 16); }

// dial terminal voltage, ~0..10.9 V (the 0.3034 divider matches the trainer wiring).
static float dialVolts() { return analogRead(IN_DIAL) * (3.3f / 4095.0f) / 0.3034f; }

// drive the four lamps (relays) and mirror their state to SCADA in one place.
void setLamps(bool blue, bool green, bool yellow, bool red) {
  digitalWrite(RLY_BLUE,   blue   ? HIGH : LOW);
  digitalWrite(RLY_GREEN,  green  ? HIGH : LOW);
  digitalWrite(RLY_YELLOW, yellow ? HIGH : LOW);
  digitalWrite(RLY_RED,    red    ? HIGH : LOW);
  mb.discreteInputWrite(DIN_LAMP_BLUE,   blue);
  mb.discreteInputWrite(DIN_LAMP_GREEN,  green);
  mb.discreteInputWrite(DIN_LAMP_YELLOW, yellow);
  mb.discreteInputWrite(DIN_LAMP_RED,    red);
}

void applyNormal(bool swBlue, bool swGreen) {
  mb.coilWrite(COIL_POWER_STATUS, 1);
  // voltage follows the bench dial (0..~10 V -> 0..240.0 V x10) with small jitter
  float v = dialVolts();
  int vx10 = (int)(v * 240.0f) + ((int)(rnd() & 0x0F) - 8);
  if (vx10 < 0) vx10 = 0;
  if (vx10 > 2500) vx10 = 2500;
  mb.holdingRegisterWrite(HREG_VOLTAGE_X10, (uint16_t)vx10);
  // instantaneous power: random walk in [P_MIN, P_MAX]
  powerWalk += (int)(rnd() & 0x1F) - 16;
  if (powerWalk < P_MIN) powerWalk = P_MIN;
  if (powerWalk > P_MAX) powerWalk = P_MAX;
  mb.holdingRegisterWrite(HREG_POWER_W, (uint16_t)powerWalk);
  // operator panel: blue=I1 switch, green=I2 switch, yellow=dial past 6, red off
  setLamps(swBlue, swGreen, v >= DIAL_YELLOW_V, false);
  digitalWrite(LED_D0, HIGH);   // onboard LED = "powered" (works on USB, no 12-24 V needed)
}

void applyFault() {
  mb.coilWrite(COIL_POWER_STATUS, 0);
  mb.holdingRegisterWrite(HREG_VOLTAGE_X10, 0);
  mb.holdingRegisterWrite(HREG_POWER_W, 0);
  // malicious update: all operator outputs off, red on
  setLamps(false, false, false, true);
  digitalWrite(LED_D0, LOW);
}

void meterTick() {
  // read the physical inputs as analog and publish raw counts for diagnostics
  int rawBlue  = analogRead(IN_BLUE);
  int rawGreen = analogRead(IN_GREEN);
  int rawReset = analogRead(IN_RESET);
  int rawDial  = analogRead(IN_DIAL);
  mb.holdingRegisterWrite(HREG_RAW_BLUE,  (uint16_t)rawBlue);
  mb.holdingRegisterWrite(HREG_RAW_GREEN, (uint16_t)rawGreen);
  mb.holdingRegisterWrite(HREG_RAW_RESET, (uint16_t)rawReset);
  mb.holdingRegisterWrite(HREG_RAW_DIAL,  (uint16_t)rawDial);

  bool swBlue  = rawBlue  > IN_THRESHOLD;
  bool swGreen = rawGreen > IN_THRESHOLD;
  mb.discreteInputWrite(DIN_SW_BLUE,  swBlue);    // mirror physical switch position for SCADA
  mb.discreteInputWrite(DIN_SW_GREEN, swGreen);

  long fw = mb.holdingRegisterRead(HREG_FW_MODE);
  if (fw < 0) fw = 0;
  bool coilReset  = mb.coilRead(COIL_RESET) > 0;
  bool localReset = rawReset > IN_THRESHOLD;

  // Operator RESET (SCADA coil / I3 button) clears a TEST trip (FW_MODE=1) but is IGNORED for
  // an exercise LOCK (FW_MODE=2) — the blue team can't reset their way out; only a direct
  // FW_MODE:=0 write (facilitator "re-flash") clears it. Always ack the coil so it doesn't stick.
  if (coilReset || localReset) {
    mb.coilWrite(COIL_RESET, 0);
    if (fw != FW_LOCKED) {
      fw = 0;
      mb.holdingRegisterWrite(HREG_FW_MODE, 0);
    }
  }
  // no local trip: the fault only fires from FW_MODE (RF payload / listener / Modbus write)
  // NOTE: FW_MODE is RAM only — a power-cycle clears even a LOCK. Flash-persisting the lock
  // across reboots is a planned follow-up (FlashIAP reserved sector; KVStore hard-faults here).

  if (fw == 0) applyNormal(swBlue, swGreen);
  else         applyFault();                // FW_MODE 1 (test) or 2 (locked) both fault identically
}

void setup() {
  analogReadResolution(12);
  pinMode(RLY_BLUE, OUTPUT);
  pinMode(RLY_GREEN, OUTPUT);
  pinMode(RLY_YELLOW, OUTPUT);
  pinMode(RLY_RED, OUTPUT);
  pinMode(LED_D0, OUTPUT);
  pinMode(IN_BLUE, INPUT);
  pinMode(IN_GREEN, INPUT);
  pinMode(IN_RESET, INPUT);

  ip = IPAddress(KIT_NETCFG[8], KIT_NETCFG[9], KIT_NETCFG[10], KIT_NETCFG[11]);  // patchable per kit
  Ethernet.begin(NULL, ip, dnsServer, gateway, subnet);   // static, non-blocking
  ethServer.begin();
  mb.begin();                                              // unit id 0xff = answer all
  mb.configureCoils(0x00, 16);                             // coils 0..15
  mb.configureHoldingRegisters(0x00, 25);                  // hregs 0..9 + diag 20..23
  mb.configureDiscreteInputs(0x00, 6);                     // panel mirror 0..5

  rng ^= (uint32_t)analogRead(IN_DIAL) + 1;                // seed jitter from dial noise
  applyNormal(false, false);                               // boot in a sane state
}

void loop() {
  EthernetClient client = ethServer.available();
  if (client) {
    mb.accept(client);
    while (client.connected()) {
      mb.poll();
      if (millis() - lastTick >= 500) { lastTick = millis(); meterTick(); }
    }
  } else {
    if (millis() - lastTick >= 500) { lastTick = millis(); meterTick(); }
  }
}
