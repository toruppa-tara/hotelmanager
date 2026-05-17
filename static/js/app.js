/* ─── Date Helpers ───────────────────────────────────── */

/** Convert Thai date string (dd/mm/yyyy or dd/mm/yy) to ISO yyyy-mm-dd */
function isoDate(thaiStr) {
  if (!thaiStr) return '';
  if (/^\d{4}-\d{2}-\d{2}$/.test(thaiStr)) return thaiStr; // already ISO
  const parts = thaiStr.split('/');
  if (parts.length !== 3) return thaiStr;
  let [d, m, y] = parts.map(Number);
  if (y > 2400) y -= 543; // BE → CE
  if (y < 100)  y += (y > 70 ? 1900 : 2000);
  return `${y}-${String(m).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
}

/** Format ISO date to Thai display (dd/mm/พ.ศ.) */
function thaiDate(isoStr) {
  if (!isoStr) return '';
  const [y, m, d] = isoStr.split('-').map(Number);
  return `${String(d).padStart(2,'0')}/${String(m).padStart(2,'0')}/${y + 543}`;
}

/** Add N days to ISO date string, return ISO */
function addDays(isoStr, n) {
  const d = new Date(isoStr);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Format Thai date from ISO for flatpickr display */
function formatDateTH(isoStr) {
  if (!isoStr) return '';
  const [y, m, d] = isoStr.split('-').map(Number);
  return `${String(d).padStart(2,'0')}/${String(m).padStart(2,'0')}/${y + 543}`;
}

/* ─── Toast ───────────────────────────────────────────── */
function showToast(message, type = 'success') {
  const container = document.getElementById('toastContainer');
  if (!container) { alert(message); return; }
  const color = type === 'success' ? '#0d6efd' : type === 'danger' ? '#dc3545' : '#0dcaf0';
  const id = 'toast_' + Date.now();
  container.insertAdjacentHTML('beforeend', `
    <div id="${id}" class="toast toast-custom show align-items-center border-0 text-white mb-2"
         style="background:${color}" role="alert">
      <div class="d-flex">
        <div class="toast-body">${message}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" onclick="document.getElementById('${id}').remove()"></button>
      </div>
    </div>`);
  setTimeout(() => document.getElementById(id)?.remove(), 3500);
}

/* ─── Flatpickr Init ──────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
  flatpickr('.datepick', {
    dateFormat: 'd/m/Y',
    locale: 'th',
    allowInput: true,
    onChange: function() { calcNights(); },
  });
});

/* ─── Booking Modal Logic ─────────────────────────────── */

let bookingModalInstance = null;
let paymentsChanged = false;   // flag: reload page on modal close to refresh calendar

function resetBookingModal() {
  paymentsChanged = false;
  ['bm_booking_id','bm_room_id','bm_member_id','bm_guest_name','bm_check_in',
   'bm_check_out','bm_num_nights','bm_room_price','bm_total_price',
   'bm_deposit_amount','bm_deposit_date','bm_notes'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  const sel = document.getElementById('bm_room_select');
  if (sel) sel.value = '';
  const dType = document.getElementById('bm_deposit_type');
  if (dType) dType.value = '';
  const status = document.getElementById('bm_status');
  if (status) status.value = 'confirmed';
  const outstanding = document.getElementById('bm_outstanding');
  if (outstanding) outstanding.value = '';
  // Reset security deposit fields
  const r = document.getElementById('sec_r_cash');
  if (r) r.checked = true;
  const secDeposit = document.getElementById('bm_sec_deposit');
  if (secDeposit) secDeposit.value = 200;
  const secNote = document.getElementById('bm_sec_note');
  if (secNote) secNote.value = '';
  onSecTypeChange();
  clearExtraCharges();
  // Clear member search text (was retaining previous guest's name)
  const memberSearch = document.getElementById('bm_member_search');
  if (memberSearch) memberSearch.value = '';
  document.getElementById('bm_member_info').innerHTML = '';
  document.getElementById('memberSearchResults').style.display = 'none';
  // Default staff = current logged-in user
  const staffSel = document.getElementById('bm_staff_id');
  if (staffSel && window.CURRENT_USER && window.CURRENT_USER.id) {
    staffSel.value = String(window.CURRENT_USER.id);
  }
  // Clear inline-invalid state on guest_name (from prior submit attempts)
  const gn = document.getElementById('bm_guest_name');
  if (gn) gn.classList.remove('is-invalid');
  document.getElementById('paymentSection').style.display = 'none';
  document.getElementById('btnCancelBooking').style.display = 'none';
  document.getElementById('btnViewInvoice').style.display = 'none';
  const confirmBtn = document.getElementById('btnViewConfirm');
  if (confirmBtn) confirmBtn.style.display = 'none';
}

function onSecTypeChange() {
  // Read from radio group, sync to hidden field
  const checked = document.querySelector('input[name="sec_type_radio"]:checked');
  const type = checked ? checked.value : 'cash';
  const hidden = document.getElementById('bm_sec_type');
  if (hidden) hidden.value = type;

  const amtCol  = document.getElementById('sec_amount_col');
  const noteCol = document.getElementById('sec_note_col');
  if (!amtCol || !noteCol) return;

  amtCol.style.display  = type === 'cash'  ? '' : 'none';
  noteCol.style.display = type === 'other' ? '' : 'none';
}

function calcNights() {
  const ci = isoDate(document.getElementById('bm_check_in')?.value);
  const co = isoDate(document.getElementById('bm_check_out')?.value);
  if (!ci || !co) return;
  const nights = Math.round((new Date(co) - new Date(ci)) / 86400000);
  if (nights > 0) {
    document.getElementById('bm_num_nights').value = nights;
    calcTotal();
  }
}

function calcTotal() {
  const price = parseFloat(document.getElementById('bm_room_price')?.value) || 0;
  const nights = parseInt(document.getElementById('bm_num_nights')?.value) || 0;
  const extras = getExtraChargesTotal();
  const total = (price * nights) + extras;
  document.getElementById('bm_total_price').value = total;
  calcOutstanding();
}

function calcOutstanding() {
  const total = parseFloat(document.getElementById('bm_total_price')?.value) || 0;
  const deposit = parseFloat(document.getElementById('bm_deposit_amount')?.value) || 0;
  document.getElementById('bm_outstanding').value = Math.max(0, total - deposit);
}

// ── Extra Charges helpers ────────────────────────────────────────────
function getExtraCharges() {
  const rows = document.querySelectorAll('#extraChargesBody .extra-row');
  const items = [];
  rows.forEach(r => {
    const name = r.querySelector('.extra-name').value.trim();
    const amount = parseFloat(r.querySelector('.extra-amount').value) || 0;
    if (name && amount > 0) items.push({ name, amount });
  });
  return items;
}

function getExtraChargesTotal() {
  return getExtraCharges().reduce((sum, x) => sum + x.amount, 0);
}

function updateExtraChargesTotal() {
  const total = getExtraChargesTotal();
  const badge = document.getElementById('extraChargesTotal');
  if (badge) badge.textContent = '฿' + total.toLocaleString();
  calcTotal();
}

function addExtraChargeRow(name = '', amount = '') {
  const body = document.getElementById('extraChargesBody');
  if (!body) return;
  const row = document.createElement('div');
  row.className = 'extra-row d-flex gap-2 mb-1 align-items-center';
  row.innerHTML = `
    <input type="text" class="form-control form-control-sm extra-name" placeholder="ชื่อรายการ เช่น ที่นอนเสริม" value="${name}" oninput="updateExtraChargesTotal()">
    <div class="input-group input-group-sm" style="width:160px">
      <span class="input-group-text">฿</span>
      <input type="number" class="form-control extra-amount" placeholder="0" min="0" step="1" value="${amount}" oninput="updateExtraChargesTotal()">
    </div>
    <button type="button" class="btn btn-sm btn-outline-danger" onclick="this.parentElement.remove(); updateExtraChargesTotal();" title="ลบรายการ">
      <i class="bi bi-x-lg"></i>
    </button>`;
  body.appendChild(row);
}

function clearExtraCharges() {
  const body = document.getElementById('extraChargesBody');
  if (body) body.innerHTML = '';
  const badge = document.getElementById('extraChargesTotal');
  if (badge) badge.textContent = '฿0';
}

async function openBookingDetail(bookingId) {
  resetBookingModal();
  document.getElementById('bookingModalTitle').innerHTML = `<i class="bi bi-calendar-check me-2"></i>รายละเอียดการจอง #${bookingId}`;

  const res = await fetch(`/api/bookings/${bookingId}`);
  if (!res.ok) { showToast('ไม่พบข้อมูลการจอง', 'danger'); return; }
  const b = await res.json();

  document.getElementById('bm_booking_id').value = b.id;
  document.getElementById('bm_room_id').value = b.room_id;
  document.getElementById('bm_room_select').value = b.room_id;
  document.getElementById('bm_check_in').value = formatDateTH(b.check_in_date);
  document.getElementById('bm_check_out').value = formatDateTH(b.check_out_date);
  document.getElementById('bm_num_nights').value = b.num_nights;
  document.getElementById('bm_room_price').value = b.room_price;
  document.getElementById('bm_total_price').value = b.total_price;
  document.getElementById('bm_deposit_amount').value = b.deposit_amount;
  document.getElementById('bm_deposit_type').value = b.deposit_type;
  document.getElementById('bm_deposit_date').value = b.deposit_date ? formatDateTH(b.deposit_date) : '';
  document.getElementById('bm_outstanding').value = b.outstanding_balance;
  document.getElementById('bm_status').value = b.status;
  document.getElementById('bm_notes').value = b.notes;
  document.getElementById('bm_guest_name').value = b.guest_name;

  if (b.member_id) {
    document.getElementById('bm_member_id').value = b.member_id;
    // If guest_name is empty but the booking has a member, show the member's name in the guest field
    if (!b.guest_name) document.getElementById('bm_guest_name').value = b.member_name || '';
    document.getElementById('bm_member_info').innerHTML =
      `<span class="badge bg-success"><i class="bi bi-person-check me-1"></i>สมาชิก: ${b.member_name}</span>`;
  }
  if (b.staff_id) {
    const staffSel = document.getElementById('bm_staff_id');
    if (staffSel) staffSel.value = b.staff_id;
  }

  // Populate security deposit fields — set radio button
  const secVal = b.security_deposit_type || 'cash';
  const radioToCheck = document.querySelector(`input[name="sec_type_radio"][value="${secVal}"]`);
  if (radioToCheck) radioToCheck.checked = true;
  const secDeposit = document.getElementById('bm_sec_deposit');
  if (secDeposit) secDeposit.value = b.security_deposit ?? 200;
  const secNote = document.getElementById('bm_sec_note');
  if (secNote) secNote.value = b.security_deposit_note || '';
  onSecTypeChange();

  // Populate extra charges from server (b.extra_charges is an array)
  clearExtraCharges();
  if (Array.isArray(b.extra_charges)) {
    b.extra_charges.forEach(x => addExtraChargeRow(x.name, x.amount));
  }
  updateExtraChargesTotal();

  document.getElementById('paymentSection').style.display = '';
  document.getElementById('pay_date').value = formatDateTH(new Date().toISOString().slice(0,10));
  document.getElementById('btnCancelBooking').style.display = b.status !== 'cancelled' ? '' : 'none';
  const extendBtn = document.getElementById('btnExtendStay');
  if (extendBtn) extendBtn.style.display = b.status !== 'cancelled' && b.status !== 'checked_out' ? '' : 'none';
  const confirmBtn = document.getElementById('btnViewConfirm');
  if (confirmBtn) { confirmBtn.style.display = ''; confirmBtn.href = `/booking-confirm/${b.id}`; }
  const invBtn = document.getElementById('btnViewInvoice');
  invBtn.style.display = '';
  invBtn.href = `/invoice/${b.id}`;

  // Load existing payments for this booking
  await loadPayments(b.id);
  updatePaidBadge(b.outstanding_balance);

  if (!bookingModalInstance) {
    bookingModalInstance = new bootstrap.Modal(document.getElementById('bookingModal'));
  }
  bookingModalInstance.show();
}

