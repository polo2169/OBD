#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_ADXL345_U.h>
#include <esp_timer.h>

// Enregistreur passif GPS + accelerometre : aucun bus CAN et aucune commande
// vehicule ne sont utilises par ce firmware.
namespace {

constexpr uint32_t USB_BAUD = 921600;
constexpr int GPS_RX_PIN = 16;  // ESP32 RX2 <- GPS TX
constexpr int GPS_TX_PIN = 17;  // ESP32 TX2 -> GPS RX
constexpr int SDA_PIN = 21;
constexpr int SCL_PIN = 22;
constexpr uint32_t GPS_SCAN_TIME_MS = 3000;
constexpr uint32_t IMU_PERIOD_US = 5000;  // 200 Hz

constexpr uint32_t GPS_BAUD_RATES[] = {9600, 115200, 38400, 57600, 230400};

HardwareSerial gpsSerial(2);
Adafruit_ADXL345_Unified adxl(12345);

size_t gpsBaudIndex = 0;
uint32_t gpsBaud = GPS_BAUD_RATES[0];
uint32_t gpsScanStartedMs = 0;
uint32_t validNmeaCount = 0;
uint32_t invalidNmeaCount = 0;
uint32_t lastValidNmeaMs = 0;

char nmeaBuffer[192] = {};
size_t nmeaLength = 0;
bool collectingNmea = false;

bool adxlPresent = false;
uint8_t adxlAddress = 0;
uint32_t lastImuUs = 0;
uint32_t lastStatusMs = 0;

int hexValue(char value) {
  if (value >= '0' && value <= '9') return value - '0';
  if (value >= 'A' && value <= 'F') return value - 'A' + 10;
  if (value >= 'a' && value <= 'f') return value - 'a' + 10;
  return -1;
}

bool hasValidNmeaChecksum(const char *sentence) {
  if (sentence[0] != '$') return false;

  const char *star = strchr(sentence, '*');
  if (star == nullptr || star[1] == '\0' || star[2] == '\0') return false;

  uint8_t checksum = 0;
  for (const char *cursor = sentence + 1; cursor < star; ++cursor) {
    checksum ^= static_cast<uint8_t>(*cursor);
  }

  const int high = hexValue(star[1]);
  const int low = hexValue(star[2]);
  return high >= 0 && low >= 0 && checksum == static_cast<uint8_t>((high << 4) | low);
}

void startGps(uint32_t baud) {
  gpsSerial.end();
  gpsSerial.begin(baud, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);
  gpsBaud = baud;
  gpsScanStartedMs = millis();
  nmeaLength = 0;
  collectingNmea = false;
  Serial.printf("GPS_BAUD,%lu\n", static_cast<unsigned long>(baud));
}

void emitNmea() {
  nmeaBuffer[nmeaLength] = '\0';
  if (!hasValidNmeaChecksum(nmeaBuffer)) {
    ++invalidNmeaCount;
    return;
  }

  ++validNmeaCount;
  lastValidNmeaMs = millis();
  Serial.printf("GPS,%llu,%lu,%s\n", static_cast<unsigned long long>(esp_timer_get_time()),
                static_cast<unsigned long>(gpsBaud), nmeaBuffer);
}

void readGps() {
  while (gpsSerial.available() > 0) {
    const char value = static_cast<char>(gpsSerial.read());

    if (value == '$') {
      collectingNmea = true;
      nmeaLength = 0;
      nmeaBuffer[nmeaLength++] = value;
    } else if (!collectingNmea) {
      continue;
    } else if (value == '\r' || value == '\n') {
      if (nmeaLength > 6) emitNmea();
      collectingNmea = false;
      nmeaLength = 0;
    } else if (value >= 32 && value <= 126 && nmeaLength < sizeof(nmeaBuffer) - 1) {
      nmeaBuffer[nmeaLength++] = value;
    } else {
      collectingNmea = false;
      nmeaLength = 0;
    }
  }

  if (validNmeaCount == 0 && millis() - gpsScanStartedMs >= GPS_SCAN_TIME_MS) {
    gpsBaudIndex = (gpsBaudIndex + 1) % (sizeof(GPS_BAUD_RATES) / sizeof(GPS_BAUD_RATES[0]));
    startGps(GPS_BAUD_RATES[gpsBaudIndex]);
  }
}

void startAdxl() {
  for (const uint8_t address : {uint8_t(0x53), uint8_t(0x1D)}) {
    Wire.beginTransmission(address);
    if (Wire.endTransmission() == 0 && adxl.begin(address)) {
      adxlAddress = address;
      adxlPresent = true;
      adxl.setRange(ADXL345_RANGE_2_G);
      adxl.setDataRate(ADXL345_DATARATE_200_HZ);
      Serial.printf("ADXL345,READY,0x%02X\n", adxlAddress);
      return;
    }
  }

  Serial.println("ADXL345,ABSENT");
}

void emitImuIfDue() {
  if (!adxlPresent) return;

  const uint32_t nowUs = micros();
  if (nowUs - lastImuUs < IMU_PERIOD_US) return;
  lastImuUs = nowUs;

  const int16_t x = adxl.getX();
  const int16_t y = adxl.getY();
  const int16_t z = adxl.getZ();
  Serial.printf("IMU,%llu,%d,%d,%d\n", static_cast<unsigned long long>(esp_timer_get_time()), x, y, z);
}

void emitStatusIfDue() {
  if (millis() - lastStatusMs < 1000) return;
  lastStatusMs = millis();

  const uint32_t gpsAgeMs = lastValidNmeaMs == 0 ? UINT32_MAX : millis() - lastValidNmeaMs;
  Serial.printf("STAT,%lu,%lu,%lu,%lu,%lu,%u,0\n", static_cast<unsigned long>(millis()),
                static_cast<unsigned long>(gpsBaud), static_cast<unsigned long>(validNmeaCount),
                static_cast<unsigned long>(invalidNmeaCount), static_cast<unsigned long>(gpsAgeMs),
                adxlPresent ? 1 : 0);
}

}  // namespace

void setup() {
  Serial.begin(USB_BAUD);
  delay(500);
  Serial.println("HELLO,gps-adxl345-logger,2.0,PASSIVE_NO_CAN");

  pinMode(SDA_PIN, INPUT_PULLUP);
  pinMode(SCL_PIN, INPUT_PULLUP);
  Wire.begin(SDA_PIN, SCL_PIN, 100000);

  startAdxl();
  startGps(GPS_BAUD_RATES[gpsBaudIndex]);
}

void loop() {
  readGps();
  emitImuIfDue();
  emitStatusIfDue();
  delay(1);
}
