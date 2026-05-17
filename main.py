import os, json
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Request, Depends, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, extract

from database import engine, get_db, SessionLocal
import models
from models import (User, Room, Member, Booking, Payment, Expense,
                    Withdrawal, InvoiceSetting, Invoice, Maintenance, RolePermission, Absence,
                    PayrollSettings, PayrollBonus)


# ─── Permissions ────────────────────────────────────────────────────
# Owner has ALL permissions implicitly. Manager/Staff are governed by
# rows in the role_permissions table; defaults are seeded on startup.
FEATURES = [
    ("manage_rooms",       "ตั้งค่าห้อง / ปิดห้อง / ซ่อมบำรุง"),
    ("view_reports",       "ดูรายงานยอดขาย"),
    ("manage_expenses",    "จัดการค่าใช้จ่าย (ดูทุกรายการ / ลบได้)"),
    ("record_expense",     "บันทึกค่าใช้จ่าย (ลบไม่ได้)"),
    ("manage_payroll",     "ระบบเงินเดือน / การเบิกเงิน (ดูทุกคน)"),
    ("record_withdrawal",  "บันทึกเบิกเงินตัวเอง (ลบไม่ได้)"),
    ("manage_users",       "จัดการผู้ใช้งาน"),
    ("manage_invoice",     "ตั้งค่าบิล / โลโก้"),
]
FEATURE_KEYS = [k for k, _ in FEATURES]

# Default room layout — 19 rooms total
# A01-A10, B01-B09 — all "Double Bedroom" @ 400 except:
#   A05, A07, A08, B06, B07 → "Triple Bedroom" @ 550
TRIPLE_ROOMS = {"A05", "A07", "A08", "B06", "B07"}
DEFAULT_ROOMS = []
for prefix, count in [("A", 10), ("B", 9)]:
    for i in range(1, count + 1):
        num = f"{prefix}{i:02d}"
        if num in TRIPLE_ROOMS:
            DEFAULT_ROOMS.append((num, "Triple Bedroom", 550))
        else:
            DEFAULT_ROOMS.append((num, "Double Bedroom", 400))

# Default permissions matrix used when seeding for the first time
DEFAULT_PERMISSIONS = {
    "manager": {"manage_rooms": True},     # was previously the only feature managers had
    "staff":   {},                          # staff has none by default
}


def seed_role_permissions():
    db = SessionLocal()
    try:
        for role, perms in DEFAULT_PERMISSIONS.items():
            for feat in FEATURE_KEYS:
                exists = db.query(RolePermission).filter_by(role=role, feature=feat).first()
                if not exists:
                    db.add(RolePermission(role=role, feature=feat,
                                           enabled=perms.get(feat, False)))
        db.commit()
    finally:
        db.close()


def get_permissions(role: str, db: Session) -> dict:
    """Return {feature_key: bool} for the given role. Owner gets everything."""
    if role == "owner":
        return {k: True for k in FEATURE_KEYS}
    perms = {k: False for k in FEATURE_KEYS}
    for p in db.query(RolePermission).filter(RolePermission.role == role).all():
        perms[p.feature] = bool(p.enabled)
    return perms


def has_permission(request: Request, feature: str, db: Session) -> bool:
    user = get_current_user_from_cookie(request)
    if not user:
        return False
    if user.get("role") == "owner":
        return True
    p = db.query(RolePermission).filter_by(
        role=user.get("role"), feature=feature
    ).first()
    return bool(p and p.enabled)


def require_permission(request: Request, feature: str, db: Session):
    if not has_permission(request, feature, db):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์เข้าถึง")
from auth import (verify_password, get_password_hash, create_access_token,
                  get_current_user_from_cookie, require_login,
                  require_owner, require_owner_or_manager)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Hotel Manager", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Ensure uploads directory exists (not in git, must create on cloud)
_uploads_dir = os.path.join(BASE_DIR, "uploads", "logos")
os.makedirs(_uploads_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=os.path.join(BASE_DIR, "uploads")), name="uploads")

# cache_size=0 avoids LRU dict-key bug on Python 3.14
_jinja_env = Environment(
    loader=FileSystemLoader(os.path.join(BASE_DIR, "templates")),
    autoescape=select_autoescape(["html"]),
    cache_size=0,
)
templates = Jinja2Templates(env=_jinja_env)

# Seed default role permissions on startup (idempotent)
seed_role_permissions()


def seed_initial_data():
    """Bootstrap admin + 19 rooms ONLY on a truly fresh database.
    After the first run, nothing is auto-recreated — deletions stay deleted."""
    import traceback
    from auth import get_password_hash
    from models import InvoiceSetting
    db = SessionLocal()
    try:
        # Only seed if there are NO users at all (true first-run on fresh DB)
        if db.query(User).count() > 0:
            return
        print("[seed] fresh database — seeding admin + 19 rooms + invoice", flush=True)
        db.add(User(
            username="admin",
            password_hash=get_password_hash("admin1234"),
            full_name="Owner",
            role="owner",
            salary=0,
            is_active=True,
        ))
        for number, name, price in DEFAULT_ROOMS:
            db.add(Room(room_number=number, name=name, price_per_night=price))
        db.add(InvoiceSetting(
            company_name="My Hotel",
            address="123 Sukhumvit Rd, Bangkok 10110",
            phone="02-000-0000",
            tax_id="",
            bank_info="Bank Account",
            footer_notes="Thank you",
        ))
        db.commit()
        print("[seed] done", flush=True)
    except Exception as e:
        print(f"[seed] ERROR: {e}", flush=True)
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

try:
    seed_initial_data()
except Exception as e:
    import traceback
    print(f"[startup] seed_initial_data crashed: {e}", flush=True)
    traceback.print_exc()