async function saveBooking() {
  try {
    const bookingId = document.getElementById('bm_booking_id').value;
    const body = {
      room_id: document.getElementById('bm_room_id').value || document.getElementById('bm_room_select').value,
      member_id: document.getElementById('bm_member_id').value || null,
      staff_id: document.getElementById('bm_staff_id')?.value || null,
      guest_name: document.getElementById('bm_guest_name').value,
      check_in_date: isoDate(document.getElementById('bm_check_in').value),
      check_out_date: isoDate(document.getElementById('bm_check_out').value),
      room_price: document.getElementById('bm_room_price').value,
      deposit_amount: document.getElementById('bm_deposit_amount').value || 0,
      deposit_type: document.getElementById('bm_deposit_type').value,
      deposit_date: isoDate(document.getElementById('bm_deposit_date').value),
      outstanding_balance: document.getElementById('bm_outstanding').value || 0,
      status: document.getElementById('bm_status').value,
      notes: document.getElementById('bm_notes').value,
      security_deposit: parseFloat(document.getElementById('bm_sec_deposit')?.value) || 0,
      security_deposit_type: document.getElementById('bm_sec_type')?.value || 'cash',
      security_deposit_note: document.getElementById('bm_sec_note')?.value || '',
      extra_charges: getExtraCharges(),
    };

    if (!body.room_id) { showToast('กรุณาเลือกห้องพัก', 'danger'); return; }
    if (!body.check_in_date || !body.check_out_date) { showToast('กรุณาระบุวันเช็คอิน/เช็คเอาต์', 'danger'); return; }
    if (!body.member_id && !body.guest_name.trim()) {
      showToast('กรุณาระบุชื่อผู้เข้าพัก หรือเลือกสมาชิก', 'danger');
      document.getElementById('bm_guest_name').classList.add('is-invalid');
      return;
    }
    document.getElementById('bm_guest_name').classList.remove('is-invalid');

    const url = bookingId ? `/api/bookings/${bookingId}` : '/api/bookings';
    const method = bookingId ? 'PUT' : 'POST';
    const res = await fetch(url, { method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    const data = await res.json();

    if (res.ok) {
      showToast(data.message || 'บันทึกเรียบร้อย');
      bootstrap.Modal.getInstance(document.getElementById('bookingModal'))?.hide();
      setTimeout(() => location.reload(), 600);
    } else {
      showToast(data.detail || 'เกิดข้อผิดพลาด', 'danger');
    }
  } catch (err) {
    showToast('เกิดข้อผิดพลาด: ' + err.message, 'danger');
  }
}

function openExtendModal() {
  const bookingId = document.getElementById('bm_booking_id').value;
  if (!bookingId) return;
  document.getElementById('extend_nights').value = 1;
  calcExtendCost();
  new bootstrap.Modal(document.getElementById('extendModal')).show();
}

function calcExtendCost() {
  const nights = parseInt(document.getElementById('extend_nights').value) || 0;
  const pricePerNight = parseFloat(document.getElementById('bm_room_price').value) || 0;
  const currentCheckout = isoDate(document.getElementById('bm_check_out').value);
  if (!currentCheckout || nights <= 0) return;
  const newCheckout = addDays(currentCheckout, nights);
  document.getElementById('extend_new_checkout').textContent = formatDateTH(newCheckout);
  document.getElementById('extend_price_per_night').textContent = `฿${pricePerNight.toLocaleString()}`;
  document.getElementById('extend_extra_cost').textContent = `฿${(nights * pricePerNight).toLocaleString()}`;
}

async function saveExtend() {
  const nights = parseInt(document.getElementById('extend_nights').value) || 0;
  if (nights <= 0) { showToast('กรุณาระบุจำนวนคืน', 'danger'); return; }

  const newCheckIn  = isoDate(document.getElementById('bm_check_out').value);
  const newCheckOut = addDays(newCheckIn, nights);

  const body = {
    room_id:        document.getElementById('bm_room_select').value,
    member_id:      document.getElementById('bm_member_id').value || null,
    guest_name:     document.getElementById('bm_guest_name').value,
    staff_id:       document.getElementById('bm_staff_id')?.value || null,
    check_in_date:  newCheckIn,
    check_out_date: newCheckOut,
    room_price:     document.getElementById('bm_room_price').value,
    deposit_amount: 0,
    status:         'confirmed',
    notes:          'พักต่อจากการจองเดิม',
  };

  if (!body.room_id) { showToast('ไม่พบข้อมูลห้องพัก', 'danger'); return; }

  const res = await fetch('/api/bookings', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  const data = await res.json();
  if (res.ok) {
    showToast('สร้างการจองพักต่อเรียบร้อย');
    bootstrap.Modal.getInstance(document.getElementById('extendModal'))?.hide();
    bootstrap.Modal.getInstance(document.getElementById('bookingModal'))?.hide();
    setTimeout(() => location.reload(), 600);
  } else {
    showToast(data.detail || 'เกิดข้อผิดพลาด', 'danger');
  }
}

async function quickStatus(newStatus, confirmMsg) {
  document.getElementById('bm_status').value = newStatus;
  await saveBooking();
}

async function cancelBooking() {
  const bookingId = document.getElementById('bm_booking_id').value;
  if (!bookingId) return;
  // Show inline confirm row instead of native confirm() which browsers may block
  const row = document.getElementById('cancelConfirmRow');
  if (row) { row.style.display = row.style.display === 'none' ? '' : 'none'; return; }
}

async function doCancelBooking() {
  const bookingId = document.getElementById('bm_booking_id').value;
  if (!bookingId) return;
  try {
    const res = await fetch(`/api/bookings/${bookingId}`, { method: 'DELETE' });
    const data = await res.json();
    showToast(data.message);
    bootstrap.Modal.getInstance(document.getElementById('bookingModal'))?.hide();
    setTimeout(() => location.reload(), 600);
  } catch (err) {
    showToast('เกิดข้อผิดพลาด: ' + err.message, 'danger');
  }
}

function updatePaidBadge(outstanding) {
  const out = parseFloat(outstanding) || 0;
  const headerEl = document.getElementById('bookingModalTitle');
  if (!headerEl) return;
  // Remove any existing paid badge
  const old = document.getElementById('paidStatusBadge');
  if (old) old.remove();

  let html = '';
  if (out <= 0) {
    html = '<span id="paidStatusBadge" class="badge bg-success ms-2"><i class="bi bi-check-circle-fill me-1"></i>ชำระครบแล้ว</span>';
  } else {
    html = `<span id="paidStatusBadge" class="badge bg-danger ms-2"><i class="bi bi-exclamation-circle me-1"></i>ค้าง ฿${out.toLocaleString()}</span>`;
  }
  headerEl.insertAdjacentHTML('beforeend', html);
}

async function loadPayments(bookingId) {
  const container = document.getElementById('paymentsList');
  if (!container) return;
  const res = await fetch(`/api/bookings/${bookingId}/payments`);
  const items = await res.json();
  if (!items.length) {
    container.innerHTML = '<div class="text-muted small text-center py-2">ยังไม่มีรายการชำระ</div>';
    return;
  }
  let total = 0;
  container.innerHTML = `
    <div class="table-responsive">
      <table class="table table-sm table-bordered mb-1" style="font-size:0.85rem">
        <thead class="table-light">
          <tr><th style="width:40px">#</th><th>วันที่</th><th>ประเภท</th><th class="text-end">จำนวน</th><th style="width:50px"></th></tr>
        </thead>
        <tbody>
          ${items.map((p, i) => { total += p.amount; return `
            <tr>
              <td class="text-muted">${i+1}</td>
              <td>${p.payment_date}</td>
              <td>${p.payment_type === 'transfer' ? '<span class="badge bg-info text-dark">โอน</span>' : '<span class="badge bg-secondary">สด</span>'}</td>
              <td class="text-end fw-semibold text-success">฿${Number(p.amount).toLocaleString()}</td>
              <td class="text-center">
                <button class="btn btn-xs btn-outline-danger" title="ลบรายการนี้" onclick="deletePayment(${p.id})">
                  <i class="bi bi-trash"></i>
                </button>
              </td>
            </tr>`; }).join('')}
        </tbody>
        <tfoot class="table-light">
          <tr class="fw-bold"><td colspan="3" class="text-end">รวมชำระแล้ว</td><td class="text-end text-success">฿${total.toLocaleString()}</td><td></td></tr>
        </tfoot>
      </table>
    </div>`;
}

async function addPayment() {
  const bookingId = document.getElementById('bm_booking_id').value;
  if (!bookingId) return;
  const btn = document.getElementById('btnAddPayment');
  if (btn.disabled) return;       // prevent double-submit
  const amount = parseFloat(document.getElementById('pay_amount').value) || 0;
  if (!amount) { showToast('กรุณาระบุจำนวนเงิน', 'danger'); return; }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>กำลังบันทึก...';

  try {
    const res = await fetch('/api/payments', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        booking_id: parseInt(bookingId), amount,
        payment_type: document.getElementById('pay_type').value,
        payment_date: isoDate(document.getElementById('pay_date').value),
      })
    });
    const data = await res.json();
    if (!res.ok) { showToast(data.detail || 'เกิดข้อผิดพลาด', 'danger'); return; }

    const newOutstanding = parseFloat(data.outstanding ?? 0);
    document.getElementById('bm_outstanding').value = newOutstanding;
    document.getElementById('pay_amount').value = '';
    paymentsChanged = true;
    await loadPayments(bookingId);
    updatePaidBadge(newOutstanding);

    if (newOutstanding <= 0) {
      // Fully paid — green badge, then auto-reload to update calendar cell colour
      showToast('🎉 ชำระเงินครบแล้ว — กำลังรีเฟรชหน้า...');
      setTimeout(() => location.reload(), 1300);
    } else {
      showToast(`${data.message || 'บันทึกการชำระเงินเรียบร้อย'} (คงเหลือ ฿${newOutstanding.toLocaleString()})`);
    }
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-plus-circle me-1"></i>บันทึก';
  }
}

