# orc-service — Implementation Plan

แผนสร้างจริงตาม `PRD.md` แบ่งเป็น 6 phase ตามความเสี่ยงและ dependency

---

## Strategy

**Ship passport ก่อน Thai ID** — Passport (MRZ) มี standard ICAO 9303 ชัดเจน, lib (PassportEye) เป็น production-grade, รองรับทุกประเทศได้ทันที → ทำ end-to-end ได้เร็ว เป็น "proof of life" ก่อนไปลุยส่วน Thai ID ที่ยากกว่า (PaddleOCR + template + accuracy unknown)

**Validate ของจริงทุก phase** — ทุก phase ต้องมี sample images จริงทดสอบก่อนปิด phase ห้าม mock อย่างเดียว

**Resist scope creep** — ทุก feature ที่ไม่อยู่ใน PRD section 2 (Goals) → ปฏิเสธ จดใน "Future Work" หรือ phase ถัดไป

---

## Prerequisites (ก่อนเริ่ม Phase 1)

- [ ] Python 3.11+
- [ ] Docker + docker-compose
- [ ] Sample images:
  - 5-10 passport (หลายประเทศ — TH, US, JP, CN, EU อย่างน้อย)
  - 5-10 Thai ID (รุ่นปัจจุบัน ปี 2563+)
  - แต่ละชุดมี: ภาพคมชัด, ภาพเฉียง, ภาพแสงน้อย, ภาพหมุน 90°
- [ ] Test API key string พร้อมใช้

---

## Phase 1 — Skeleton + Auth + Health (~ครึ่งวัน)

**Goal:** Service ตอบ HTTP ได้, auth ใช้งานได้, deploy เป็น container ได้

### Deliverables
- `Dockerfile` (Python 3.11 slim, PaddleOCR + OpenCV + PassportEye deps)
- `docker-compose.yml` (single service, env file, exposed port 8000)
- `requirements.txt` (fastapi, uvicorn, pydantic, paddleocr, passporteye/fastmrz, opencv-python-headless, python-multipart, python-dotenv)
- `.env.example` ตาม PRD section 8.4
- `app/main.py` — FastAPI app + middleware
- `app/config.py` — env var loader (ทุก var อ่านที่นี่ที่เดียว)
- `GET /health` endpoint
- API key middleware — `X-API-Key` ผิด → 401 ก่อน route handler

### Validation gate
- [ ] `docker compose up` รันได้ ไม่ crash
- [ ] `curl http://localhost:8000/health` → 200 `{"status":"ok"}`
- [ ] `curl http://localhost:8000/scan` ไม่มี API key → 401
- [ ] `curl -H "X-API-Key: wrong" ...` → 401
- [ ] OpenAPI docs ที่ `/docs` แสดงได้

### Risk
- PaddleOCR base image ใหญ่ (~1GB+ หลังลง deps) — ยอมรับ, optimize ทีหลัง

---

## Phase 2 — Schemas + /scan stub (~2-3 ชม.)

**Goal:** Contract ชัดเจน, `/scan` รับ multipart ได้, validate input ครบ, ตอบ stub response

### Deliverables
- `app/schemas.py` — Pydantic models:
  - `DocumentType` enum (`thai_id`, `passport`)
  - `ScanResponse` (ตาม PRD 4.2)
  - `ConfidenceScores`
  - `ErrorResponse` + `ErrorCode` enum
- `POST /scan` route — รับ multipart (`type` form field + `image` UploadFile)
- Input validation:
  - `type` ต้องเป็น enum ที่กำหนด → 400 ถ้าผิด
  - `image` content-type ต้องเป็น `image/jpeg` หรือ `image/png` → 400 `unsupported_format`
  - File size ≤ `MAX_IMAGE_SIZE_MB` → 400 `file_too_large`
  - File decode ได้ด้วย OpenCV → 400 `image_invalid`
- Stub response: คืน 200 พร้อม fields เป็น null + confidence 0 ทั้งหมด

### Validation gate
- [ ] `curl -F type=passport -F image=@test.jpg ...` → 200 พร้อม schema ถูกต้อง
- [ ] ส่ง type ผิด → 400
- [ ] ส่ง file > 10MB → 400
- [ ] ส่ง .pdf / .heic → 400 `unsupported_format`
- [ ] OpenAPI schema ใน `/docs` ตรงกับ PRD 4.2

