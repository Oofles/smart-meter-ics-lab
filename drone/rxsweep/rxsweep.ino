/*
 * drone/rxsweep — reverse-link PHY finder for the smart-meter exercise.
 *
 * Heltec WiFi LoRa 32 V4 (ESP32-S3 + SX1262). The FORWARD link (Heltec raw TX ->
 * Pi EBYTE HAT RX) got 0 bytes across a full SF/BW grid at sync 0x12, so SF/BW is
 * ruled out. This sketch reverses the link: the Pi HAT transmits a known frame
 * (scripts side: tx_beacon.py, benign SMFW) and the Heltec RX-SWEEPS SF/BW x sync
 * until it demodulates it. Because the HAT emits its TRUE PHY, a lock tells us the
 * HAT's actual SF/BW/sync directly — no more guessing. If NOTHING locks across the
 * whole grid, the EBYTE module isn't emitting standard LoRa and raw interop is a
 * dead end (pivot the drone to a 2nd EBYTE/Waveshare HAT).
 *
 * In explicit-header mode the receiver learns CR/length/CRC from the header, so the
 * only PHY params that must match to lock are freq + SF + BW + sync (+ preamble).
 *
 * RadioLib 7.x + U8g2 + esp32 core 3.x. Build with CDCOnBoot=cdc to read the log on USB.
 */
#include <RadioLib.h>
#include <U8g2lib.h>

// ---- OLED (Heltec V4) ----
#define OLED_SDA 17
#define OLED_SCL 18
#define OLED_RST 21
#define VEXT     36
U8G2_SSD1306_128X64_NONAME_F_SW_I2C u8g2(U8G2_R0, OLED_SCL, OLED_SDA, OLED_RST);

// ---- radio (Heltec V4: NSS=8 DIO1=14 RST=12 BUSY=13; SPI SCK=9 MISO=11 MOSI=10) ----
SX1262 radio = new Module(8, 14, 12, 13);

// ---- sweep grid: SF7..12 x BW{125,250,500} x sync{0x12,0x34}; freq 868.125 ----
struct Combo { float bw; uint8_t sf; uint8_t sync; };
Combo COMBOS[108];
int NCOMBO = 0;
char nameBuf[24];

void buildGrid() {
  const float BWS[3]   = {125.0, 250.0, 500.0};
  const uint8_t SFS[6] = {7, 8, 9, 10, 11, 12};
  const uint8_t SYN[2] = {0x12, 0x34};
  NCOMBO = 0;
  for (int s = 0; s < 2; s++)
    for (int b = 0; b < 3; b++)
      for (int f = 0; f < 6; f++)
        COMBOS[NCOMBO++] = {BWS[b], SFS[f], SYN[s]};
}
const char* comboName(int i) {
  snprintf(nameBuf, sizeof(nameBuf), "SF%u BW%d sy%02X",
           COMBOS[i].sf, (int)COMBOS[i].bw, COMBOS[i].sync);
  return nameBuf;
}

const uint32_t DWELL_MS = 1200;   // listen window per combo (HAT TXs ~every 400ms)

volatile bool rxFlag = false;
void IRAM_ATTR onRx() { rxFlag = true; }

uint32_t hits = 0;

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
  pinMode(VEXT, OUTPUT); digitalWrite(VEXT, LOW); delay(60);
  u8g2.begin();
  buildGrid();
  oled("SMART-METER LAB", "RX SWEEP (find PHY)", "init radio...", "");
  SPI.begin(9, 11, 10, 8);
  int st = radio.begin(868.125, 125.0, 9, 5, 0x12, 22, 8, 1.8, false);
  Serial.printf("radio.begin -> %d ; sweeping %d combos, dwell %lums\n",
                st, NCOMBO, (unsigned long)DWELL_MS);
  radio.setDio2AsRfSwitch(true);
  radio.setDio1Action(onRx);
  char b[24]; snprintf(b, sizeof(b), "begin=%d n=%d", st, NCOMBO);
  oled("RX SWEEP", "listening for HAT", b, "868.125 MHz");
  delay(1000);
}

void applyCombo(int i) {
  radio.setBandwidth(COMBOS[i].bw);
  radio.setSpreadingFactor(COMBOS[i].sf);
  radio.setSyncWord(COMBOS[i].sync);
}

void loop() {
  for (int i = 0; i < NCOMBO; i++) {
    radio.standby();
    applyCombo(i);
    rxFlag = false;
    radio.startReceive();
    Serial.printf("listen combo%d [%s]\n", i, comboName(i));
    char l2[22]; snprintf(l2, sizeof(l2), "c%d %s", i, comboName(i));
    char l4[22]; snprintf(l4, sizeof(l4), "hits=%lu", (unsigned long)hits);
    oled("RX SWEEP: listening", l2, "", l4);

    uint32_t start = millis();
    while (millis() - start < DWELL_MS) {
      if (rxFlag) {
        rxFlag = false;
        uint8_t buf[64];
        int n = radio.getPacketLength();
        int st = radio.readData(buf, n > 64 ? 64 : n);
        if (st == RADIOLIB_ERR_NONE || st == RADIOLIB_ERR_CRC_MISMATCH) {
          hits++;
          bool smfw = (n >= 4 && buf[0]=='S' && buf[1]=='M' && buf[2]=='F' && buf[3]=='W');
          char hex[3*64+1]; int p = 0;
          for (int k = 0; k < n && k < 64; k++) p += snprintf(hex+p, sizeof(hex)-p, "%02x ", buf[k]);
          Serial.printf(">>> LOCK combo%d [%s] st=%d len=%d rssi=%.1f snr=%.1f magic=%s data=%s\n",
                        i, comboName(i), st, n, radio.getRSSI(), radio.getSNR(),
                        smfw ? "SMFW" : "----", hex);
          char l1[22]; snprintf(l1, sizeof(l1), "LOCK %s", smfw ? "SMFW!" : "pkt");
          char l3[22]; snprintf(l3, sizeof(l3), "rssi %.0f len %d", radio.getRSSI(), n);
          oled(l1, comboName(i), l3, "!! PHY FOUND !!");
          delay(1500);
        }
        radio.startReceive();
      }
      delay(2);
    }
  }
}
