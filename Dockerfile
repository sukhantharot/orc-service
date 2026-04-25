FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender1 \
        ccache \
        tesseract-ocr \
        tesseract-ocr-eng \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# fastmrz needs the custom MRZ-trained Tesseract model from tesseractMRZ.
# Resolve tessdata dir from the installed eng.traineddata so this survives
# Debian/tesseract version bumps.
RUN TESSDATA_DIR="$(dirname "$(find /usr/share -name eng.traineddata | head -n1)")" \
    && curl -sSL -o "${TESSDATA_DIR}/mrz.traineddata" \
        https://github.com/DoubangoTelecom/tesseractMRZ/raw/master/tessdata_best/mrz.traineddata \
    && test -s "${TESSDATA_DIR}/mrz.traineddata"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download Thai+English PaddleOCR models so first /scan doesn't pay download latency
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='th', show_log=False)"

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
