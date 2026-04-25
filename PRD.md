# orc-service — Product Requirements Document

OCR microservice สำหรับระบบ hotel check-in ทำหน้าที่ดึงข้อมูลจากบัตรประชาชนไทยและ passport ต่างประเทศ คืนเป็น JSON ให้ NestJS backend

---

## 1. Overview

**Problem:** พนักงาน front desk พิมพ์ข้อมูลแขกจากบัตร/passport ด้วยมือทุกครั้งที่ check-in ช้า + ผิดพลาดบ่อย + กระทบ TM.30 reporting (ต้องส่งข้อมูลแขกต่างชาติเข้า ตม. ภายใน 24 ชม.)

**Solution:** Python microservice แยกออกมาจาก NestJS รับภาพบัตร/passport → ส่งคืน structured JSON ใช้ OCR + MRZ parsing แบบ self-hosted ไม่มีค่าใช้จ่ายต่อ scan

**Why Python (not extending NestJS):** ทีมเคยพยายามทำใน JS (Tesseract.js) แล้ว accuracy ไม่ผ่าน โดยเฉพาะภาษาไทย + ไม่มี PassportEye / PaddleOCR ใน JS ecosystem

---

## 2. Goals & Non-goals

### Goals
- ดึง 6 fields ต่อไปนี้จากทั้ง Thai ID และ passport: first_name (EN), last_name (EN), document_number, date_of_birth, sex, country (ISO-3)
- Passport รองรับทุกประเทศ (ICAO 9303 MRZ)
- Thai ID รองรับบัตรรุ่นปัจจุบัน
- Accuracy พอใช้งาน check-in จริง (พนักงานยืนยัน/แก้ได้ก่อน commit)
- Cost: 0 บาท/เดือน (ไม่รวมค่า server)
- Response time < 3 วินาที sync

### Non-goals
- ❌ KYC / identity verification / liveness / face match
- ❌ Multi-tenant SaaS (สำหรับโรงแรมเครือเดียว / ตัวเองก่อน)
- ❌ ดึงที่อยู่, รูป, วันหมดอายุ, วันออกบัตร, ศาสนา
- ❌ OCR ชื่อภาษาไทย (ใช้ชื่อ EN จากบัตรแทน)
- ❌ OCR ด้านหลัง Thai ID (ข้อมูลที่ต้องการอยู่ด้านหน้าครบ)
- ❌ Cloud AI APIs (Google Document AI, AWS Textract, Azure) หรือ LLM (Claude/Gemini/GPT-4V)
- ❌ KYC vendors (Microblink/Regula/Onfido)

---

## 3. Users & Context

### Callers
ระบบนี้ถูกเรียกโดย **NestJS backend เท่านั้น** (ไม่เปิดให้ browser เรียกตรง)

```
NextJS (frontend) ──upload image──> NestJS ──multipart──> orc-service (ตัวนี้)
                                        <──── JSON ────
```

### Image sources (ผ่าน NestJS)
- พนักงาน front desk ใช้ phone camera / webcam / file upload
- แขกใช้ phone camera / photo upload จากมือถือ

→ คุณภาพภาพไม่แน่นอน ต้อง preprocess หนักพอควร

### Workload (MVP baseline)
- 1 โรงแรม, ~50-300 scan/วัน
- Peak: ~10 scan/ชม.
- Single worker + CPU-only ไม่ต้อง GPU

---

## 4. API Specification

### 4.1 Endpoint

```http
POST /scan
Headers:
  X-API-Key: <shared-secret>
  Content-Type: multipart/form-data

Body fields:
  type   — "thai_id" | "passport"   (required)
  image  — file (JPG หรือ PNG, max 10MB)  (required)
```

### 4.2 Response schema (success)

```json
{
  "type": "thai_id",
  "first_name": "SOMCHAI",
  "last_name": "JAIDEE",
  "document_number": "1234567890123",
  "date_of_birth": "1985-03-15",
  "sex": "M",
  "country": "THA",
  "document_valid": true,
  "confidence": {
    "overall": 0.89,
    "first_name": 0.95,
    "last_name": 0.92,
    "document_number": 0.99,
    "date_of_birth": 0.88,
    "sex": 0.75,
    "country": 1.0
  },
  "warnings": []
}
```