---

## Phase 3 — Passport scanner (MRZ end-to-end) (~1 วัน)

**Goal:** ส่ง passport image → ได้ JSON ครบทุก field

### Deliverables
- `app/scanners/passport.py`:
  - รับ decoded image (numpy array)
  - หา + parse MRZ ด้วย PassportEye (หรือ fastmrz)
  - Map MRZ fields → unified schema (PRD 5.1)
  - Validate check digits — set `document_valid`
  - Convert YYMMDD → YYYY-MM-DD (handle century: ถ้า YY > current_year_2digit → 19xx, else 20xx)
  - Map sex `<` → null
- `app/validators.py`:
  - `mrz_check_digit(s)` — ICAO 9303 weighted sum
- `/scan` ถ้า `type=passport` → call passport scanner → คืน real response
- ไม่เจอ MRZ → 422 `no_document_detected`

### Validation gate
- [ ] Sample passport 5-10 ใบ จากหลายประเทศ → fields ครบถ้วน, accuracy > 95% บนภาพคมชัด
- [ ] `document_valid: true` บน passport จริง, `false` บนภาพ tamper test
- [ ] Date_of_birth ถูกต้องทั้ง century (ทดสอบเกิดปี 1985 และ 2005)
- [ ] Sex `<` (passport บางประเทศ) → null ไม่ throw
- [ ] ภาพไม่มี MRZ (เช่น ใบ ID อื่น) → 422

### Risk
- บาง passport design วาง MRZ ใกล้ขอบ — ต้อง crop bottom 30% ก่อนส่ง PassportEye
- Mitigation: ถ้า fail ลอง full image เป็น fallback

---

## Phase 4 — Image preprocessing pipeline (~1 วัน)

**Goal:** ภาพเฉียง/หมุน/คุณภาพไม่ดี → จัดให้พร้อม OCR

### Deliverables
- `app/preprocessing.py`:
  - `decode_and_normalize(bytes)` — decode, resize ถ้ากว้าง > `MAX_IMAGE_DIMENSION`
  - `detect_document_boundary(img)` — Canny + contour + 4-corner approx → return polygon หรือ None
  - `perspective_correct(img, polygon)` — warp ให้เป็นสี่เหลี่ยมตรง
  - `enhance_contrast(img)` — CLAHE
  - `try_orientations(img, ocr_fn)` — รัน OCR ทั้ง 0/90/180/270, return ผลที่ confidence สูงสุด
