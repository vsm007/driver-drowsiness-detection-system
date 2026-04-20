// =======================================================
// 1. PIN DEFINITIONS
// =======================================================
// Motor A (Left)
const int enA = 25; 
const int in1 = 26; 
const int in2 = 27; 

// Motor B (Right)
const int enB = 14; 
const int in3 = 12; 
const int in4 = 13; 

// Sensors & Alerts
const int frontIrPin = 34;    // Front IR Sensor (Input Only Pin)
const int backIrPin = 35;     // Back IR Sensor (Input Only Pin)
const int alertPin = 33;      // Hazard LEDs & Buzzer combined here

// =======================================================
// 2. SYSTEM VARIABLES
// =======================================================
int currentSpeed = 255;  
int targetSpeed = 255;
int drowsinessScore = 0;
bool emergencyStopActive = false;

// Non-blocking timer variables for Hazard/Buzzer blinking
unsigned long previousMillis = 0;
const long blinkInterval = 300; // Blink every 300ms
bool alertState = false;

void setup() {
  Serial.begin(9600);
  
  // Configure Motors
  pinMode(enA, OUTPUT); pinMode(in1, OUTPUT); pinMode(in2, OUTPUT);
  pinMode(enB, OUTPUT); pinMode(in3, OUTPUT); pinMode(in4, OUTPUT);
  
  // Configure Sensors & Alerts
  pinMode(frontIrPin, INPUT);
  pinMode(backIrPin, INPUT);
  pinMode(alertPin, OUTPUT);
  
  // Start the rover moving forward
  moveForward(currentSpeed, currentSpeed);
}

void loop() {
  // =======================================================
  // 3. HAZARD LIGHTS & BUZZER LOGIC
  // =======================================================
  // Flash hazards & beep if drowsy or if the car performed an emergency stop
  if (drowsinessScore > 0 || emergencyStopActive) {
    unsigned long currentMillis = millis();
    if (currentMillis - previousMillis >= blinkInterval) {
      previousMillis = currentMillis;
      alertState = !alertState; 
      digitalWrite(alertPin, alertState ? HIGH : LOW);
    }
  } else {
    // Awake and safe: Turn off lights and buzzer
    digitalWrite(alertPin, LOW);
    alertState = false;
  }

  // If the emergency stop was triggered, halt the motor logic permanently
  if (emergencyStopActive) return;

  // =======================================================
  // 4. READ DROWSINESS DATA FROM PYTHON
  // =======================================================
  if (Serial.available() > 0) {
    String incomingData = Serial.readStringUntil('\n');
    drowsinessScore = incomingData.toInt();
    
    // Map score to target speed (255 down to 60 to prevent motor stall)
    if (drowsinessScore == 0) {
      targetSpeed = 255; // Awake
    } else {
      targetSpeed = map(drowsinessScore, 10, 100, 200, 100); 
    }
  }

  // =======================================================
  // 5. ADAPTIVE DECELERATION
  // =======================================================
  int frontBlocked = digitalRead(frontIrPin);
  int backBlocked = digitalRead(backIrPin);
  
  // If BOTH front and back are blocked, decelerate 5x faster!
  int decelStep = (frontBlocked == LOW && backBlocked == LOW) ? 5 : 1;

  if (currentSpeed > targetSpeed) {
    currentSpeed -= decelStep; 
    if (currentSpeed < targetSpeed) currentSpeed = targetSpeed; // Prevent undershoot
    moveForward(currentSpeed, currentSpeed);
    delay(2000); // Short delay for smooth braking without freezing lights
  } else if (currentSpeed < targetSpeed) {
    currentSpeed += 1;
    moveForward(currentSpeed, currentSpeed);
    delay(2000);
  }

  // =======================================================
  // 6. OBSTACLE EVASION & EMERGENCY BRAKING
  // =======================================================
  // Only trigger evasion if there is an obstacle AND the driver is drowsy
  if (frontBlocked == LOW && drowsinessScore > 0) {
    
    if (backBlocked == LOW) {
      // BOXED IN! Do not swerve. Slam the brakes immediately.
      digitalWrite(in1, LOW); digitalWrite(in2, LOW);
      digitalWrite(in3, LOW); digitalWrite(in4, LOW);
      analogWrite(enA, 0); analogWrite(enB, 0);
      emergencyStopActive = true; 
      
    } else {
      // ONLY front is blocked. Safe to swerve right!
      digitalWrite(in1, HIGH); digitalWrite(in2, LOW); 
      digitalWrite(in3, LOW);  digitalWrite(in4, HIGH);
      analogWrite(enA, 180); 
      analogWrite(enB, 180);
      
      delay(600); // Wait 0.6 seconds to clear the obstacle
      
      // Emergency Dead Stop after swerving
      digitalWrite(in1, LOW); digitalWrite(in2, LOW);
      digitalWrite(in3, LOW); digitalWrite(in4, LOW);
      analogWrite(enA, 0); analogWrite(enB, 0);
      
      emergencyStopActive = true; 
    }
  }
}

// =======================================================
// HELPER FUNCTION: Drive Motors
// =======================================================
void moveForward(int speedLeft, int speedRight) {
  digitalWrite(in1, HIGH); digitalWrite(in2, LOW);
  digitalWrite(in3, HIGH); digitalWrite(in4, LOW);
  analogWrite(enA, speedLeft);
  analogWrite(enB, speedRight);
}