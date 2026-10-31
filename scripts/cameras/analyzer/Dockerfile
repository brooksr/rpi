FROM python:3.12-slim
COPY requirements.txt /app/
RUN pip install --no-cache-dir --root-user-action=ignore -r /app/requirements.txt
# YAMNet (as MediaPipe hosts it) and SSD-MobileNet v1 from the ONNX model zoo.
ADD https://storage.googleapis.com/mediapipe-models/audio_classifier/yamnet/float32/1/yamnet.tflite /models/yamnet.tflite
ADD https://github.com/onnx/models/raw/main/validated/vision/object_detection_segmentation/ssd-mobilenetv1/model/ssd_mobilenet_v1_12.onnx /models/ssd_mobilenet_v1_12.onnx
RUN chmod 644 /models/*
COPY analyzer.py /app/
USER 1000:1000
CMD ["python", "-u", "/app/analyzer.py"]
