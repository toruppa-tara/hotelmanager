# 🏨 Hotel Manager — ระบบจัดการโรงแรม

ระบบจัดการโรงแรมครบวงจร สร้างด้วย Python FastAPI + SQLite

---

## 🚀 วิธีติดตั้งและรัน

### 1. ติดตั้ง Python dependencies
```bash
pip install -r requirements.txt
```

### 2. สร้างฐานข้อมูลและ 19 ห้องเริ่มต้น
```bash
python init_db.py
```

### 3. รันเซิร์ฟเวอร์
```bash
python main.py
```

เปิดบราวเซอร์ที่ **http://localhost:8000**

---

## 🔑 บัญชีเริ่มต้น

| Username | Password   | สิทธิ์    |
|----------|------------|-----------|
| admin    | admin1234  | เจ้าของ   |

> ⚠️ เปลี่ยนรหัสผ่านทันทีหลังเข้าสู่ระบบครั้งแรก

---

## ✨ ฟีเจอร์หลัก

| # | ฟีเจอร์ | รายละเอียด |
|---|---------|------------|
| 1 | **ตารางห้องพัก** | Grid Calendar 19 ห้อง × 31 วัน คลิกเพื่อจอง |
| 2 | **จองห้องพัก** | ระบุพนักงาน มัดจำ (สด/โอน+วันที่) ยอดค้าง หมายเหตุ |
| 3 | **ฐานข้อมูล** | SQLite ตรวจย้อนหลังได้ทุกรายการ |
| 4 | **รายงานยอดขาย** | รายวัน/รายเดือน/กำหนดเอง พร้อมกราฟ |
| 5 | **ระบบสมาชิก** | จดจำลูกค้า autocomplete เมื่อจองซ้ำ |
| 6 | **สิทธิ์การเข้าถึง** | เจ้าของ/ผู้จัดการ/พนักงาน |
| 7 | **เงินเดือนพนักงาน** | สรุปเงินเดือน บันทึกการเบิก (เจ้าของเท่านั้น) |
| 8 | **ระบบ Login** | JWT Cookie สร้าง User ได้ไม่จำกัด |
| 9 | **บิลเงินสด** | พิมพ์ได้ทันที รองรับโลโก้/ที่อยู่/เลขภาษี |
| 10 | **Web Ready** | รันบน Cloud/VPS ได้ทันที |

---

## 🌐 Deploy บน Cloud (ตัวอย่าง)

### Railway / Render / VPS
```bash
# ตั้ง host = 0.0.0.0 แล้วรัน
uvicorn main:app --host 0.0.0.0 --port 8000
```

### ใช้ PostgreSQL แทน SQLite
แก้ `database.py`:
```python
SQLALCHEMY_DATABASE_URL = "postgresql://user:pass@host/dbname"
```
ติดตั้งเพิ่ม: `pip install psycopg2-binary`

---

## 📁 โครงสร้างไฟล์

```
HotelManager/
├── main.py              ← FastAPI routes ทั้งหมด
├── models.py            ← SQLAlchemy database models
├── database.py          ← DB connection
├── auth.py              ← JWT authentication
├── init_db.py           ← สร้าง DB + ข้อมูลเริ่มต้น
├── requirements.txt
├── hotel.db             ← SQLite database (สร้างอัตโนมัติ)
├── templates/           ← Jinja2 HTML templates
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── rooms.html       ← Calendar grid
│   ├── members.html
│   ├── reports.html
│   ├── payroll.html
│   ├── users.html
│   ├── settings.html
│   ├── invoice_print.html
│   └── partials/
│       └── booking_modal.html
├── static/
│   ├── css/style.css
│   └── js/app.js
└── uploads/
    └── logos/           ← อัปโหลดโลโก้ที่นี่
```
