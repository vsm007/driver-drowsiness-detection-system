import cv2
import torch
import torch.nn as nn
from torchvision import models, transforms
from PIL import Image
import mediapipe as mp
import time
import serial
import os
import urllib.request

# =======================================================
# 1. ESP32 HARDWARE SETUP
# =======================================================
try:
    esp32 = serial.Serial('COM3', 9600, timeout=0.1)
    time.sleep(2)
    print("ESP32 Connected!")
except Exception:
    print("Running in Vision-Only Mode.")
    esp32 = None

# =======================================================
# 2. LOAD YOUR CUSTOM VGG16 BRAIN
# =======================================================
print("Loading Custom VGG16 Model...")
device = torch.device('cpu')

cnn_model = models.vgg16(weights=None)
num_features = cnn_model.classifier[6].in_features
cnn_model.classifier[6] = nn.Sequential(
    nn.Linear(num_features, 1),
    nn.Sigmoid()
)

# Load your custom trained weights
cnn_model.load_state_dict(torch.load('vgg16_eye_weights.pt', map_location=device))
cnn_model.eval()

vgg_transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
])

# =======================================================
# 3. MEDIAPIPE SETUP (For Flawless Eye Cropping)
# =======================================================
model_path = 'face_landmarker.task'

if not os.path.exists(model_path):
    print("Downloading MediaPipe Face Landmarker model...")
    url = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
    urllib.request.urlretrieve(url, model_path)
    print("Download complete!")

BaseOptions = mp.tasks.BaseOptions
FaceLandmarker = mp.tasks.vision.FaceLandmarker
FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions
VisionRunningMode = mp.tasks.vision.RunningMode

options = FaceLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=model_path),
    running_mode=VisionRunningMode.VIDEO,
    num_faces=1
)

LEFT_EYE_INDICES = [362, 385, 386, 263, 374, 380]
RIGHT_EYE_INDICES = [33, 159, 158, 133, 153, 145]


# THIS IS THE MISSING FUNCTION!
def get_eye_bbox(face_landmarks, eye_indices, img_w, img_h, padding=15):
    x_coords = [int(face_landmarks[idx].x * img_w) for idx in eye_indices]
    y_coords = [int(face_landmarks[idx].y * img_h) for idx in eye_indices]

    x_min, x_max = max(0, min(x_coords) - padding), min(img_w, max(x_coords) + padding)
    y_min, y_max = max(0, min(y_coords) - padding), min(img_h, max(y_coords) + padding)
    return x_min, y_min, x_max, y_max


# =======================================================
# 4. SYSTEM VARIABLES
# =======================================================
warning_start_time = 0
is_warning_active = False
DROWSINESS_THRESHOLD = 0.5

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
frame_count = 0
last_vgg_score = 1.0  # Default to Awake (1.0)
print("System Ready! Starting Hybrid Camera...")

# =======================================================
# 5. MAIN LOOP
# =======================================================
with FaceLandmarker.create_from_options(options) as landmarker:
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break

        frame_count += 1
        frame = cv2.flip(frame, 1)
        img_h, img_w, _ = frame.shape

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
        timestamp_ms = int(time.time() * 1000)

        # 1. Flawless Face Detection (Runs every frame)
        result = landmarker.detect_for_video(mp_image, timestamp_ms)
        driver_is_drowsy = False

        if result.face_landmarks:
            for face_landmarks in result.face_landmarks:

                # Extract Bounding Boxes for both eyes
                lx_min, ly_min, lx_max, ly_max = get_eye_bbox(face_landmarks, LEFT_EYE_INDICES, img_w, img_h)
                rx_min, ry_min, rx_max, ry_max = get_eye_bbox(face_landmarks, RIGHT_EYE_INDICES, img_w, img_h)

                # Draw boxes around the eyes
                cv2.rectangle(frame, (lx_min, ly_min), (lx_max, ly_max), (255, 0, 0), 2)
                cv2.rectangle(frame, (rx_min, ry_min), (rx_max, ry_max), (255, 0, 0), 2)

                # 2. VGG16 INFERENCE THROTTLING (Only run every 5 frames)
                if frame_count % 5 == 0:
                    try:
                        # Crop the right eye
                        eye_crop_cv = frame[ry_min:ry_max, rx_min:rx_max]
                        eye_img_rgb = cv2.cvtColor(eye_crop_cv, cv2.COLOR_BGR2RGB)
                        pil_image = Image.fromarray(eye_img_rgb)

                        # Format for VGG16
                        eye_tensor = vgg_transform(pil_image).unsqueeze(0)

                        # Run the model
                        with torch.no_grad():
                            last_vgg_score = cnn_model(eye_tensor).item()
                    except Exception:
                        pass  # Ignore if crop fails momentarily

                cv2.putText(frame, f"VGG: {last_vgg_score:.2f}", (rx_min, ry_min - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            (0, 255, 255), 2)

                if last_vgg_score < DROWSINESS_THRESHOLD:
                    driver_is_drowsy = True

        # ---------------------------------------------------
        # THE 2-SECOND TIMER & ESP32 CONTROL
        # ---------------------------------------------------
        if driver_is_drowsy:
            if not is_warning_active:
                warning_start_time = time.time()
                is_warning_active = True

            time_elapsed = time.time() - warning_start_time

            if time_elapsed < 2.0:
                cv2.putText(frame, f"WARNING! ({2.0 - time_elapsed:.1f}s)", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                            (0, 165, 255), 3)
            else:
                cv2.putText(frame, "CRITICAL: SLOWING DOWN", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 3)
                if esp32: esp32.write(b"85\n")
        else:
            is_warning_active = False
            cv2.putText(frame, "NORMAL DRIVING", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            if esp32: esp32.write(b"0\n")

        cv2.imshow("Hybrid VGG16 Monitor", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

cap.release()
cv2.destroyAllWindows()
if esp32: esp32.close()