def migrate_db():
    from sqlalchemy import text

    # ── PostgreSQL: only add columns introduced after the initial schema
    if engine.dialect.name != "sqlite":
        with engine.connect() as conn:
            for table, col, ddl in [
                ("bookings", "extra_charges", "TEXT DEFAULT '[]'"),
            ]:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                    conn.commit()
                except Exception:
                    pass  # column already exists
        return


    with engine.connect() as conn:
        # bookings table
        for col, ddl in [
            ("security_deposit",      "REAL DEFAULT 200"),
            ("security_deposit_type", "VARCHAR(50) DEFAULT 'cash'"),
            ("security_deposit_note", "VARCHAR(200) DEFAULT ''"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE bookings ADD COLUMN {col} {ddl}"))
                conn.commit()
            except Exception:
                pass
        # users table
        for col, ddl in [
            ("wage_type",  "VARCHAR(10) DEFAULT 'monthly'"),
            ("daily_rate", "REAL DEFAULT 0"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {ddl}"))
                conn.commit()
            except Exception:
                pass
        # absences table (create if not exists)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS absences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                absence_date DATE NOT NULL,
                reason TEXT DEFAULT '',
                recorded_by_id INTEGER REFERENCES users(id),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()
        # payroll_settings table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS payroll_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                no_absence_bonus REAL DEFAULT 1000,
                free_absence_days INTEGER DEFAULT 4
            )
        """))
        conn.commit()
        # payroll_bonuses table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS payroll_bonuses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                year INTEGER NOT NULL,
                month INTEGER NOT NULL,
                special_bonus REAL DEFAULT 0,
                notes TEXT DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()

migrate_db()

# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def flash(response, message: str, category: str = "success"):
    response.set_cookie("flash_msg", message, max_age=5)
    response.set_cookie("flash_cat", category, max_age=5)


def get_flash(request: Request):
    msg = request.cookies.get("flash_msg", "")
    cat = request.cookies.get("flash_cat", "success")
    return msg, cat


def ctx(request: Request, db: Session, extra: dict = None):
    """Build template context (without 'request' — Starlette 1.0 passes it separately)."""
    user_data = get_current_user_from_cookie(request)
    msg, cat = get_flash(request)
    perms = get_permissions(user_data.get("role"), db) if user_data else {}
    base = {"current_user": user_data, "flash_msg": msg, "flash_cat": cat, "perms": perms}
    if extra:
        base.update(extra)
    return base


def render(request: Request, template: str, context: dict = None):
    """Starlette 1.0 compatible TemplateResponse wrapper."""
    return templates.TemplateResponse(request, template, context or {})


def booking_status_for_grid(db: Session, year: int, month: int):
    from calendar import monthrange
    _, days_in_month = monthrange(year, month)
    start = date(year, month, 1)
    end = date(year, month, days_in_month)

    # Include checked_out so history stays visible in the grid (greyed out)
    bookings = db.query(Booking).filter(
        Booking.status.in_(["confirmed", "checked_in", "checked_out"]),
        Booking.check_in_date <= end,
        Booking.check_out_date > start
    ).all()

    grid = {}  # room_id -> {day: cell_info}
    for b in bookings:
        room_id = b.room_id
        if room_id not in grid:
            grid[room_id] = {}
        # Priority: checked_out > checked_in > payment-status
        if b.status == "checked_out":
            pay_class = "pay-checkedout"   # ⚫ เช็คเอาต์แล้ว
        elif b.status == "checked_in":
            pay_class = "pay-checkedin"    # 🟢 เช็คอินแล้ว (กำลังเข้าพัก)
        elif b.outstanding_balance <= 0:
            pay_class = "pay-paid"         # 🔵 ชำระครบ รอเช็คอิน
        else:
            pay_class = "pay-partial"      # 🟡 จอง / ค้างชำระ (รวมทั้งมัดจำและยังไม่ชำระ)
        d_start = max(b.check_in_date, start)
        d_end_incl = min(b.check_out_date - timedelta(days=1), end)
        span = (d_end_incl - d_start).days + 1
        d = d_start
        while d < b.check_out_date and d <= end:
            if d == d_start:
                grid[room_id][d.day] = {
                    "type": "booking",
                    "booking_id": b.id,
                    "status": b.status,
                    "guest": b.member.name if b.member else b.guest_name,
                    "pay_class": pay_class,
                    "outstanding": b.outstanding_balance,
                    "deposit": b.deposit_amount,
                    "span": span,
                    "check_in": b.check_in_date.isoformat(),
                    "check_out": b.check_out_date.isoformat(),
                }
            else:
                grid[room_id][d.day] = {
                    "type": "booking_continue",
                    "booking_id": b.id,
                }
            d += timedelta(days=1)

    # Maintenance ranges — only block the days within their range
    maints = db.query(Maintenance).filter(
        Maintenance.start_date <= end,
        Maintenance.end_date >= start
    ).all()
    for m in maints:
        if m.room_id not in grid:
            grid[m.room_id] = {}
        d = max(m.start_date, start)
        while d <= m.end_date and d <= end:
            # Don't overwrite an existing booking (bookings take priority on the same day)
            if d.day not in grid[m.room_id]:
                grid[m.room_id][d.day] = {
                    "type": "maintenance",
                    "maintenance_id": m.id,
                    "note": m.note or "ซ่อมบำรุง",
                }
            d += timedelta(days=1)

    return grid, days_in_month


# ─────────────────────────────────────────────
#  Auth Routes
# ─────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    user = get_current_user_from_cookie(request)
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/login", status_code=302)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = get_current_user_from_cookie(request)
    if user:
        return RedirectResponse("/dashboard", status_code=302)
    return render(request, "login.html")


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username, User.is_active == True).first()
        if not user or not verify_password(password, user.password_hash):
            return render(request, "login.html", {"error": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"})
        token = create_access_token({"sub": str(user.id), "username": user.username,
                                     "role": user.role, "full_name": user.full_name})
        response = RedirectResponse("/dashboard", status_code=302)
        response.set_cookie("access_token", token, httponly=True, max_age=43200)
        return response
    finally:
        db.close()


@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("access_token")
    return response


@app.post("/api/change-password")
async def api_change_password(request: Request, db: Session = Depends(get_db)):
    user_data = get_current_user_from_cookie(request)
    if not user_data:
        raise HTTPException(status_code=401, detail="กรุณาเข้าสู่ระบบ")
    data = await request.json()
    current = (data.get("current_password") or "").strip()
    new_pwd = (data.get("new_password") or "").strip()
    if not current or not new_pwd:
        raise HTTPException(status_code=400, detail="กรุณากรอกรหัสผ่านให้ครบ")
    if len(new_pwd) < 4:
        raise HTTPException(status_code=400, detail="รหัสผ่านใหม่ต้องมีอย่างน้อย 4 ตัวอักษร")
    user = db.query(User).filter(User.id == int(user_data.get("sub"))).first()
    if not user:
        raise HTTPException(status_code=404, detail="ไม่พบผู้ใช้")
    if not verify_password(current, user.password_hash):
        raise HTTPException(status_code=400, detail="รหัสผ่านเดิมไม่ถูกต้อง")
    user.password_hash = get_password_hash(new_pwd)
    db.commit()
    return {"message": "เปลี่ยนรหัสผ่านเรียบร้อย"}


# ─────────────────────────────────────────────
#  Dashboard
# ─────────────────────────────────────────────

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    today = date.today()
    rooms = db.query(Room).all()
    total_rooms = len(rooms)

    # Rooms with active maintenance record today
    maintenance_ids = {
        m.room_id for m in db.query(Maintenance).filter(
            Maintenance.start_date <= today,
            Maintenance.end_date >= today
        ).all()
    }
    maintenance = len(maintenance_ids)

    occupied_ids = {
        b.room_id for b in db.query(Booking).filter(
            Booking.status.in_(["confirmed", "checked_in"]),
            Booking.check_in_date <= today,
            Booking.check_out_date > today
        ).all()
    }
    # don't double-count maintenance rooms in occupied
    occupied_ids -= maintenance_ids
    occupied = len(occupied_ids)
    available = max(0, total_rooms - occupied - maintenance)

    checkin_bookings = db.query(Booking).filter(
        Booking.check_in_date == today,
        Booking.status == "confirmed"
    ).all()
    checkin_today = len(checkin_bookings)
    checkout_bookings = db.query(Booking).filter(
        Booking.check_out_date == today,
        Booking.status == "checked_in"
    ).all()
    checkout_today = len(checkout_bookings)

    month_income = 0
    if user.get("role") == "owner":
        month_income = db.query(func.sum(Payment.amount)).filter(
            extract("month", Payment.payment_date) == today.month,
            extract("year", Payment.payment_date) == today.year
        ).scalar() or 0

    recent_bookings = db.query(Booking).order_by(Booking.created_at.desc()).limit(8).all()

    can_expense = has_permission(request, "manage_expenses", db) or has_permission(request, "record_expense", db)
    today_expenses = []
    if can_expense:
        today_expenses = db.query(Expense).filter(Expense.expense_date == today).order_by(Expense.created_at.desc()).all()

    return render(request, "dashboard.html", ctx(request, db, {
        "total_rooms": total_rooms, "available": available,
        "occupied": occupied, "maintenance": maintenance,
        "checkin_today": checkin_today, "checkin_bookings": checkin_bookings,
        "checkout_today": checkout_today, "checkout_bookings": checkout_bookings,
        "month_income": month_income, "recent_bookings": recent_bookings,
        "today": today,
        "staff_list": db.query(User).filter(User.is_active == True).all(),
        "today_expenses": today_expenses,
        "can_expense": can_expense,
        "can_manage_expenses": has_permission(request, "manage_expenses", db),
    }))


# ─────────────────────────────────────────────
#  Rooms
# ─────────────────────────────────────────────

@app.get("/rooms", response_class=HTMLResponse)
async def rooms_page(request: Request, year: int = None, month: int = None, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    today = date.today()
    year = year or today.year
    month = month or today.month

    rooms = db.query(Room).order_by(Room.room_number).all()
    grid, days_in_month = booking_status_for_grid(db, year, month)
    staff_list = db.query(User).filter(User.is_active == True).all()

    prev_month = date(year, month, 1) - timedelta(days=1)
    next_month = date(year, month, days_in_month) + timedelta(days=1)

    return render(request, "rooms.html", ctx(request, db, {
        "rooms": rooms, "grid": grid,
        "year": year, "month": month,
        "days_in_month": days_in_month,
        "days": list(range(1, days_in_month + 1)),
        "today": today,
        "prev_year": prev_month.year, "prev_month": prev_month.month,
        "next_year": next_month.year, "next_month": next_month.month,
        "staff_list": staff_list,
        "month_name": ["", "มกราคม","กุมภาพันธ์","มีนาคม","เมษายน","พฤษภาคม","มิถุนายน",
                        "กรกฎาคม","สิงหาคม","กันยายน","ตุลาคม","พฤศจิกายน","ธันวาคม"][month],
    }))


@app.get("/api/rooms", response_class=JSONResponse)
async def api_get_rooms(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    rooms = db.query(Room).order_by(Room.room_number).all()
    return [{"id": r.id, "room_number": r.room_number, "name": r.name,
             "price_per_night": r.price_per_night, "status": r.status, "description": r.description}
            for r in rooms]


@app.post("/api/rooms")
async def api_create_room(request: Request, db: Session = Depends(get_db)):
    require_permission(request, "manage_rooms", db)
    data = await request.json()
    new_number = (data.get("room_number") or "").strip()
    if not new_number:
        raise HTTPException(status_code=400, detail="กรุณาระบุเลขห้อง")
    if db.query(Room).filter(Room.room_number == new_number).first():
        raise HTTPException(status_code=400, detail=f"เลขห้อง '{new_number}' มีอยู่แล้ว")
    room = Room(
        room_number=new_number, name=data["name"],
        price_per_night=float(data.get("price_per_night", 0)),
        status=data.get("status", "available"),
        description=data.get("description", "")
    )
    db.add(room); db.commit(); db.refresh(room)
    return {"id": room.id, "message": "สร้างห้องเรียบร้อย"}


@app.get("/api/maintenances", response_class=JSONResponse)
async def api_list_maintenances(request: Request, room_id: int = None,
                                  upcoming: int = 0, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    q = db.query(Maintenance)
    if room_id:
        q = q.filter(Maintenance.room_id == room_id)
    if upcoming:
        today = date.today()
        q = q.filter(Maintenance.end_date >= today)
    items = q.order_by(Maintenance.start_date.desc()).all()
    return [{"id": m.id, "room_id": m.room_id,
             "room_number": m.room_id and db.query(Room).get(m.room_id).room_number,
             "start_date": str(m.start_date), "end_date": str(m.end_date),
             "note": m.note} for m in items]


@app.post("/api/maintenances")
async def api_create_maintenance(request: Request, db: Session = Depends(get_db)):
    require_permission(request, "manage_rooms", db)
    user = get_current_user_from_cookie(request)
    data = await request.json()
    room_id = int(data["room_id"])
    start = date.fromisoformat(data["start_date"])
    end = date.fromisoformat(data["end_date"])
    if end < start:
        raise HTTPException(status_code=400, detail="วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่ม")
    # Block if there's an active booking overlapping this range
    conflict = db.query(Booking).filter(
        Booking.room_id == room_id,
        Booking.status.in_(["confirmed", "checked_in"]),
        Booking.check_in_date <= end,
        Booking.check_out_date > start,
    ).first()
    if conflict:
        raise HTTPException(status_code=400,
            detail=f"ช่วงนี้มีการจองอยู่แล้ว (Booking #{conflict.id})")
    m = Maintenance(
        room_id=room_id, start_date=start, end_date=end,
        note=data.get("note", "").strip(),
        created_by_id=int(user["sub"]),
    )
    db.add(m); db.commit(); db.refresh(m)
    return {"id": m.id, "message": "บันทึกการปิดห้องเรียบร้อย"}


@app.delete("/api/maintenances/{mid}")
async def api_delete_maintenance(mid: int, request: Request, db: Session = Depends(get_db)):
    require_permission(request, "manage_rooms", db)
    m = db.query(Maintenance).filter(Maintenance.id == mid).first()
    if not m:
        raise HTTPException(status_code=404)
    db.delete(m); db.commit()
    return {"message": "ยกเลิกการปิดห้องเรียบร้อย"}


@app.post("/api/rooms/reset-defaults")
async def api_reset_default_rooms(request: Request, db: Session = Depends(get_db)):
    """Owner-only: wipe rooms with no booking history and recreate the default 19 rooms."""
    user = get_current_user_from_cookie(request)
    if not user or user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="เฉพาะเจ้าของเท่านั้น")

    # Check for rooms that have bookings — cannot wipe those
    booked_ids = {b.room_id for b in db.query(Booking).all()}
    locked = db.query(Room).filter(Room.id.in_(booked_ids)).all() if booked_ids else []
    if locked:
        names = ", ".join(r.room_number for r in locked)
        raise HTTPException(
            status_code=400,
            detail=f"ลบไม่ได้: ห้องเหล่านี้มีประวัติการจอง: {names}"
        )

    # Safe to wipe everything (no bookings exist)
    db.query(Maintenance).delete()
    db.query(Room).delete()
    db.commit()

    for number, name, price in DEFAULT_ROOMS:
        db.add(Room(room_number=number, name=name, price_per_night=price))
    db.commit()
    return {"message": f"รีเซ็ตห้องเริ่มต้น {len(DEFAULT_ROOMS)} ห้องเรียบร้อย"}


@app.delete("/api/rooms/{room_id}")
async def api_delete_room(room_id: int, request: Request, db: Session = Depends(get_db)):
    require_permission(request, "manage_rooms", db)
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="ไม่พบห้องพัก")
    # Block deletion if room has any bookings (active or historical)
    booking_count = db.query(Booking).filter(Booking.room_id == room_id).count()
    if booking_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"ห้อง {room.room_number} มีประวัติการจอง {booking_count} รายการ — ลบไม่ได้"
        )
    # Remove related maintenances first (no booking history exists)
    db.query(Maintenance).filter(Maintenance.room_id == room_id).delete()
    db.delete(room)
    db.commit()
    return {"message": f"ลบห้อง {room.room_number} เรียบร้อย"}


@app.put("/api/rooms/{room_id}")
async def api_update_room(room_id: int, request: Request, db: Session = Depends(get_db)):
    require_permission(request, "manage_rooms", db)
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404)
    data = await request.json()
    new_number = (data.get("room_number") or room.room_number).strip()
    if not new_number:
        raise HTTPException(status_code=400, detail="กรุณาระบุเลขห้อง")
    if new_number != room.room_number:
        exists = db.query(Room).filter(Room.room_number == new_number, Room.id != room_id).first()
        if exists:
            raise HTTPException(status_code=400, detail=f"เลขห้อง '{new_number}' มีอยู่แล้ว")
    room.room_number = new_number
    room.name = data.get("name", room.name)
    room.price_per_night = float(data.get("price_per_night", room.price_per_night))
    room.status = data.get("status", room.status)
    room.description = data.get("description", room.description)
    db.commit()
    return {"message": "อัปเดตเรียบร้อย"}


# ─────────────────────────────────────────────
#  Bookings
# ─────────────────────────────────────────────

@app.get("/api/bookings/{booking_id}", response_class=JSONResponse)
async def api_get_booking(booking_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if not b:
        raise HTTPException(status_code=404)
    return {
        "id": b.id, "room_id": b.room_id, "member_id": b.member_id,
        "staff_id": b.staff_id, "guest_name": b.guest_name,
        "check_in_date": str(b.check_in_date), "check_out_date": str(b.check_out_date),
        "num_nights": b.num_nights, "room_price": b.room_price, "total_price": b.total_price,
        "deposit_amount": b.deposit_amount, "deposit_type": b.deposit_type,
        "deposit_date": str(b.deposit_date) if b.deposit_date else "",
        "outstanding_balance": b.outstanding_balance,
        "status": b.status, "notes": b.notes,
        "member_name": b.member.name if b.member else "",
        "room_number": b.room.room_number if b.room else "",
        "security_deposit": b.security_deposit or 0,
        "security_deposit_type": b.security_deposit_type or "cash",
        "security_deposit_note": b.security_deposit_note or "",
        "extra_charges": _parse_extras(b.extra_charges),
    }


def _parse_extras(raw):
    """Safely parse the JSON extra_charges field into a list of {name, amount} dicts."""
    if not raw:
        return []
    try:
        items = json.loads(raw) if isinstance(raw, str) else raw
        out = []
        for it in items or []:
            name = str(it.get("name") or "").strip()
            try:
                amount = float(it.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0
            if name and amount > 0:
                out.append({"name": name, "amount": amount})
        return out
    except Exception:
        return []


def _extras_total(items):
    return sum(float(x.get("amount") or 0) for x in (items or []))


@app.post("/api/bookings")
async def api_create_booking(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    data = await request.json()

    check_in = date.fromisoformat(data["check_in_date"])
    check_out = date.fromisoformat(data["check_out_date"])
    num_nights = (check_out - check_in).days
    if num_nights <= 0:
        raise HTTPException(status_code=400, detail="วันเช็คเอาต์ต้องหลังวันเช็คอิน")

    room = db.query(Room).filter(Room.id == data["room_id"]).first()
    if not room:
        raise HTTPException(status_code=404, detail="ไม่พบห้องพัก")

    # Check conflicts
    conflict = db.query(Booking).filter(
        Booking.room_id == data["room_id"],
        Booking.status.in_(["confirmed", "checked_in"]),
        Booking.check_in_date < check_out,
        Booking.check_out_date > check_in
    ).first()
    if conflict:
        raise HTTPException(status_code=400, detail=f"ห้องนี้มีการจองซ้อนทับในช่วงวันที่ดังกล่าว (Booking #{conflict.id})")

    # Also block if any maintenance covers this range
    maint_conflict = db.query(Maintenance).filter(
        Maintenance.room_id == data["room_id"],
        Maintenance.start_date <= check_out - timedelta(days=1),
        Maintenance.end_date >= check_in,
    ).first()
    if maint_conflict:
        raise HTTPException(status_code=400,
            detail=f"ห้องนี้ถูกปิดซ่อมในช่วง {maint_conflict.start_date} – {maint_conflict.end_date}")

    room_price = float(data.get("room_price") or room.price_per_night)
    extras = _parse_extras(data.get("extra_charges"))
    total_price = room_price * num_nights + _extras_total(extras)
    deposit_amount = float(data.get("deposit_amount") or 0)

    # Member handling
    member_id = data.get("member_id")
    if member_id:
        member = db.query(Member).filter(Member.id == member_id).first()
        if member:
            member.total_stays += 1

    deposit_date = None
    if data.get("deposit_date"):
        deposit_date = date.fromisoformat(data["deposit_date"])

    booking = Booking(
        room_id=data["room_id"],
        member_id=member_id or None,
        staff_id=int(user["sub"]),
        guest_name=data.get("guest_name", ""),
        check_in_date=check_in, check_out_date=check_out,
        num_nights=num_nights, room_price=room_price, total_price=total_price,
        deposit_amount=deposit_amount,
        deposit_type=data.get("deposit_type", ""),
        deposit_date=deposit_date,
        outstanding_balance=total_price - deposit_amount,
        status=data.get("status", "confirmed"),
        notes=data.get("notes", ""),
        security_deposit=float(data.get("security_deposit") or 200),
        security_deposit_type=data.get("security_deposit_type", "cash"),
        security_deposit_note=data.get("security_deposit_note", ""),
        extra_charges=json.dumps(extras, ensure_ascii=False),
    )
    db.add(booking); db.commit(); db.refresh(booking)

    if deposit_amount > 0:
        payment = Payment(
            booking_id=booking.id, amount=deposit_amount,
            payment_type=data.get("deposit_type", "cash"),
            payment_date=deposit_date or check_in,
            notes="มัดจำ", recorded_by_id=int(user["sub"])
        )
        db.add(payment); db.commit()

    return {"id": booking.id, "message": "สร้างการจองเรียบร้อย"}


@app.put("/api/bookings/{booking_id}")
async def api_update_booking(booking_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if not b:
        raise HTTPException(status_code=404)
    data = await request.json()

    if "check_in_date" in data:
        b.check_in_date = date.fromisoformat(data["check_in_date"])
    if "check_out_date" in data:
        b.check_out_date = date.fromisoformat(data["check_out_date"])
        b.num_nights = (b.check_out_date - b.check_in_date).days
    if "room_price" in data:
        b.room_price = float(data["room_price"])
    if "extra_charges" in data:
        extras = _parse_extras(data["extra_charges"])
        b.extra_charges = json.dumps(extras, ensure_ascii=False)
    # Recompute total = room_price × nights + sum(extras)
    extras_total = _extras_total(_parse_extras(b.extra_charges))
    b.total_price = (b.room_price or 0) * (b.num_nights or 0) + extras_total
    if "deposit_amount" in data:
        b.deposit_amount = float(data["deposit_amount"])
    if "deposit_type" in data:
        b.deposit_type = data["deposit_type"]
    if "deposit_date" in data and data["deposit_date"]:
        b.deposit_date = date.fromisoformat(data["deposit_date"])
    if "status" in data:
        b.status = data["status"]
    if "notes" in data:
        b.notes = data["notes"]
    if "guest_name" in data:
        b.guest_name = data["guest_name"]
    if "member_id" in data:
        b.member_id = data["member_id"] or None
    if "security_deposit" in data:
        b.security_deposit = float(data["security_deposit"] or 0)
    if "security_deposit_type" in data:
        b.security_deposit_type = data["security_deposit_type"]
    if "security_deposit_note" in data:
        b.security_deposit_note = data["security_deposit_note"]

    # ✅ Source of truth: outstanding = total - sum(all payments)
    # Never wipe out previously recorded payments
    total_paid = db.query(func.sum(Payment.amount)).filter(Payment.booking_id == b.id).scalar() or 0
    b.outstanding_balance = max(0, b.total_price - total_paid)
    db.commit()
    return {"message": "อัปเดตการจองเรียบร้อย", "outstanding": b.outstanding_balance}


@app.delete("/api/bookings/{booking_id}")
async def api_delete_booking(booking_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user or user.get("role") not in ("owner", "manager"):
        raise HTTPException(status_code=403)
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if not b:
        raise HTTPException(status_code=404)
    b.status = "cancelled"
    db.commit()
    return {"message": "ยกเลิกการจองเรียบร้อย"}


@app.get("/api/bookings", response_class=JSONResponse)
async def api_list_bookings(request: Request, room_id: int = None,
                             date_from: str = None, date_to: str = None,
                             db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    q = db.query(Booking)
    if room_id:
        q = q.filter(Booking.room_id == room_id)
    if date_from:
        q = q.filter(Booking.check_in_date >= date.fromisoformat(date_from))
    if date_to:
        q = q.filter(Booking.check_out_date <= date.fromisoformat(date_to))
    bookings = q.order_by(Booking.check_in_date.desc()).limit(200).all()
    return [{
        "id": b.id, "room_number": b.room.room_number,
        "guest": b.member.name if b.member else b.guest_name,
        "check_in": str(b.check_in_date), "check_out": str(b.check_out_date),
        "total_price": b.total_price, "outstanding_balance": b.outstanding_balance,
        "status": b.status,
    } for b in bookings]


@app.put("/api/bookings/{booking_id}/move")
async def api_move_booking(booking_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    data = await request.json()
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if not b:
        raise HTTPException(status_code=404)
    new_room_id = int(data["room_id"])
    new_checkin = date.fromisoformat(data["check_in_date"])
    new_checkout = date.fromisoformat(data["check_out_date"])
    conflict = db.query(Booking).filter(
        Booking.id != booking_id,
        Booking.room_id == new_room_id,
        Booking.status.in_(["confirmed", "checked_in"]),
        Booking.check_in_date < new_checkout,
        Booking.check_out_date > new_checkin
    ).first()
    if conflict:
        guest = conflict.member.name if conflict.member else conflict.guest_name
        raise HTTPException(status_code=400, detail=f"ห้องนี้มีการจองของ {guest} ทับช่วงวันดังกล่าว")
    b.room_id = new_room_id
    b.check_in_date = new_checkin
    b.check_out_date = new_checkout
    b.num_nights = (new_checkout - new_checkin).days
    db.commit()
    return {"message": "ย้ายการจองเรียบร้อย"}


# ─────────────────────────────────────────────
#  Members
# ─────────────────────────────────────────────

@app.get("/members", response_class=HTMLResponse)
async def members_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    query = db.query(Member)
    if q:
        query = query.filter(or_(
            Member.name.contains(q), Member.phone.contains(q),
            Member.email.contains(q), Member.id_card.contains(q),
            Member.company_name.contains(q)
        ))
    members = query.order_by(Member.name).all()
    return render(request, "members.html", ctx(request, db, {
        "members": members, "search_q": q
    }))


@app.get("/api/members/search", response_class=JSONResponse)
async def api_search_members(request: Request, q: str = "", db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    members = db.query(Member).filter(or_(
        Member.name.contains(q), Member.phone.contains(q),
        Member.id_card.contains(q), Member.company_name.contains(q)
    )).limit(10).all()
    return [{"id": m.id, "name": m.name, "phone": m.phone,
             "company_name": m.company_name, "is_corporate": m.is_corporate,
             "total_stays": m.total_stays} for m in members]


@app.get("/api/members/{member_id}", response_class=JSONResponse)
async def api_get_member(member_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    m = db.query(Member).filter(Member.id == member_id).first()
    if not m:
        raise HTTPException(status_code=404)
    return {"id": m.id, "name": m.name, "phone": m.phone, "email": m.email,
            "id_card": m.id_card, "address": m.address, "company_name": m.company_name,
            "is_corporate": m.is_corporate, "notes": m.notes, "total_stays": m.total_stays}


@app.post("/api/members")
async def api_create_member(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    data = await request.json()
    m = Member(
        name=data["name"], phone=data.get("phone", ""), email=data.get("email", ""),
        id_card=data.get("id_card", ""), address=data.get("address", ""),
        company_name=data.get("company_name", ""),
        is_corporate=bool(data.get("is_corporate", False)),
        notes=data.get("notes", "")
    )
    db.add(m); db.commit(); db.refresh(m)
    return {"id": m.id, "message": "เพิ่มสมาชิกเรียบร้อย"}


@app.put("/api/members/{member_id}")
async def api_update_member(member_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    m = db.query(Member).filter(Member.id == member_id).first()
    if not m:
        raise HTTPException(status_code=404)
    data = await request.json()
    for field in ("name", "phone", "email", "id_card", "address", "company_name", "notes"):
        if field in data:
            setattr(m, field, data[field])
    if "is_corporate" in data:
        m.is_corporate = bool(data["is_corporate"])
    db.commit()
    return {"message": "อัปเดตสมาชิกเรียบร้อย"}


@app.get("/api/members/{member_id}/history", response_class=JSONResponse)
async def api_member_history(member_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    bookings = db.query(Booking).filter(Booking.member_id == member_id).order_by(Booking.check_in_date.desc()).all()
    return [{"id": b.id, "room": b.room.room_number, "check_in": str(b.check_in_date),
             "check_out": str(b.check_out_date), "total": b.total_price, "status": b.status}
            for b in bookings]


# ─────────────────────────────────────────────
#  Reports (Owner only)
# ─────────────────────────────────────────────

@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not has_permission(request, "view_reports", db):
        return RedirectResponse("/dashboard", status_code=302)
    return render(request, "reports.html", ctx(request, db))


@app.get("/api/reports/summary", response_class=JSONResponse)
async def api_report_summary(request: Request, date_from: str = None, date_to: str = None,
                              period: str = "month", db: Session = Depends(get_db)):
    require_permission(request, "view_reports", db)

    today = date.today()
    if period == "day":
        d_from = today if not date_from else date.fromisoformat(date_from)
        d_to = d_from
    elif period == "month":
        d_from = date(today.year, today.month, 1) if not date_from else date.fromisoformat(date_from)
        d_to = today if not date_to else date.fromisoformat(date_to)
    else:
        d_from = date.fromisoformat(date_from) if date_from else date(today.year, 1, 1)
        d_to = date.fromisoformat(date_to) if date_to else today

    income = db.query(func.sum(Payment.amount)).filter(
        Payment.payment_date >= d_from, Payment.payment_date <= d_to
    ).scalar() or 0

    expenses = db.query(func.sum(Expense.amount)).filter(
        Expense.expense_date >= d_from, Expense.expense_date <= d_to
    ).scalar() or 0

    bookings_count = db.query(func.count(Booking.id)).filter(
        Booking.check_in_date >= d_from, Booking.check_in_date <= d_to,
        Booking.status != "cancelled"
    ).scalar() or 0

    # Daily breakdown
    payments_detail = db.query(Payment).filter(
        Payment.payment_date >= d_from, Payment.payment_date <= d_to
    ).order_by(Payment.payment_date).all()

    daily = {}
    for p in payments_detail:
        k = str(p.payment_date)
        daily[k] = daily.get(k, 0) + p.amount

    expenses_detail = db.query(Expense).filter(
        Expense.expense_date >= d_from, Expense.expense_date <= d_to
    ).order_by(Expense.expense_date.desc()).all()

    return {
        "income": income, "expenses": expenses, "profit": income - expenses,
        "bookings_count": bookings_count,
        "date_from": str(d_from), "date_to": str(d_to),
        "daily_income": daily,
        "expenses_list": [{"id": e.id, "category": e.category, "amount": e.amount,
                            "description": e.description, "date": str(e.expense_date)}
                           for e in expenses_detail],
    }


@app.get("/expenses", response_class=HTMLResponse)
async def expenses_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not has_permission(request, "manage_expenses", db) and not has_permission(request, "record_expense", db):
        return RedirectResponse("/dashboard", status_code=302)
    today = date.today()
    today_expenses = db.query(Expense).filter(Expense.expense_date == today).order_by(Expense.created_at.desc()).all()
    can_manage = has_permission(request, "manage_expenses", db)
    return render(request, "expenses.html", ctx(request, db, {
        "today": today,
        "today_expenses": today_expenses,
        "can_manage": can_manage,
    }))


@app.post("/api/expenses")
async def api_create_expense(request: Request, db: Session = Depends(get_db)):
    if not has_permission(request, "manage_expenses", db) and not has_permission(request, "record_expense", db):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์บันทึกค่าใช้จ่าย")
    data = await request.json()
    user = get_current_user_from_cookie(request)
    e = Expense(
        category=data["category"], amount=float(data["amount"]),
        description=data.get("description", ""),
        expense_date=date.fromisoformat(data["expense_date"]),
        recorded_by_id=int(user["sub"])
    )
    db.add(e); db.commit()
    return {"message": "บันทึกค่าใช้จ่ายเรียบร้อย"}


@app.delete("/api/expenses/{expense_id}")
async def api_delete_expense(expense_id: int, request: Request, db: Session = Depends(get_db)):
    require_permission(request, "manage_expenses", db)
    e = db.query(Expense).filter(Expense.id == expense_id).first()
    if not e:
        raise HTTPException(status_code=404)
    db.delete(e); db.commit()
    return {"message": "ลบรายการเรียบร้อย"}


# ─────────────────────────────────────────────
#  Payroll (Owner only)
# ─────────────────────────────────────────────

@app.get("/payroll", response_class=HTMLResponse)
async def payroll_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    can_manage  = has_permission(request, "manage_payroll", db)
    can_record  = has_permission(request, "record_withdrawal", db)
    if not can_manage and not can_record:
        return RedirectResponse("/dashboard", status_code=302)
    is_owner = user.get("role") == "owner"
    staff = db.query(User).filter(User.is_active == True, User.role != "owner").all()
    today = date.today()
    return render(request, "payroll.html", ctx(request, db, {
        "staff": staff,
        "now_year": today.year,
        "now_month": today.month,
        "can_manage": can_manage,
        "can_record": can_record,
        "is_owner": is_owner,
        "self_user_id": int(user["sub"]),
        "self_full_name": user.get("full_name", ""),
    }))


@app.get("/api/payroll/withdrawals", response_class=JSONResponse)
async def api_withdrawals(request: Request, user_id: int = None,
                           year: int = None, month: int = None, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    can_manage = has_permission(request, "manage_payroll", db)
    can_record = has_permission(request, "record_withdrawal", db)
    if not can_manage and not can_record:
        raise HTTPException(status_code=403)
    today = date.today()
    y = year or today.year
    m = month or today.month
    q = db.query(Withdrawal).filter(
        extract("year", Withdrawal.date) == y,
        extract("month", Withdrawal.date) == m
    )
    if user_id:
        q = q.filter(Withdrawal.user_id == user_id)
    withdrawals = q.order_by(Withdrawal.date.desc()).all()
    # fetch recorder names in one pass
    recorder_ids = {w.approved_by_id for w in withdrawals if w.approved_by_id}
    recorders = {u.id: u.full_name for u in db.query(User).filter(User.id.in_(recorder_ids)).all()} if recorder_ids else {}
    return [{
        "id": w.id,
        "user_id": w.user_id,
        "user_name": w.user.full_name if w.user else "",
        "amount": w.amount,
        "date": str(w.date),
        "reason": w.reason,
        "recorded_by": recorders.get(w.approved_by_id, ""),
        "recorded_at": w.created_at.strftime("%d/%m/%Y %H:%M") if w.created_at else "",
    } for w in withdrawals]


@app.post("/api/payroll/withdrawals")
async def api_create_withdrawal(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    can_manage = has_permission(request, "manage_payroll", db)
    can_record = has_permission(request, "record_withdrawal", db)
    if not can_manage and not can_record:
        raise HTTPException(status_code=403)
    data = await request.json()
    target_user_id = int(data["user_id"])
    w = Withdrawal(
        user_id=target_user_id,
        amount=float(data["amount"]),
        date=date.fromisoformat(data["date"]),
        reason=data.get("reason", ""),
        approved_by_id=int(user["sub"]),
        created_at=datetime.now(),
    )
    db.add(w); db.commit()
    return {"message": "บันทึกการเบิกเงินเรียบร้อย"}


@app.delete("/api/payroll/withdrawals/{wid}")
async def api_delete_withdrawal(wid: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    # Only owner can delete withdrawals
    if user.get("role") != "owner":
        raise HTTPException(status_code=403, detail="เฉพาะเจ้าของเท่านั้นที่สามารถลบรายการเบิกเงิน")
    w = db.query(Withdrawal).filter(Withdrawal.id == wid).first()
    if not w:
        raise HTTPException(status_code=404)
    db.delete(w); db.commit()
    return {"message": "ลบรายการเรียบร้อย"}


@app.get("/api/payroll/summary", response_class=JSONResponse)
async def api_payroll_summary(request: Request, year: int = None, month: int = None,
                               db: Session = Depends(get_db)):
    require_permission(request, "manage_payroll", db)
    today = date.today()
    y = year or today.year
    m = month or today.month
    import calendar
    days_in_month = calendar.monthrange(y, m)[1]

    cfg = db.query(PayrollSettings).first()
    free_days        = cfg.free_absence_days if cfg else 4
    no_ab_bonus_amt  = cfg.no_absence_bonus  if cfg else 1000

    staff = db.query(User).filter(User.is_active == True, User.role != "owner").all()
    result = []
    for s in staff:
        total_withdraw = db.query(func.sum(Withdrawal.amount)).filter(
            Withdrawal.user_id == s.id,
            extract("year", Withdrawal.date) == y,
            extract("month", Withdrawal.date) == m
        ).scalar() or 0
        absence_count = db.query(func.count(Absence.id)).filter(
            Absence.user_id == s.id,
            extract("year", Absence.absence_date) == y,
            extract("month", Absence.absence_date) == m
        ).scalar() or 0
        wage_type  = getattr(s, "wage_type", "monthly") or "monthly"
        daily_rate = getattr(s, "daily_rate", 0) or 0

        effective_absences = max(0, absence_count - free_days)
        if wage_type == "daily":
            working_days = max(0, days_in_month - effective_absences)
            base_earned  = round(daily_rate * working_days, 2)
        else:
            working_days = None
            base_earned  = s.salary or 0

        no_ab_bonus = no_ab_bonus_amt if absence_count == 0 else 0

        pb = db.query(PayrollBonus).filter(
            PayrollBonus.user_id == s.id,
            PayrollBonus.year == y,
            PayrollBonus.month == m,
        ).first()
        special_bonus = pb.special_bonus if pb else 0

        total_earned = round(base_earned + no_ab_bonus + special_bonus, 2)
        result.append({
            "user_id": s.id, "full_name": s.full_name, "role": s.role,
            "wage_type": wage_type,
            "salary": s.salary,
            "daily_rate": daily_rate,
            "days_in_month": days_in_month,
            "absence_count": absence_count,
            "free_days": free_days,
            "effective_absences": effective_absences,
            "working_days": working_days,
            "base_earned": base_earned,
            "no_ab_bonus": no_ab_bonus,
            "special_bonus": special_bonus,
            "total_earned": total_earned,
            "total_withdrawals": round(total_withdraw, 2),
            "net_payable": round(total_earned - total_withdraw, 2),
        })
    return result


@app.get("/api/payroll/settings", response_class=JSONResponse)
async def api_get_payroll_settings(request: Request, db: Session = Depends(get_db)):
    require_permission(request, "manage_payroll", db)
    cfg = db.query(PayrollSettings).first()
    return {
        "no_absence_bonus": cfg.no_absence_bonus if cfg else 1000,
        "free_absence_days": cfg.free_absence_days if cfg else 4,
    }


@app.put("/api/payroll/settings", response_class=JSONResponse)
async def api_update_payroll_settings(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user or user.get("role") != "owner":
        raise HTTPException(status_code=403)
    data = await request.json()
    cfg = db.query(PayrollSettings).first()
    if not cfg:
        cfg = PayrollSettings()
        db.add(cfg)
    cfg.no_absence_bonus  = float(data.get("no_absence_bonus", cfg.no_absence_bonus or 1000))
    cfg.free_absence_days = int(data.get("free_absence_days", cfg.free_absence_days or 4))
    db.commit()
    return {"message": "บันทึกการตั้งค่าเรียบร้อย"}


@app.put("/api/payroll/special-bonus", response_class=JSONResponse)
async def api_set_special_bonus(request: Request, db: Session = Depends(get_db)):
    require_permission(request, "manage_payroll", db)
    data = await request.json()
    uid   = int(data["user_id"])
    y     = int(data["year"])
    m     = int(data["month"])
    amt   = float(data.get("special_bonus", 0))
    notes = data.get("notes", "")
    pb = db.query(PayrollBonus).filter(
        PayrollBonus.user_id == uid,
        PayrollBonus.year == y,
        PayrollBonus.month == m,
    ).first()
    if pb:
        pb.special_bonus = amt
        pb.notes = notes
    else:
        pb = PayrollBonus(user_id=uid, year=y, month=m, special_bonus=amt, notes=notes)
        db.add(pb)
    db.commit()
    return {"message": "บันทึกเงินพิเศษเรียบร้อย"}


# ── Absence (day-off) CRUD ──────────────────────────────────────────

@app.get("/api/payroll/absences", response_class=JSONResponse)
async def api_get_absences(request: Request, user_id: int = None,
                            year: int = None, month: int = None, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    can_manage = has_permission(request, "manage_payroll", db)
    can_record = has_permission(request, "record_withdrawal", db)
    if not can_manage and not can_record:
        raise HTTPException(status_code=403)
    today = date.today()
    y = year or today.year
    m = month or today.month
    q = db.query(Absence).filter(
        extract("year", Absence.absence_date) == y,
        extract("month", Absence.absence_date) == m,
    )
    if user_id:
        q = q.filter(Absence.user_id == user_id)
    rows = q.order_by(Absence.absence_date).all()
    recorder_ids = {r.recorded_by_id for r in rows if r.recorded_by_id}
    recorders = {u.id: u.full_name for u in db.query(User).filter(User.id.in_(recorder_ids)).all()} if recorder_ids else {}
    return [{
        "id": r.id,
        "user_id": r.user_id,
        "user_name": r.user.full_name if r.user else "",
        "absence_date": str(r.absence_date),
        "reason": r.reason,
        "recorded_by": recorders.get(r.recorded_by_id, ""),
        "recorded_at": r.created_at.strftime("%d/%m/%Y %H:%M") if r.created_at else "",
    } for r in rows]


@app.post("/api/payroll/absences")
async def api_create_absence(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    can_manage = has_permission(request, "manage_payroll", db)
    can_record = has_permission(request, "record_withdrawal", db)
    if not can_manage and not can_record:
        raise HTTPException(status_code=403)
    data = await request.json()
    a = Absence(
        user_id=int(data["user_id"]),
        absence_date=date.fromisoformat(data["absence_date"]),
        reason=data.get("reason", ""),
        recorded_by_id=int(user["sub"]),
        created_at=datetime.now(),
    )
    db.add(a); db.commit()
    return {"message": "บันทึกวันหยุดเรียบร้อย"}


@app.delete("/api/payroll/absences/{aid}")
async def api_delete_absence(aid: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    # Only owner or manager can delete absences
    if not has_permission(request, "manage_payroll", db):
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์ลบรายการวันหยุด")
    a = db.query(Absence).filter(Absence.id == aid).first()
    if not a:
        raise HTTPException(status_code=404)
    db.delete(a); db.commit()
    return {"message": "ลบวันหยุดเรียบร้อย"}


@app.put("/api/users/{user_id}/wage")
async def api_update_user_wage(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user or user.get("role") != "owner":
        raise HTTPException(status_code=403)
    data = await request.json()
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404)
    u.wage_type  = data.get("wage_type", u.wage_type)
    u.daily_rate = float(data.get("daily_rate", u.daily_rate or 0))
    u.salary     = float(data.get("salary", u.salary or 0))
    db.commit()
    return {"message": "อัปเดตค่าจ้างเรียบร้อย"}


# ─────────────────────────────────────────────
#  Users (Owner only)
# ─────────────────────────────────────────────

@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if not has_permission(request, "manage_users", db):
        return RedirectResponse("/dashboard", status_code=302)
    users = db.query(User).order_by(User.full_name).all()
    # Build permissions matrix for display/edit
    perm_matrix = {}
    for role in ("manager", "staff"):
        perm_matrix[role] = {k: False for k in FEATURE_KEYS}
        for p in db.query(RolePermission).filter(RolePermission.role == role).all():
            perm_matrix[role][p.feature] = bool(p.enabled)
    return render(request, "users.html", ctx(request, db, {
        "users": users,
        "features": FEATURES,
        "perm_matrix": perm_matrix,
    }))


@app.post("/api/users")
async def api_create_user(request: Request, db: Session = Depends(get_db)):
    require_permission(request, "manage_users", db)
    user = get_current_user_from_cookie(request)
    data = await request.json()
    if db.query(User).filter(User.username == data["username"]).first():
        raise HTTPException(status_code=400, detail="ชื่อผู้ใช้นี้มีอยู่แล้ว")
    u = User(
        username=data["username"],
        password_hash=get_password_hash(data["password"]),
        full_name=data["full_name"],
        role=data.get("role", "staff"),
        salary=float(data.get("salary", 0)),
        is_active=True
    )
    db.add(u); db.commit()
    return {"message": "สร้างผู้ใช้เรียบร้อย"}


@app.put("/api/users/{user_id}")
async def api_update_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_permission(request, "manage_users", db)
    user = get_current_user_from_cookie(request)
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404)
    data = await request.json()
    if "full_name" in data:
        u.full_name = data["full_name"]
    if "role" in data:
        u.role = data["role"]
    if "salary" in data:
        u.salary = float(data["salary"])
    if "is_active" in data:
        u.is_active = bool(data["is_active"])
    if "password" in data and data["password"]:
        u.password_hash = get_password_hash(data["password"])
    db.commit()
    return {"message": "อัปเดตผู้ใช้เรียบร้อย"}


# ─────────────────────────────────────────────
#  Settings & Invoice
# ─────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user.get("role") != "owner":
        return RedirectResponse("/dashboard", status_code=302)
    inv_setting = db.query(InvoiceSetting).first()
    return render(request, "settings.html", ctx(request, db, {
        "inv_setting": inv_setting
    }))


@app.post("/api/settings/invoice")
async def api_save_invoice_settings(request: Request, db: Session = Depends(get_db)):
    require_permission(request, "manage_invoice", db)
    user = get_current_user_from_cookie(request)
    data = await request.json()
    s = db.query(InvoiceSetting).first()
    if not s:
        s = InvoiceSetting()
        db.add(s)
    s.company_name = data.get("company_name", "")
    s.address = data.get("address", "")
    s.phone = data.get("phone", "")
    s.tax_id = data.get("tax_id", "")
    s.bank_info = data.get("bank_info", "")
    s.footer_notes = data.get("footer_notes", "")
    db.commit()
    return {"message": "บันทึกการตั้งค่าเรียบร้อย"}


@app.post("/api/settings/logo")
async def api_upload_logo(request: Request, file: UploadFile = File(...),
                           db: Session = Depends(get_db)):
    require_permission(request, "manage_invoice", db)
    user = get_current_user_from_cookie(request)
    content = await file.read()
    filename = f"logo_{datetime.now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
    logo_path = os.path.join(BASE_DIR, "uploads", "logos", filename)
    with open(logo_path, "wb") as f:
        f.write(content)
    s = db.query(InvoiceSetting).first()
    if not s:
        s = InvoiceSetting()
        db.add(s)
    s.logo_filename = filename
    db.commit()
    return {"message": "อัปโหลดโลโก้เรียบร้อย", "filename": filename}


# ─────────────────────────────────────────────
#  Permissions API (owner only)
# ─────────────────────────────────────────────

@app.get("/api/permissions")
async def api_get_permissions(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user or user.get("role") != "owner":
        raise HTTPException(status_code=403)
    result = {}
    for role in ("manager", "staff"):
        result[role] = {k: False for k in FEATURE_KEYS}
        for p in db.query(RolePermission).filter(RolePermission.role == role).all():
            result[role][p.feature] = bool(p.enabled)
    return {"permissions": result, "features": [{"key": k, "label": v} for k, v in FEATURES]}


@app.put("/api/permissions/{role}/{feature}")
async def api_update_permission(role: str, feature: str, request: Request,
                                 db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user or user.get("role") != "owner":
        raise HTTPException(status_code=403)
    if role not in ("manager", "staff") or feature not in FEATURE_KEYS:
        raise HTTPException(status_code=400, detail="ข้อมูลไม่ถูกต้อง")
    data = await request.json()
    enabled = bool(data.get("enabled", False))
    p = db.query(RolePermission).filter_by(role=role, feature=feature).first()
    if p:
        p.enabled = enabled
    else:
        db.add(RolePermission(role=role, feature=feature, enabled=enabled))
    db.commit()
    return {"message": "อัปเดตสิทธิ์เรียบร้อย"}


@app.get("/booking-confirm/{booking_id}", response_class=HTMLResponse)
async def booking_confirm_page(booking_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if not b:
        raise HTTPException(status_code=404)
    inv_setting = db.query(InvoiceSetting).first()
    extras = _parse_extras(b.extra_charges)
    return render(request, "booking_confirm_print.html", {
        "booking": b,
        "inv_setting": inv_setting,
        "today": date.today(),
        "current_user": user,
        "extras": extras,
        "room_subtotal": (b.room_price or 0) * (b.num_nights or 0),
    })


@app.get("/invoice/{booking_id}", response_class=HTMLResponse)
async def invoice_page(booking_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    b = db.query(Booking).filter(Booking.id == booking_id).first()
    if not b:
        raise HTTPException(status_code=404)
    inv_setting = db.query(InvoiceSetting).first()
    extras = _parse_extras(b.extra_charges)
    return render(request, "invoice_print.html", {
        "booking": b,
        "inv_setting": inv_setting,
        "invoice_number": f"INV-{b.id:05d}",
        "issue_date": date.today(),
        "current_user": user,
        "extras": extras,
        "room_subtotal": (b.room_price or 0) * (b.num_nights or 0),
    })


# ─────────────────────────────────────────────
#  Payments
# ─────────────────────────────────────────────

@app.post("/api/payments")
async def api_create_payment(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    data = await request.json()
    b = db.query(Booking).filter(Booking.id == data["booking_id"]).first()
    if not b:
        raise HTTPException(status_code=404)
    amount = float(data["amount"])
    if amount <= 0:
        raise HTTPException(status_code=400, detail="จำนวนเงินต้องมากกว่า 0")
    if amount > b.outstanding_balance:
        raise HTTPException(status_code=400, detail=f"จำนวนเงินเกินยอดค้าง (฿{b.outstanding_balance:,.0f})")
    p = Payment(
        booking_id=b.id, amount=amount,
        payment_type=data.get("payment_type", "cash"),
        payment_date=date.fromisoformat(data["payment_date"]),
        notes=data.get("notes", ""),
        recorded_by_id=int(user["sub"])
    )
    db.add(p)
    b.outstanding_balance = max(0, b.outstanding_balance - amount)
    db.commit()
    return {"message": "บันทึกการชำระเงินเรียบร้อย", "outstanding": b.outstanding_balance}


@app.get("/api/bookings/{booking_id}/payments", response_class=JSONResponse)
async def api_list_payments(booking_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    payments = db.query(Payment).filter(Payment.booking_id == booking_id).order_by(Payment.payment_date.desc(), Payment.id.desc()).all()
    return [{"id": p.id, "amount": p.amount, "payment_type": p.payment_type,
             "payment_date": str(p.payment_date), "notes": p.notes}
            for p in payments]


@app.delete("/api/payments/{payment_id}")
async def api_delete_payment(payment_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_from_cookie(request)
    if not user:
        raise HTTPException(status_code=401)
    p = db.query(Payment).filter(Payment.id == payment_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="ไม่พบรายการ")
    b = db.query(Booking).filter(Booking.id == p.booking_id).first()
    if b:
        # add the amount back to outstanding (capped at total)
        b.outstanding_balance = min(b.total_price, b.outstanding_balance + p.amount)
    db.delete(p)
    db.commit()
    return {"message": "ลบรายการชำระเงินเรียบร้อย",
            "outstanding": b.outstanding_balance if b else 0}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

