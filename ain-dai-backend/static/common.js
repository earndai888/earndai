/* เอิ้นได้ — helper กลางของหน้าลูกค้าและหน้าช่าง
   auth: เปิดผ่าน LIFF → ล็อกอิน LINE จริงอัตโนมัติ
         โหมด dev (DEV_MODE=true) → ใช้ debug user ทดสอบได้ (?user=Uxxxx) */

const DEBUG_KEY = "aindai_debug_user";
let META = null;
const AUTH = { mode: "debug", debugUser: null, idToken: null };

const STATUS_TH = {
  bidding: "รอข้อเสนอ", assigned: "จ่ายแล้ว รอช่างเริ่มงาน", in_progress: "ช่างกำลังทำงาน",
  done: "รอตรวจงาน", confirmed: "จบงานแล้ว", settled: "โอนเงินช่างแล้ว",
  cancelled: "ยกเลิก", expired: "หมดอายุ", disputed: "มีข้อพิพาท",
};

function esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
function fmt(x) { return (+x).toLocaleString("th-TH", { maximumFractionDigits: 0 }); }

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src; s.onload = resolve; s.onerror = reject;
    document.head.appendChild(s);
  });
}

function liffConfigured() {
  // LIFF id จริงรูปแบบ 1234567890-AbCdEfGh (ตัด placeholder เลขศูนย์ทิ้ง)
  const id = META && META.liff_id || "";
  return /^\d{9,}-\w+$/.test(id) && !id.startsWith("0000000000");
}

/* คืน true = auth พร้อมใช้งาน, false = กำลัง redirect ไปล็อกอิน/ใช้ไม่ได้ */
async function initAuth(defaultDebugUser) {
  META = await (await fetch("/api/meta")).json();

  const q = new URLSearchParams(location.search);
  if (q.get("user")) localStorage.setItem(DEBUG_KEY, q.get("user"));
  const savedDebug = localStorage.getItem(DEBUG_KEY);

  // dev mode + มี debug user → ใช้โหมดทดสอบ (ข้าม LIFF)
  if (META.dev_mode && (savedDebug || !liffConfigured())) {
    AUTH.mode = "debug";
    AUTH.debugUser = savedDebug || defaultDebugUser;
    showDebugBadge();
    return true;
  }

  if (liffConfigured()) {
    try {
      await loadScript("https://static.line-scdn.net/liff/edge/2/sdk.js");
      await liff.init({ liffId: META.liff_id });
      if (!liff.isLoggedIn()) { liff.login({ redirectUri: location.href }); return false; }
      AUTH.mode = "liff";
      AUTH.idToken = liff.getIDToken();
      return true;
    } catch (e) {
      console.error("LIFF init ล้มเหลว", e);
      if (META.dev_mode) {
        AUTH.mode = "debug"; AUTH.debugUser = savedDebug || defaultDebugUser;
        showDebugBadge();
        return true;
      }
      alert("เชื่อมต่อ LINE ไม่สำเร็จ ลองเปิดผ่านแอป LINE อีกครั้งครับ");
      return false;
    }
  }

  alert("ระบบยังไม่ได้ตั้งค่าการล็อกอิน (LIFF_ID)");
  return false;
}

function showDebugBadge() {
  const el = document.getElementById("debugbadge");
  if (!el) return;
  el.textContent = "🧪 " + AUTH.debugUser;
  el.style.display = "block";
  el.onclick = () => {
    const u = prompt("โหมดทดสอบ: สวมเป็นผู้ใช้ id ไหน?", AUTH.debugUser);
    if (u) { localStorage.setItem(DEBUG_KEY, u.trim()); location.reload(); }
  };
}

function authHeaders() {
  return AUTH.mode === "liff"
    ? { Authorization: "Bearer " + AUTH.idToken }
    : { "X-Debug-User": AUTH.debugUser };
}

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch("/api" + path, {
    method,
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && AUTH.mode === "liff") {
    liff.login({ redirectUri: location.href }); // token หมดอายุ → ล็อกอินใหม่
    throw new Error("token หมดอายุ กำลังล็อกอินใหม่…");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || res.status));
  return data;
}

async function uploadFile(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/uploads", { method: "POST", headers: authHeaders(), body: fd });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "อัปโหลดไม่สำเร็จ");
  return data.url;
}

function go(id) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("on"));
  const el = document.getElementById(id);
  if (el) el.classList.add("on");
  window.scrollTo(0, 0);
}
