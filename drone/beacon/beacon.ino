/*
 * drone/beacon — LoRa injector for the smart-meter exercise.
 *
 * ⛔ DEAD END — DOES NOT WORK against the Pi's Waveshare HAT. Kept for the record only.
 * The HAT is an EBYTE E22-900T (SX1262 behind an onboard MCU, proprietary framing) and does
 * NOT interoperate with this raw-SX1262/RadioLib transmitter. Proven both directions across
 * the full SF/BW×sync grid = 0 reception. Use a 2nd EBYTE/Waveshare HAT as the drone instead.
 * See drone/README.md.
 *
 * Heltec WiFi LoRa 32 V4 (ESP32-S3 + SX1262, 868 MHz) — the drone payload. Transmits our
 * SMFW "firmware update" frame as a RAW LoRa packet with the PHY of the meters'
 * Waveshare/EBYTE SX1262 UART HATs, so the meters receive it (transparent mode emits the
 * payload byte-for-byte on their UART) and flood it across the mesh. Frame matches
 * listener/protocol.py. Status shown on the onboard OLED.
 *
 * BRING-UP: SWEEP=true cycles the full SF/BW grid (sync 0x12 fixed; SF11/BW500 first),
 * tagging each frame's msg_id low nibble with the combo index. When a meter HAT receives one,
 * listener.py prints "RX update msg_id=0x....C00i" -> low nibble i = the winning combo. Then
 * set SWEEP=false, LOCK=i, re-flash to inject the real malicious frame.
 *
 * RadioLib 7.x + U8g2 + esp32 core 3.x.
 */
#include <RadioLib.h>
#include <U8g2lib.h>

// ---- OLED (Heltec V4: SDA=17 SCL=18 RST=21; Vext=36 active-low powers it) ----
#define OLED_SDA 17
#define OLED_SCL 18
#define OLED_RST 21
#define VEXT     36
U8G2_SSD1306_128X64_NONAME_F_SW_I2C u8g2(U8G2_R0, OLED_SCL, OLED_SDA, OLED_RST);

// ---- radio (Heltec V4: NSS=8 DIO1=14 RST=12 BUSY=13; SPI SCK=9 MISO=11 MOSI=10) ----
SX1262 radio = new Module(8, 14, 12, 13);

// ---- SMFW frame (mirror of listener/protocol.py) ----
static uint16_t crc16(const uint8_t* d, size_t n) {
  uint16_t c = 0xFFFF;
  for (size_t i = 0; i < n; i++) {
    c ^= (uint16_t)d[i] << 8;
    for (int b = 0; b < 8; b++) c = (c & 0x8000) ? ((c << 1) ^ 0x1021) : (c << 1);
  }
  return c;
}
static size_t buildFrame(uint8_t* out, uint8_t type, uint16_t msgid, uint8_t ttl) {
  size_t n = 0;
  out[n++] = 'S'; out[n++] = 'M'; out[n++] = 'F'; out[n++] = 'W';
  out[n++] = 1; out[n++] = type;
  out[n++] = msgid >> 8; out[n++] = msgid & 0xFF; out[n++] = ttl;
  uint16_t c = crc16(out, n);
  out[n++] = c >> 8; out[n++] = c & 0xFF;
  return n;   // 11 bytes
}

// ---- PHY sweep table: SF/BW candidates x sync word ----
struct Combo { float bw; uint8_t sf; uint8_t sync; const char* name; };
Combo COMBOS[] = {
  // Live HAT config (read off the Pi via `C1 00 09`): freq 868.125 (ch 18),
  // transparent mode, air-rate index 2 ("2.4k"). EBYTE does NOT publish the
  // air-rate -> SF/BW map, so we sweep the full grid. TX is confirmed good
  // (radio.begin=0, tx=0), so this pass isolates the last variable: SYNC is
  // now 0x12 (private, EBYTE's word) on every row — the old 0x34 (public) was
  // overriding radio.begin() and receiving nothing. Strong prior: SF11/BW500
  // (~2.15 kbps ~ "2.4k", and the sketch's own begin() default).
  {500.0, 11, 0x12, "SF11 BW500"}, {125.0,  9, 0x12, "SF9 BW125"},  {250.0, 10, 0x12, "SF10 BW250"},
  {125.0,  7, 0x12, "SF7 BW125"},  {125.0,  8, 0x12, "SF8 BW125"},  {125.0, 10, 0x12, "SF10 BW125"},
  {125.0, 11, 0x12, "SF11 BW125"}, {125.0, 12, 0x12, "SF12 BW125"}, {250.0,  7, 0x12, "SF7 BW250"},
  {250.0,  8, 0x12, "SF8 BW250"},  {250.0,  9, 0x12, "SF9 BW250"},  {250.0, 11, 0x12, "SF11 BW250"},
  {250.0, 12, 0x12, "SF12 BW250"}, {500.0,  7, 0x12, "SF7 BW500"},  {500.0,  8, 0x12, "SF8 BW500"},
  {500.0,  9, 0x12, "SF9 BW500"},  {500.0, 10, 0x12, "SF10 BW500"}, {500.0, 12, 0x12, "SF12 BW500"},
};
const int NCOMBO = sizeof(COMBOS) / sizeof(COMBOS[0]);

