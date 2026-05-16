"""Run once to initialise the database with 19 rooms and a default owner account."""
from database import engine, SessionLocal
import models
from models import User, Room, InvoiceSetting
from auth import get_password_hash

models.Base.metadata.create_all(bind=engine)

db = SessionLocal()

# Default owner
if not db.query(User).filter(User.username == "admin").first():
    db.add(User(
        username="admin",
        password_hash=get_password_hash("admin1234"),
        full_name="เจ้าของโรงแรม",
        role="owner",
        salary=0,
        is_active=True,
    ))
    print("[OK] สร้างบัญชีเจ้าของ  username=admin  password=admin1234")

# 19 rooms
room_configs = [
    ("101", "Standard A", 800),
    ("102", "Standard B", 800),
    ("103", "Standard C", 800),
    ("104", "Standard D", 800),
    ("105", "Standard E", 800),
    ("106", "Deluxe A",  1200),
    ("107", "Deluxe B",  1200),
    ("108", "Deluxe C",  1200),
    ("109", "Deluxe D",  1200),
    ("110", "Deluxe E",  1200),
    ("201", "Superior A", 1500),
    ("202", "Superior B", 1500),
    ("203", "Superior C", 1500),
    ("204", "Superior D", 1500),
    ("205", "Superior E", 1500),
    ("301", "Suite A",   2500),
    ("302", "Suite B",   2500),
    ("303", "Suite C",   2500),
    ("304", "Penthouse", 4500),
]

for number, name, price in room_configs:
    if not db.query(Room).filter(Room.room_number == number).first():
        db.add(Room(room_number=number, name=name, price_per_night=price))

# Default invoice settings
if not db.query(InvoiceSetting).first():
    db.add(InvoiceSetting(
        company_name="โรงแรมของฉัน",
        address="123 ถนนสุขุมวิท กรุงเทพฯ 10110",
        phone="02-000-0000",
        tax_id="",
        bank_info="ธนาคารกสิกรไทย  เลขบัญชี 000-0-00000-0\nชื่อบัญชี โรงแรมของฉัน",
        footer_notes="ขอบคุณที่ใช้บริการ",
    ))

db.commit()
db.close()
print("[OK] ฐานข้อมูลพร้อมใช้งาน")