- ปรับ `passport.py` ให้ใช้ preprocess + auto-rotation
- หา document ไม่เจอ → ใช้ original image (don't fail hard, OCR อาจยังอ่านได้)

### Validation gate
- [ ] ภาพ passport หมุน 90° → output เหมือนภาพปกติ
- [ ] ภาพถ่ายเฉียง 30° → perspective correct แล้ว readable
- [ ] ภาพ low-light + CLAHE → MRZ readable
- [ ] Latency เพิ่ม < 1.5s จาก auto-rotation (acceptable trade-off)

### Risk
- Auto-rotation 4x latency — อาจเกิน 3s SLA บน CPU ช้า
- Mitigation: short-circuit ถ้า orientation 0° ได้ confidence > 0.9 ก็ไม่ต้องลองที่เหลือ

---

## Phase 5 — Thai ID scanner (~2-3 วัน — เสี่ยงสุด)

**Goal:** ส่ง Thai ID → ได้ first_name (EN), last_name (EN), id_number (13 digit), DOB, sex, country

### Deliverables
- `app/scanners/thai_id.py`:
  - PaddleOCR instance (Thai + English models, lazy load ตอน start app)
  - รับ preprocessed image, run PaddleOCR → list of (bbox, text, confidence)
  - **Field extraction**: 2 strategies, run together, เลือกผลที่ confidence ดีกว่า:
    - **(a) Anchor-based:** หา label keywords ("Identification Number", "Name", "Last name", "Date of Birth") → ดึง text บรรทัดถัดไปหรือขวามือ
    - **(b) Pattern-based:** regex หาเลข 13 หลัก, regex หา title prefix (Mr./Mrs./Miss./นาย/นาง/นางสาว) แล้วดึง 2 word ถัดไป
- Sex derivation:
  - หา Thai title prefix บน OCR results → map (PRD 5.2)
  - ถ้าไม่เจอ → null
- Date conversion: ถ้า year > 2400 → BE (ลบ 543), ถ้า ≤ 2200 → CE
- Mod-11 checksum: `validators.thai_id_check_digit(id_str)` → set `document_valid`
- Hard-code `country = "THA"`
- Per-field confidence: ใช้ confidence ของ OCR result ที่ฟิลด์นั้นมาจาก

### Validation gate
- [ ] Sample 10 ใบ → first_name + last_name accuracy ≥ 90% บนภาพคมชัด
- [ ] ID number accuracy = 100% (มี checksum verify ได้)
- [ ] DOB ถูก: ทดสอบทั้งบัตรที่พิมพ์ พ.ศ. และ ค.ศ.
- [ ] Sex derivation ถูกบนทุกคำนำหน้า (นาย/นาง/นางสาว/เด็กชาย/เด็กหญิง), null บน OCR fail
- [ ] `document_valid` ถูก: ใช้ ID จริง (valid) + ID สมมติ checksum ผิด (invalid)
- [ ] Confidence per field สมเหตุสมผล (ไม่ใช่ 1.0 ทุกอัน)

### Risk — สูงที่สุดในโปรเจกต์
- PaddleOCR Thai+English อาจ confuse ตัวเลขไทย/อารบิก, อาจอ่าน "1" เป็น "I" ใน id number
- Mitigation: ใน id_number field force regex `\d{13}`, reject ตัวอักษร
- ภาพ phone-shot คุณภาพไม่ดี accuracy อาจตกลงเหลือ 70% — **acceptable per PRD** (frontend ให้คนแก้ได้)
- ถ้า accuracy ต่ำเกินยอมรับ → revisit: เพิ่ม fine-tuned model? เพิ่ม preprocessing?

---

## Phase 6 — Type mismatch + logging + polish (~ครึ่งวัน)

**Goal:** Edge case ครบ, observability พร้อม, deploy ready

### Deliverables
- **Type mismatch detection:**
  - `passport.py`: ถ้า `type=thai_id` แต่หา MRZ pattern เจอ → 422 `type_mismatch` + `detected_type: passport`
  - `thai_id.py`: ถ้า `type=passport` แต่หา Thai script + 13-digit layout เจอ → 422 + `detected_type: thai_id`
- **Logging (`app/logging_config.py`):**
  - JSON formatter
  - PII filter — strip ทุก field ที่อาจเป็น PII (whitelist log fields เท่านั้น)
  - Request ID middleware (gen UUID per request, ใส่ใน log + response header)
- **README.md:**
  - Quick start (`docker compose up`)
  - API reference (link ไป PRD)
  - **NestJS calling example** (TypeScript snippet — multipart forward ด้วย `axios` + `form-data`)
  - PDPA notes
- **`.env.example`** ครบทุก var ที่ใช้

### Validation gate
- [ ] ส่ง Thai ID image พร้อม `type=passport` → 422 + `detected_type: thai_id`
- [ ] ส่ง passport image พร้อม `type=thai_id` → 422 + `detected_type: passport`
- [ ] Log file (1 request) — ไม่มี first_name/last_name/document_number/DOB ปรากฏที่ใดเลย
- [ ] Request ID เดียวกันใน log entries ของ request นั้น + response header
- [ ] NestJS snippet รัน + เรียก orc-service สำเร็จ (test กับ NestJS dev จริง)

---

## Out of plan (อย่าไปทำตอน MVP)

- Persistence / DB
- Caching
- Multi-tenant routing
- Rate limiting (NestJS ทำแทน)
- Metrics (Prometheus etc.) — รอจนกว่าจะมี monitoring stack
- ที่อยู่, รูป, expiry, issue date
- TM.30 integration
- Async job queue
- GPU
- Mobile/client-side OCR

---

## Definition of Done (ทั้งโปรเจกต์)

- [ ] ทุก phase ผ่าน validation gate
- [ ] `docker compose up` จาก clean machine → ใช้งานได้
- [ ] NestJS เรียก `/scan` ส่ง passport + Thai ID จริง → ได้ JSON ครบตาม PRD
- [ ] Log ตรวจแล้วไม่มี PII
- [ ] README ใช้งานได้จริงโดยคนอื่นที่ไม่เคยเห็น repo
- [ ] PRD + PLAN ใน repo เป็น source of truth