**Partial success** (อ่านได้บางส่วน): คืน 200, fields ที่อ่านไม่ได้เป็น `null`, `confidence.<field>` = 0, เพิ่ม entry ใน `warnings`

### 4.3 Status codes

| Code | Meaning |
|------|---------|
| 200  | OCR ran, fields returned (อาจมี field เป็น null + confidence ต่ำ — frontend ตัดสินใจ) |
| 400  | Malformed input (ไม่มี image, format ไม่รองรับ, file ใหญ่เกิน 10MB, type ไม่ valid) |
| 401  | Missing / bad API key |
| 422  | OCR ran แต่ (a) ไม่เจอเอกสาร หรือ (b) detected type ไม่ตรงกับที่ส่งมา |
| 500  | Internal error |

### 4.4 Error body

```json
{ "error": "type_mismatch", "message": "Detected passport but type=thai_id", "detected_type": "passport" }
```

Error codes: `no_document_detected`, `type_mismatch`, `unsupported_format`, `file_too_large`, `image_invalid`

### 4.5 Utility

```http
GET /health  →  200 {"status":"ok"}
```

---

## 5. Field Extraction Rules

### 5.1 Passport (via MRZ, ICAO 9303)

| Field | Source |
|-------|--------|
| first_name | MRZ given names (split by `<<`, join ด้วย space) |
| last_name | MRZ surname |
| document_number | MRZ line 2, positions 1-9 |
| date_of_birth | MRZ line 2 (YYMMDD → YYYY-MM-DD, disambiguate century) |
| sex | MRZ line 2, position 21 (M/F/X/<) — `<` → null |
| country | MRZ line 2, positions 11-13 (ISO-3) |
| document_valid | ทุก check digit ใน MRZ ผ่าน |

### 5.2 Thai ID Card (OCR + template)

| Field | Source |
|-------|--------|
| first_name | บรรทัด "Name" (EN) — แยก first word หลัง title (Mr./Mrs./Miss) |
| last_name | บรรทัด "Last name" (EN) |
| document_number | "Identification Number" 13 หลัก |
| date_of_birth | "Date of Birth" — ถ้าเป็น พ.ศ. ลบ 543 → ค.ศ. → ISO 8601 |
| sex | Derive จาก Thai title prefix บนบรรทัดชื่อไทย: `นาย`/`เด็กชาย` → M ; `นาง`/`นางสาว`/`เด็กหญิง` → F ; ถ้าอ่านไม่ออก → null |
| country | Hard-coded `"THA"` |
| document_valid | ตรวจ mod-11 checksum ของเลข 13 หลัก |

---

## 6. Technical Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.11+ |
| Web framework | FastAPI + uvicorn |
| OCR (Thai ID) | PaddleOCR (Thai + English) |
| MRZ (passport) | PassportEye หรือ fastmrz |
| Image preprocessing | OpenCV |
| Validation | Pydantic v2 |
| Packaging | Docker + docker-compose |
| Logging | Python `logging` (JSON format, stdout) |

**ไม่ใช้:** cloud OCR APIs, LLMs, paid services, KYC vendors

---

## 7. Preprocessing Pipeline

ใช้ "Standard" pipeline บน OpenCV:

1. **Decode + validate** — ตรวจ format/size/dimension, resize ถ้ากว้างเกิน 2000px
2. **Document boundary detection** — contour detection หา 4 มุมของเอกสาร
3. **Perspective correction** — warp ให้เป็นสี่เหลี่ยมผืนผ้าตรง
4. **Auto-rotation** — OCR ทั้ง 0°/90°/180°/270° เลือก orientation ที่ confidence สูงสุด
5. **Contrast normalization** — CLAHE หรือ adaptive threshold
6. **Dispatch** — ส่งไปที่ `thai_id_scanner` หรือ `passport_scanner`

