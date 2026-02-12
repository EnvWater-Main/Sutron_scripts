
#include <TFT_eSPI.h>
#include <HX711.h>
#include <ModbusRTU.h>
#include <HardwareSerial.h>

// ---------- TFT / Sprites ----------
TFT_eSPI tft = TFT_eSPI();
TFT_eSprite headerSprite = TFT_eSprite(&tft);
TFT_eSprite valueSprite  = TFT_eSprite(&tft);

// ---------- Backlight ----------
#define TFT_BLK 32

// ---------- Display geometry ----------
const int16_t TFT_W = 240;
const int16_t TFT_H = 135;
const int16_t HEADER_H = 30;

// ---------- HX711 ----------
#define HX_DOUT 33
#define HX_SCK  25   // Safe pin for HX711 clock
#define CALIBRATION_FACTOR 11880.0f
HX711 scale;

// ---------- RS-485 / Modbus ----------
const int RS485_RX = 16; // from MAX485 RO
const int RS485_TX = 17; // to MAX485 DI
const int RS485_DE = 21; // to MAX485 DE and RE̅ (tie together)
HardwareSerial RS485(1);
ModbusRTU modbus;

// ---------- Update policy ----------
const float DISPLAY_EPS = 0.1f;     // Only update if change > 0.1 mL
const uint32_t MIN_UPDATE_MS = 500; // Minimum interval between screen pushes

// ---------- Smoothing filter ----------
const uint32_t SMOOTH_WINDOW_MS = 5000; // 5 seconds
const int SAMPLE_INTERVAL_MS = 1000;     // HX711 sample every 100 ms
const int MAX_SAMPLES = SMOOTH_WINDOW_MS / SAMPLE_INTERVAL_MS;
float samples[MAX_SAMPLES];
int sampleIndex = 0;
int sampleCount = 0;

float lastVolume = NAN;
uint32_t lastPushMs = 0;

void drawStaticHeaderOnce() {
  headerSprite.createSprite(TFT_W, HEADER_H);
  headerSprite.fillSprite(TFT_BLUE);
  headerSprite.setTextColor(TFT_WHITE, TFT_BLUE);
  headerSprite.setTextDatum(TL_DATUM);
  headerSprite.setTextFont(4);  // Use built-in Font 4 (requires LOAD_FONT2)
  headerSprite.drawString("Volume in mL", 10, 4);
  headerSprite.pushSprite(0, 0);
}

void initValueSprite() {
  valueSprite.createSprite(TFT_W, TFT_H - HEADER_H);
  valueSprite.setTextColor(TFT_WHITE, TFT_BLACK);
  valueSprite.setTextDatum(MC_DATUM);
  valueSprite.setTextPadding(0);
}

float computeAverage() {
  float sum = 0;
  for (int i = 0; i < sampleCount; i++) {
    sum += samples[i];
  }
  return (sampleCount > 0) ? sum / sampleCount : 0;
}


void showVolume(int roundedVolume, bool force = false) {
  uint32_t now = millis();
  if (!force && (now - lastPushMs) < MIN_UPDATE_MS) return;
  if (!force && !isnan(lastVolume) && fabs(roundedVolume - lastVolume) < DISPLAY_EPS) return;

  valueSprite.fillSprite(TFT_BLACK);
  valueSprite.setTextColor(TFT_WHITE, TFT_BLACK);
  valueSprite.setFreeFont(&FreeSansBold24pt7b); // Large, bold font
  valueSprite.setTextDatum(MC_DATUM);

  String displayText = String(roundedVolume) + " mL";
  valueSprite.drawString(displayText, TFT_W / 2, (TFT_H - HEADER_H) / 2);
  valueSprite.pushSprite(0, HEADER_H);

  lastVolume = roundedVolume;
  lastPushMs = now;
}





void setup() {
  Serial.begin(9600);
  delay(50);

  pinMode(TFT_BLK, OUTPUT);
  digitalWrite(TFT_BLK, HIGH);

  tft.init();
  tft.setRotation(1);
  tft.fillScreen(TFT_BLACK);

  drawStaticHeaderOnce();
  initValueSprite();

  RS485.begin(9600, SERIAL_8N1, RS485_RX, RS485_TX);
  pinMode(RS485_DE, OUTPUT);
  digitalWrite(RS485_DE, LOW);
  modbus.begin(&RS485, RS485_DE);
  modbus.server(1);
  modbus.addHreg(0, 0);

  scale.begin(HX_DOUT, HX_SCK);
  scale.set_scale(CALIBRATION_FACTOR);
  scale.tare();

  showVolume(0.0f, true);
  Serial.println("Ready: Hreg0 = volume * 10 (0.1 mL units)");
}

void loop() {
  // Read HX711
  float mass_kg = scale.get_units(1); // single reading for speed
  float volume_mL = mass_kg * 1000.0f;

  // Add to rolling buffer
  samples[sampleIndex] = volume_mL;
  sampleIndex = (sampleIndex + 1) % MAX_SAMPLES;
  if (sampleCount < MAX_SAMPLES) sampleCount++;

  // Compute smoothed average
  float avgVolume = computeAverage();
  // Round to nearest 10 mL
  int roundedVolume = round(avgVolume / 10.0f) * 10.0;


  // Update Modbus with smoothed value
  long scaled = lroundf(roundedVolume);
  if (scaled < 0) scaled = 0;
  if (scaled > 65535) scaled = 65535;
  modbus.Hreg(0, (uint16_t)scaled);
  modbus.task();

  // Update display with smoothed value
  showVolume(roundedVolume);

  Serial.printf("VOL: %d mL\n", roundedVolume);
  delay(SAMPLE_INTERVAL_MS);
}
