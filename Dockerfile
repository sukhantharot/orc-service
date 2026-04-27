FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgomp1 \
        libgl1 \
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
# paddlex[ocr] brings opencv-contrib-python==4.10.0.84 and checks for that exact package name at runtime
# (importlib.metadata), so we keep it instead of substituting the headless variant.
RUN pip install --no-cache-dir -r requirements.txt
# PaddleOCR: avoid MKL-DNN in thin containers (can segfault); thread caps reduce allocator issues.
# Models download on first Thai ID /scan (no RUN warmup — init crashes in some build daemons).
ENV OMP_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV FLAGS_use_mkldnn=0

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