**Type-mismatch detection:**
- Passport scanner หา MRZ pattern (2 บรรทัดล่าง, OCR-B font, `<` separator) → ถ้าเจอใน image แต่ `type=thai_id` → 422 mismatch
- Thai ID scanner หา Thai script + เลข 13 หลัก layout → ถ้าเจอใน image แต่ `type=passport` → 422 mismatch

---

## 8. Non-Functional Requirements

### 8.1 Performance
- p95 response time < 3 วินาที ต่อ request บน 2-4 vCPU
- Concurrency: ≥ 2 concurrent requests per worker
- Memory: < 1GB per worker (PaddleOCR models โหลดครั้งเดียวตอน start)

### 8.2 Security / PDPA
- **In-memory only** — ไม่ save image ลง disk ไม่ cache response
- **Logs ห้ามมี PII** — log ได้แค่: `request_id`, timestamp, duration_ms, status_code, type, `confidence.overall`, error_code
- **ห้าม log**: image bytes, first_name, last_name, document_number, DOB, country (ISO code ของแขกก็นับเป็น PII รวมกับอื่น)
- API key ผ่าน env var, ไม่ hardcode
- TLS จัดการที่ reverse proxy (nginx/traefik) หน้า orc-service

### 8.3 Deployment
- Same host กับ NestJS (MVP)
- Docker Compose network — NestJS เรียก `http://orc-service:8000/scan`
- Stateless — restart ได้ทุกเมื่อ ไม่มี data loss
- Health check endpoint สำหรับ monitoring

### 8.4 Configuration (env vars)

```
API_KEY=<shared-secret>
PORT=8000
MAX_IMAGE_SIZE_MB=10
MAX_IMAGE_DIMENSION=2000
LOG_LEVEL=info
CONFIDENCE_LOG_THRESHOLD=0.0   # log confidence แต่ไม่บังคับ reject
```

---

## 9. Project Structure

```
orc-service/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── README.md
├── PRD.md                       (ไฟล์นี้)
└── app/
    ├── main.py                  (FastAPI app + routes + auth middleware)
    ├── config.py                (env var loading)
    ├── schemas.py               (Pydantic request/response models)
    ├── preprocessing.py         (OpenCV pipeline + auto-rotation)
    ├── scanners/
    │   ├── __init__.py
    │   ├── thai_id.py           (PaddleOCR + template + checksum)
    │   └── passport.py          (MRZ extraction + check digits)
    ├── validators.py            (mod-11 Thai ID, MRZ check digits, sex derivation)
    └── logging_config.py        (JSON formatter, PII filter)
```

---

## 10. Known Risks & Trade-offs

| Risk | Mitigation |
|------|------------|
| Accuracy ต่ำบนภาพคุณภาพแย่ (เบลอ, มืด, เฉียงมาก) | Preprocessing + auto-rotation + คืน confidence per field → frontend ให้คนแก้ได้ |
| PaddleOCR ขนาดใหญ่ (~200-500MB model) | ยอมรับ — trade-off ระหว่าง accuracy กับ bundle size |
| Thai ID "sex" derive จาก title prefix → ถ้า OCR ผิด sex ก็ผิด | คืน null ถ้าไม่มั่นใจ, ไม่เดา |
| Passport visual-zone ต่างชาติบาง design อ่านยาก | ใช้ MRZ (standardized) ไม่ใช่ visual zone |
| Single-host deployment → crash = down | MVP acceptable, ภายหลัง scale horizontal ได้ง่าย (stateless) |
| No KYC / liveness → ใช้กับ high-risk verification ไม่ได้ | Explicit non-goal — ถ้าต้องการ ต้องรื้อ scope ใหม่ |

---

## 11. Out of Scope / Future Work

- ดึง "ที่อยู่" จาก Thai ID
- ดึงรูปหน้าจากบัตร/passport
- ดึงวันหมดอายุ, วันออกบัตร
- OCR passport visual zone (นอกเหนือ MRZ)
- Multi-tenancy / billing
- Batch API
- Async job + webhook
- GPU inference
- TM.30 submission (ปล่อยให้ NestJS จัดการหลังจาก verify ข้อมูล)
- Liveness / face match / KYC
- Mobile SDK / client-side OCR
