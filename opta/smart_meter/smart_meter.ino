/*
 * smart-meter-ics-lab -- Opta smart-meter simulation + Modbus TCP server.
 *
 * Implemented as a plain Arduino sketch (arduino:mbed_opta) flashed over USB.
 * The Arduino PLC IDE online link would not connect on this bench across three
 * IDE versions, so the IEC 61131-3 path was abandoned for a sketch. Functionally
 * identical rig: same Modbus contract, same FW_MODE trip scenario.
 *
 * Contract: docs/register-map.md   (0-based PDU addresses below)
 *   Coil  0   POWER_STATUS  1=powered(green) 0=fault(red)   written by Opta
 *   Coil 15   RESET         write 1 to clear fault           written by ops
 *   HReg  0   VOLTAGE_X10   volts x10 (1200 = 120.0 V)       written by Opta
 *   HReg  1   POWER_W       instantaneous watts              written by Opta
 *   HReg  9   FW_MODE       0=normal, !=0=malicious update   written by listener
 *
 * Physical I/O (plccable Opta trainer):
 *   O1=D0 blue   O2=D1 green   O3=D2 yellow   O4=D3 red
 *   I1=A0 switch (local trip)   I3=A2 button (local reset)   I5=A4 dial (analog)
 *   Note: relays only switch when the Opta is on its 12-24 V supply.
 */
#include <SPI.h>
#include <Ethernet.h>
#include <ArduinoRS485.h>   // required dependency of ArduinoModbus, even for TCP
#include <ArduinoModbus.h>

// ---- network ----
IPAddress ip(192, 168, 1, 210);
IPAddress dnsServer(192, 168, 1, 1);
IPAddress gateway(192, 168, 1, 1);
IPAddress subnet(255, 255, 255, 0);
EthernetServer ethServer(502);
ModbusTCPServer mb;

// ---- modbus map (0-based PDU addresses) ----
enum { COIL_POWER_STATUS = 0, COIL_RESET = 15 };
enum { HREG_VOLTAGE_X10 = 0, HREG_POWER_W = 1, HREG_FW_MODE = 9 };
// diagnostics (raw ADC counts, 12-bit) so we can see the physical inputs over Modbus
enum { HREG_RAW_TRIP = 20, HREG_RAW_RESET = 21, HREG_RAW_DIAL = 22 };

// analog inputs are 0..4095 (12-bit); ~2000 counts ≈ 5.3 V at the terminal.
const int IN_THRESHOLD = 2000;

// ---- physical I/O ----
const int RLY_BLUE = D0, RLY_GREEN = D1, RLY_YELLOW = D2, RLY_RED = D3;
const int IN_TRIP = A0, IN_RESET = A2, IN_DIAL = A4;

// ---- simulation state ----
const int P_MIN = 300, P_MAX = 1500;
uint32_t rng = 0x1234567;
long powerWalk = 750;
uint32_t lastTick = 0;

static uint16_t rnd() { rng = rng * 1103515245u + 12345u; return (uint16_t)(rng >> 16); }

void applyNormal() {
  mb.coilWrite(COIL_POWER_STATUS, 1);
  // voltage follows the bench dial (0..~10 V -> 0..240.0 V x10) with small jitter
  float v = analogRead(IN_DIAL) * (3.3f / 4095.0f) / 0.3034f;   // ~0..10.9 V
  int vx10 = (int)(v * 240.0f) + ((int)(rnd() & 0x0F) - 8);
  if (vx10 < 0) vx10 = 0;
  if (vx10 > 2500) vx10 = 2500;
  mb.holdingRegisterWrite(HREG_VOLTAGE_X10, (uint16_t)vx10);
  // instantaneous power: random walk in [P_MIN, P_MAX]
  powerWalk += (int)(rnd() & 0x1F) - 16;
  if (powerWalk < P_MIN) powerWalk = P_MIN;
  if (powerWalk > P_MAX) powerWalk = P_MAX;
  mb.holdingRegisterWrite(HREG_POWER_W, (uint16_t)powerWalk);
  // lamps: green on, red off, blue = "alive"
  digitalWrite(RLY_GREEN, HIGH);
  digitalWrite(RLY_RED, LOW);
  digitalWrite(RLY_BLUE, HIGH);
  digitalWrite(RLY_YELLOW, LOW);
  digitalWrite(LED_D0, HIGH);
}

void applyFault() {
  mb.coilWrite(COIL_POWER_STATUS, 0);
  mb.holdingRegisterWrite(HREG_VOLTAGE_X10, 0);
  mb.holdingRegisterWrite(HREG_POWER_W, 0);
  digitalWrite(RLY_GREEN, LOW);
  digitalWrite(RLY_RED, HIGH);
  digitalWrite(RLY_BLUE, LOW);
  digitalWrite(RLY_YELLOW, LOW);
  digitalWrite(LED_D0, LOW);
}

void meterTick() {
  // read the physical inputs as analog and publish raw counts for diagnostics
  int rawTrip  = analogRead(IN_TRIP);
  int rawReset = analogRead(IN_RESET);
  int rawDial  = analogRead(IN_DIAL);
  mb.holdingRegisterWrite(HREG_RAW_TRIP,  (uint16_t)rawTrip);
  mb.holdingRegisterWrite(HREG_RAW_RESET, (uint16_t)rawReset);
  mb.holdingRegisterWrite(HREG_RAW_DIAL,  (uint16_t)rawDial);

  long fw = mb.holdingRegisterRead(HREG_FW_MODE);
  if (fw < 0) fw = 0;
  bool coilReset  = mb.coilRead(COIL_RESET) > 0;
  bool localReset = rawReset > IN_THRESHOLD;
  bool localTrip  = rawTrip  > IN_THRESHOLD;

  if (coilReset || localReset) {            // clear fault back to normal
    fw = 0;
    mb.holdingRegisterWrite(HREG_FW_MODE, 0);
    mb.coilWrite(COIL_RESET, 0);            // self-clear the reset coil
  }
  if (localTrip) {                          // bench switch = local "malicious update"
    fw = 1;
    mb.holdingRegisterWrite(HREG_FW_MODE, 1);
  }

  if (fw == 0) applyNormal();
  else         applyFault();
}

void setup() {
  analogReadResolution(12);
  pinMode(RLY_BLUE, OUTPUT);
  pinMode(RLY_GREEN, OUTPUT);
  pinMode(RLY_YELLOW, OUTPUT);
  pinMode(RLY_RED, OUTPUT);
  pinMode(LED_D0, OUTPUT);
  pinMode(IN_TRIP, INPUT);
  pinMode(IN_RESET, INPUT);

  Ethernet.begin(NULL, ip, dnsServer, gateway, subnet);   // static, non-blocking
  ethServer.begin();
  mb.begin();                                              // unit id 0xff = answer all
  mb.configureCoils(0x00, 16);                             // coils 0..15
  mb.configureHoldingRegisters(0x00, 25);                  // hregs 0..9 + diag 20..22

  rng ^= (uint32_t)analogRead(IN_DIAL) + 1;                // seed jitter from dial noise
  applyNormal();                                           // boot in a sane state
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
