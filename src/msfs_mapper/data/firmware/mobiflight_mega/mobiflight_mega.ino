#include <Arduino.h>
#include "mobiflight_config.h"
const unsigned long DEBOUNCE_MS = 25;

struct ButtonState {
  bool stable;
  bool reading;
  unsigned long changedAt;
};

ButtonState buttons[BUTTON_COUNT];
volatile int8_t encoderSteps[ENCODER_COUNT] = {};
volatile int8_t encoderDetents[ENCODER_COUNT] = {};
volatile uint8_t encoderPrevious[ENCODER_COUNT] = {};
const int8_t QUADRATURE[16] = {0, -1, 1, 0, 1, 0, 0, -1, -1, 0, 0, 1, 0, 1, -1, 0};

void updateEncoder(uint8_t index) {
  uint8_t state = (digitalRead(encoderPins[index][0]) << 1) |
                  digitalRead(encoderPins[index][1]);
  uint8_t transition = (encoderPrevious[index] << 2) | state;
  encoderPrevious[index] = state;
  int8_t step = QUADRATURE[transition];
  if (step != 0) {
    int8_t next = encoderSteps[index] + step;
    if (next >= 4) {
      encoderSteps[index] = 0;
      if (encoderDetents[index] < 8) ++encoderDetents[index];
    } else if (next <= -4) {
      encoderSteps[index] = 0;
      if (encoderDetents[index] > -8) --encoderDetents[index];
    } else {
      encoderSteps[index] = next;
    }
  }
}

void encoder0Changed() { updateEncoder(0); }
void encoder1Changed() { updateEncoder(1); }
void encoder2Changed() { updateEncoder(2); }

void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < BUTTON_COUNT; ++i) {
    pinMode(buttonPins[i], INPUT_PULLUP);
    buttons[i] = {digitalRead(buttonPins[i]) == LOW,
                  digitalRead(buttonPins[i]) == LOW, millis()};
  }
  for (uint8_t i = 0; i < ENCODER_COUNT; ++i) {
    pinMode(encoderPins[i][0], INPUT_PULLUP);
    pinMode(encoderPins[i][1], INPUT_PULLUP);
    encoderPrevious[i] = (digitalRead(encoderPins[i][0]) << 1) |
                         digitalRead(encoderPins[i][1]);
  }
  if (ENCODER_COUNT > 0) {
    attachInterrupt(digitalPinToInterrupt(encoderPins[0][0]), encoder0Changed, CHANGE);
    attachInterrupt(digitalPinToInterrupt(encoderPins[0][1]), encoder0Changed, CHANGE);
  }
  if (ENCODER_COUNT > 1) {
    attachInterrupt(digitalPinToInterrupt(encoderPins[1][0]), encoder1Changed, CHANGE);
    attachInterrupt(digitalPinToInterrupt(encoderPins[1][1]), encoder1Changed, CHANGE);
  }
  if (ENCODER_COUNT > 2) {
    attachInterrupt(digitalPinToInterrupt(encoderPins[2][0]), encoder2Changed, CHANGE);
    attachInterrupt(digitalPinToInterrupt(encoderPins[2][1]), encoder2Changed, CHANGE);
  }
  Serial.print("READY,1,");
  Serial.print(BUTTON_COUNT);
  Serial.print(",");
  Serial.println(ENCODER_COUNT);
}

void loop() {
  unsigned long now = millis();
  for (uint8_t i = 0; i < BUTTON_COUNT; ++i) {
    bool reading = digitalRead(buttonPins[i]) == LOW;
    if (reading != buttons[i].reading) {
      buttons[i].reading = reading;
      buttons[i].changedAt = now;
    }
    if (reading != buttons[i].stable && now - buttons[i].changedAt >= DEBOUNCE_MS) {
      buttons[i].stable = reading;
      Serial.print("B,");
      Serial.print(i);
      Serial.print(",");
      Serial.println(reading ? 1 : 0);
    }
  }
  for (uint8_t i = 0; i < ENCODER_COUNT; ++i) {
    noInterrupts();
    int8_t pending = encoderDetents[i];
    encoderDetents[i] = 0;
    interrupts();
    while (pending > 0) {
      Serial.print("E,");
      Serial.print(i);
      Serial.println(",1");
      --pending;
    }
    while (pending < 0) {
      Serial.print("E,");
      Serial.print(i);
      Serial.println(",-1");
      ++pending;
    }
  }
}