const bool SWEEP = true;   // true=find PHY; false=inject using LOCK
const int  LOCK  = 0;      // once known: SWEEP=false, LOCK=<winning combo index>

uint8_t  cycle = 0;
uint32_t txCount = 0;

void applyCombo(int i) {
  radio.setBandwidth(COMBOS[i].bw);
  radio.setSpreadingFactor(COMBOS[i].sf);
  radio.setSyncWord(COMBOS[i].sync);
}

void oled(const char* l1, const char* l2, const char* l3, const char* l4) {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x12_tr);
  u8g2.drawStr(0, 11, l1);
  u8g2.drawStr(0, 26, l2);
  u8g2.drawStr(0, 41, l3);
  u8g2.drawStr(0, 56, l4);
  u8g2.sendBuffer();
}

void setup() {
  Serial.begin(115200);
  delay(600);
  pinMode(VEXT, OUTPUT); digitalWrite(VEXT, LOW); delay(60);   // power OLED
  u8g2.begin();
  oled("SMART-METER LAB", "DRONE BEACON", "init radio...", "");
  SPI.begin(9, 11, 10, 8);
  int st = radio.begin(868.125, 500.0, 11, 5, 0x12, 22, 12, 1.8, false);
  Serial.printf("radio.begin -> %d\n", st);
  radio.setDio2AsRfSwitch(true);
  radio.setCodingRate(5);
  radio.setCRC(true);
  radio.explicitHeader();
  char b[24]; snprintf(b, sizeof(b), "radio begin=%d", st);
  oled("DRONE BEACON", SWEEP ? "mode: PHY sweep" : "mode: INJECT", b, "868.125 MHz");
  delay(1000);
}

void loop() {
  if (SWEEP) {
    for (int i = 0; i < NCOMBO; i++) {
      applyCombo(i);
      uint16_t mid = 0xC000 + (cycle % 100) * 32 + i;   // decode: combo = (mid-0xC000) % 32
      uint8_t f[16]; size_t n = buildFrame(f, 0x00 /*benign during sweep*/, mid, 3);
      int st = radio.transmit(f, n); txCount++;
      Serial.printf("cyc%u combo%d [%s] msgid=0x%04X tx=%d\n", cycle, i, COMBOS[i].name, mid, st);
      char l2[22], l3[22], l4[22];
      snprintf(l2, sizeof(l2), "c%d %s", i, COMBOS[i].name);
      snprintf(l3, sizeof(l3), "msgid %04X", mid);
      snprintf(l4, sizeof(l4), "tx#%lu ok=%d", (unsigned long)txCount, st == RADIOLIB_ERR_NONE);
      oled("SWEEP: find PHY", l2, l3, l4);
      delay(1800);
    }
    cycle++;
  } else {
    applyCombo(LOCK);
    uint16_t mid = 0xA000 | (cycle++ & 0x0FFF);
    uint8_t f[16]; size_t n = buildFrame(f, 0x01 /*MALICIOUS*/, mid, 3);
    int st = radio.transmit(f, n); txCount++;
    Serial.printf("INJECT malicious [%s] msgid=0x%04X tx=%d\n", COMBOS[LOCK].name, mid, st);
    char l3[22], l4[22];
    snprintf(l3, sizeof(l3), "%s", COMBOS[LOCK].name);
    snprintf(l4, sizeof(l4), "injects: %lu", (unsigned long)txCount);
    oled("!! INJECTING !!", "malicious FW upd", l3, l4);
    delay(4000);
  }
}
