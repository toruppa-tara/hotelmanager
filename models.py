from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Date, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    role = Column(String(20), default="staff")  # owner | manager | staff
    salary = Column(Float, default=0)
    wage_type = Column(String(10), default="monthly")  # monthly | daily
    daily_rate = Column(Float, default=0)
    is_active = Column(Boolean, default=True)
    bank_account_number = Column(String(50), default="")
    bank_account_name = Column(String(100), default="")
    bank_qr_filename = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.now)

    bookings_as_staff = relationship("Booking", foreign_keys="Booking.staff_id", back_populates="staff")
    withdrawals = relationship("Withdrawal", foreign_keys="Withdrawal.user_id", back_populates="user")
    absences = relationship("Absence", foreign_keys="Absence.user_id", back_populates="user")


class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    room_number = Column(String(20), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    price_per_night = Column(Float, nullable=False, default=0)
    status = Column(String(20), default="available")  # available | maintenance
    description = Column(Text, default="")

    bookings = relationship("Booking", back_populates="room")


class Member(Base):
    __tablename__ = "members"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), default="")
    email = Column(String(100), default="")
    id_card = Column(String(20), default="")
    address = Column(Text, default="")
    company_name = Column(String(200), default="")
    is_corporate = Column(Boolean, default=False)
    notes = Column(Text, default="")
    total_stays = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)

    bookings = relationship("Booking", back_populates="member")


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=True)
    staff_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    guest_name = Column(String(100), default="")  # for walk-in guests without member account
    check_in_date = Column(Date, nullable=False)
    check_out_date = Column(Date, nullable=False)
    num_nights = Column(Integer, default=1)
    room_price = Column(Float, nullable=False)
    total_price = Column(Float, nullable=False)

    deposit_amount = Column(Float, default=0)
    deposit_type = Column(String(20), default="")  # transfer | cash
    deposit_date = Column(Date, nullable=True)
    outstanding_balance = Column(Float, default=0)

    status = Column(String(20), default="confirmed")  # confirmed | checked_in | checked_out | cancelled
    notes = Column(Text, default="")
    security_deposit = Column(Float, default=200)
    security_deposit_type = Column(String(50), default="cash")  # cash | id_card | none | other
    security_deposit_note = Column(String(200), default="")
    # JSON list: [{"name": "ที่นอนเสริม", "amount": 100}, ...]
    extra_charges = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.now)

    room = relationship("Room", back_populates="bookings")
    member = relationship("Member", back_populates="bookings")
    staff = relationship("User", foreign_keys=[staff_id], back_populates="bookings_as_staff")
    payments = relationship("Payment", back_populates="booking", cascade="all, delete-orphan")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    amount = Column(Float, nullable=False)
    payment_type = Column(String(20), default="cash")  # cash | transfer
    payment_date = Column(Date, nullable=False)
    notes = Column(Text, default="")
    recorded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    booking = relationship("Booking", back_populates="payments")


class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(100), nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(Text, default="")
    expense_date = Column(Date, nullable=False)
    recorded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class Withdrawal(Base):
    __tablename__ = "withdrawals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    date = Column(Date, nullable=False)
    reason = Column(Text, default="")
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("User", foreign_keys=[user_id], back_populates="withdrawals")


class InvoiceSetting(Base):
    __tablename__ = "invoice_settings"

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(200), default="")
    address = Column(Text, default="")
    phone = Column(String(50), default="")
    tax_id = Column(String(50), default="")
    bank_info = Column(Text, default="")
    logo_filename = Column(String(200), default="")
    footer_notes = Column(Text, default="")


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint('role', 'feature', name='uq_role_feature'),)

    id = Column(Integer, primary_key=True, index=True)
    role = Column(String(20), nullable=False, index=True)     # manager | staff
    feature = Column(String(50), nullable=False)              # view_reports / manage_payroll / ...
    enabled = Column(Boolean, default=False)


class Maintenance(Base):
    __tablename__ = "maintenances"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)   # inclusive
    note = Column(Text, default="")
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class Absence(Base):
    __tablename__ = "absences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    absence_date = Column(Date, nullable=False)
    reason = Column(Text, default="")
    recorded_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("User", foreign_keys=[user_id], back_populates="absences")


class PayrollSettings(Base):
    __tablename__ = "payroll_settings"

    id = Column(Integer, primary_key=True, index=True)
    no_absence_bonus = Column(Float, default=1000)   # bonus when 0 absences in month
    free_absence_days = Column(Integer, default=4)   # days not deducted before cut


class PayrollBonus(Base):
    __tablename__ = "payroll_bonuses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    special_bonus = Column(Float, default=0)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)


class PayrollPayment(Base):
    __tablename__ = "payroll_payments"
    __table_args__ = (UniqueConstraint('user_id', 'year', 'month', name='uq_payroll_payment'),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    year = Column(Integer, nullable=False)
    month = Column(Integer, nullable=False)
    amount = Column(Float, default=0)
    paid_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    paid_at = Column(DateTime, default=datetime.now)


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=True)
    member_id = Column(Integer, ForeignKey("members.id"), nullable=True)
    invoice_number = Column(String(50), unique=True, nullable=False)
    issue_date = Column(Date, nullable=False)
    items_json = Column(Text, default="[]")
    subtotal = Column(Float, default=0)
    tax_rate = Column(Float, default=0)
    tax_amount = Column(Float, default=0)
    total = Column(Float, default=0)
    is_corporate = Column(Boolean, default=False)
    customer_name = Column(String(200), default="")
    customer_address = Column(Text, default="")
    customer_tax_id = Column(String(50), default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now)