async function quickCheckout(bookingId) {
  if (!confirm('ยืนยันการเช็คเอาต์? (ยืนยันว่าคืนเงินประกัน/บัตรให้ลูกค้าแล้ว)')) return;
  try {
    const res = await fetch(`/api/bookings/${bookingId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'checked_out' })
    });
    const data = await res.json();
    if (res.ok) {
      showToast('เช็คเอาต์เรียบร้อย');
      const row = document.getElementById(`checkout-row-${bookingId}`);
      if (row) row.remove();
      const list = document.getElementById('checkoutList');
      if (list && !list.querySelector('[id^="checkout-row-"]')) {
        list.innerHTML = '<div class="text-muted small text-center py-1">ไม่มีรายการเช็คเอาต์</div>';
      }
      setTimeout(() => location.reload(), 1200);
    } else {
      showToast(data.detail || 'เกิดข้อผิดพลาด', 'danger');
    }
  } catch (err) {
    showToast('เกิดข้อผิดพลาด: ' + err.message, 'danger');
  }
}

async function deletePayment(paymentId) {
  if (!confirm('ลบรายการชำระเงินนี้? ยอดค้างชำระจะถูกปรับเพิ่มกลับ')) return;
  const bookingId = document.getElementById('bm_booking_id').value;
  const res = await fetch(`/api/payments/${paymentId}`, { method: 'DELETE' });
  const data = await res.json();
  if (!res.ok) { showToast(data.detail || 'ลบไม่สำเร็จ', 'danger'); return; }
  showToast(data.message);
  document.getElementById('bm_outstanding').value = data.outstanding || 0;
  paymentsChanged = true;
  if (bookingId) await loadPayments(bookingId);
  updatePaidBadge(data.outstanding);
}

// When booking modal closes after any payment was made, reload page so calendar grid + tooltips refresh
document.addEventListener('DOMContentLoaded', () => {
  const modal = document.getElementById('bookingModal');
  if (modal) {
    modal.addEventListener('hidden.bs.modal', () => {
      if (paymentsChanged) location.reload();
    });
  }
});

/* ─── Member Search Autocomplete ─────────────────────── */

// ─── Auto-search members as user types in the guest name field ────────
let _memberSearchTimer = null;
async function autoSearchMember() {
  // If user starts editing, clear any previously-attached member_id
  clearMember();
  const input = document.getElementById('bm_guest_name');
  const q = input.value.trim();
  const container = document.getElementById('memberSearchResults');
  clearTimeout(_memberSearchTimer);
  if (q.length < 2) { container.style.display = 'none'; return; }
  _memberSearchTimer = setTimeout(async () => {
    const res = await fetch(`/api/members/search?q=${encodeURIComponent(q)}`);
    const members = await res.json();
    if (!members.length) { container.style.display = 'none'; return; }
    container.innerHTML = members.map(m => `
      <a href="#" class="list-group-item list-group-item-action py-1 px-2 small" onclick="selectMember(${m.id},'${(m.name||'').replace(/'/g,"\\'")}','${(m.company_name||'').replace(/'/g,"\\'")}',${m.is_corporate});return false;">
        <strong>${m.is_corporate ? (m.company_name || m.name) : m.name}</strong>
        ${m.phone ? `<span class="text-muted ms-2">${m.phone}</span>` : ''}
        ${m.is_corporate ? `<span class="badge bg-primary ms-1">นิติบุคคล</span>` : ''}
        <span class="badge bg-info text-dark ms-1">${m.total_stays} ครั้ง</span>
      </a>`).join('');
    container.style.display = '';
  }, 250);
}

function selectMember(id, name, companyName, isCorp) {
  const displayName = isCorp ? (companyName || name) : name;
  document.getElementById('bm_member_id').value = id;
  document.getElementById('bm_guest_name').value = displayName;
  document.getElementById('bm_member_info').innerHTML =
    `<span class="badge bg-success"><i class="bi bi-person-check me-1"></i>สมาชิก #${id}</span>
     <button type="button" class="btn btn-sm btn-link text-danger p-0 ms-1" onclick="clearMember();return false;" title="ยกเลิกการเลือก">✕</button>`;
  document.getElementById('memberSearchResults').style.display = 'none';
}

function clearMember() {
  document.getElementById('bm_member_id').value = '';
  document.getElementById('bm_member_info').innerHTML = '';
}

// Hide search results when clicking outside
document.addEventListener('click', e => {
  if (!e.target.closest('#bm_guest_name') && !e.target.closest('#memberSearchResults')) {
    const el = document.getElementById('memberSearchResults');
    if (el) el.style.display = 'none';
  }
});

/* ─── Inline Add Member (from booking guest field) ─────── */
function onNewMemberTypeChange() {
  const isCorp = document.querySelector('input[name="nm_type_radio"]:checked')?.value === 'true';
  document.getElementById('nm_is_corporate').value = isCorp ? 'true' : 'false';
  document.querySelectorAll('.nm-person-field').forEach(el => el.style.display = isCorp ? 'none' : '');
  document.querySelectorAll('.nm-corp-field').forEach(el => el.style.display = isCorp ? '' : 'none');
}

function openAddMemberInline() {
  // Clear all fields
  ['nm_name','nm_phone','nm_id_card','nm_id_card_corp','nm_company','nm_contact_name','nm_address'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  // Pre-fill name from the booking guest_name field if any
  const guest = document.getElementById('bm_guest_name')?.value.trim();
  if (guest) document.getElementById('nm_name').value = guest;
  // Default to บุคคลธรรมดา
  document.getElementById('nm_type_person').checked = true;
  onNewMemberTypeChange();
  new bootstrap.Modal(document.getElementById('newMemberModal')).show();
}

async function saveNewMember() {
  const isCorp = document.getElementById('nm_is_corporate').value === 'true';
  const name = document.getElementById('nm_name').value.trim();
  const company = document.getElementById('nm_company').value.trim();
  const contactName = document.getElementById('nm_contact_name').value.trim();

  // Validation per type
  if (isCorp && !company) { showToast('กรุณากรอกชื่อบริษัท', 'danger'); return; }
  if (!isCorp && !name)   { showToast('กรุณากรอกชื่อ-นามสกุล', 'danger'); return; }

  // For corporate: member.name = contact (occupant) name, falls back to company if not provided
  const memberName = isCorp ? (contactName || company) : name;

  const body = {
    name: memberName,
    phone: document.getElementById('nm_phone').value,
    email: '',
    id_card: isCorp
      ? document.getElementById('nm_id_card_corp').value
      : document.getElementById('nm_id_card').value,
    company_name: company,
    address: document.getElementById('nm_address').value,
    is_corporate: isCorp,
  };

  const res = await fetch('/api/members', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body)
  });
  const data = await res.json();
  if (!res.ok) { showToast(data.detail || 'เพิ่มสมาชิกไม่สำเร็จ', 'danger'); return; }
  showToast(data.message || 'เพิ่มสมาชิกเรียบร้อย');
  selectMember(data.id, body.name, company, isCorp);
  bootstrap.Modal.getInstance(document.getElementById('newMemberModal'))?.hide();
}
