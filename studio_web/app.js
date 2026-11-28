/* VoidFeed Studio v3.1 — fixed & hardened
   - Prevents black screen (safe DOM + deferred init)
   - Proper i18n for calendar
   - Social networks with real char limits
   - Startup animation
   - Better error handling
*/
"use strict";

const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
const params = new URLSearchParams(location.search);
const DEMO = params.has("demo");

let AUTH = "";
if (tg && tg.initData) {
  try {
    tg.ready();
    tg.expand();
    AUTH = "tma " + tg.initData;
    try { tg.setHeaderColor("#0e1621"); tg.setBackgroundColor("#17212b"); } catch (e) {}
  } catch (e) {
    console.error("Telegram init error", e);
  }
} else if (DEMO) {
  AUTH = "demo";
}

// Safe DOM helper — never throws
const $ = (id) => {
  try { return document.getElementById(id); } catch (e) { return null; }
};
const $q = (sel) => {
  try { return document.querySelector(sel); } catch (e) { return null; }
};

/* ---- standalone auth (STUDIO_ADMIN_TOKEN) ----
   Saved in localStorage; api()/media use Bearer when present,
   Telegram initData (tma) otherwise. Backend enables Bearer ONLY
   when STUDIO_ADMIN_TOKEN is configured. */
function studioToken() {
  try { return (localStorage.getItem("vf_studio_token") || "").trim(); } catch (e) { return ""; }
}
function authHeader() {
  const tok = studioToken();
  if (tok) return { Authorization: "Bearer " + tok };
  return { Authorization: AUTH };
}
const $$ = (sel, root) => {
  try { return Array.from((root || document).querySelectorAll(sel)); } catch (e) { return []; }
};

const faDigits = (s) => String(s).replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[d]);
const num = (s) => (LANG === "fa" ? faDigits(s) : String(s));

/* ============================================================
   CALENDAR — Jalali (fa) + Gregorian (en)
   ============================================================ */
const MONTHS_EN = ["January","February","March","April","May","June",
  "July","August","September","October","November","December"];
const MONTHS_FA = ["فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور",
  "مهر","آبان","آذر","دی","بهمن","اسفند"];
const WEEKDAYS_FA = ["ش","ی","د","س","چ","پ","ج"];   // Sat-first
const WEEKDAYS_EN = ["Sa","Su","Mo","Tu","We","Th","Fr"]; // Sat-first

function g2j(gy, gm, gd) {
  const g_d_m = [0,31,59,90,120,151,181,212,243,273,304,334];
  let jy = (gy <= 1600) ? 0 : 979;
  gy -= (gy <= 1600) ? 621 : 1600;
  const gy2 = (gm > 2) ? (gy + 1) : gy;
  let days = (365 * gy) + Math.floor((gy2 + 3) / 4) - Math.floor((gy2 + 99) / 100)
    + Math.floor((gy2 + 399) / 400) - 80 + gd + g_d_m[gm - 1];
  jy += 33 * Math.floor(days / 12053); days %= 12053;
  jy += 4 * Math.floor(days / 1461); days %= 1461;
  if (days > 365) { jy += Math.floor((days - 1) / 365); days = (days - 1) % 365; }
  const jm = (days < 186) ? 1 + Math.floor(days / 31) : 7 + Math.floor((days - 186) / 30);
  const jd = 1 + ((days < 186) ? (days % 31) : ((days - 186) % 30));
  return [jy, jm, jd];
}
function j2g(jy, jm, jd) {
  let gy = (jy <= 979) ? 621 : 1600;
  jy -= (jy <= 979) ? 0 : 979;
  let days = (365 * jy) + (Math.floor(jy / 33) * 8) + Math.floor(((jy % 33) + 3) / 4)
    + 78 + jd + ((jm < 7) ? (jm - 1) * 31 : ((jm - 7) * 30) + 186);
  gy += 400 * Math.floor(days / 146097); days %= 146097;
  if (days > 36524) {
    gy += 100 * Math.floor(--days / 36524); days %= 36524;
    if (days >= 365) days++;
  }
  gy += 4 * Math.floor(days / 1461); days %= 1461;
  if (days > 365) { gy += Math.floor((days - 1) / 365); days = (days - 1) % 365; }
  let gd = days + 1;
  const sal_a = [0,31,((gy % 4 === 0 && gy % 100 !== 0) || (gy % 400 === 0)) ? 29 : 28,
    31,30,31,30,31,31,30,31,30,31];
  let gm;
  for (gm = 1; gm <= 12; gm++) {
    if (gd <= sal_a[gm]) break;
    gd -= sal_a[gm];
  }
  return [gy, gm, gd];
}
function isLeapJalali(jy) {
  return ((25 * jy + 11) % 33) < 8;
}
function jalaliMonthLen(jy, jm) {
  if (jm <= 6) return 31;
  if (jm <= 11) return 30;
  return isLeapJalali(jy) ? 30 : 29;
}
function jalaliWeekday(jy, jm, jd) {
  const [gy, gm, gd] = j2g(jy, jm, jd);
  const d = new Date(gy, gm - 1, gd);
  return (d.getDay() + 1) % 7; // Sat-first
}
const calState = {
  fa: { jy: 0, jm: 0 },
  en: { gy: 0, gm: 0 },
};
function initCalState() {
  const now = new Date();
  const [jy, jm] = g2j(now.getFullYear(), now.getMonth() + 1, now.getDate());
  calState.fa = { jy, jm };
  calState.en = { gy: now.getFullYear(), gm: now.getMonth() + 1 };
}
function buildCalendarMonth() {
  if (LANG === "fa") {
    const { jy, jm } = calState.fa;
    const title = `${MONTHS_FA[jm - 1]} ${num(jy)}`;
    const len = jalaliMonthLen(jy, jm);
    const startCol = jalaliWeekday(jy, jm, 1);
    const today = new Date();
    const [tjy, tjm, tjd] = g2j(today.getFullYear(), today.getMonth() + 1, today.getDate());
    const isCurMonth = (tjy === jy && tjm === jm);
    const cells = [];
    for (let i = 0; i < startCol; i++) cells.push({ empty: true });
    for (let d = 1; d <= len; d++) {
      const [gy, gm, gd] = j2g(jy, jm, d);
      const key = `${gy}-${String(gm).padStart(2, "0")}-${String(gd).padStart(2, "0")}`;
      cells.push({ day: d, key, today: isCurMonth && d === tjd, label: num(d) });
    }
    return { title, weekdays: WEEKDAYS_FA, cells };
  } else {
    const { gy, gm } = calState.en;
    const title = `${MONTHS_EN[gm - 1]} ${gy}`;
    const len = new Date(gy, gm, 0).getDate();
    const first = new Date(gy, gm - 1, 1);
    const startCol = (first.getDay() + 1) % 7;
    const today = new Date();
    const isCurMonth = (today.getFullYear() === gy && today.getMonth() + 1 === gm);
    const cells = [];
    for (let i = 0; i < startCol; i++) cells.push({ empty: true });
    for (let d = 1; d <= len; d++) {
      const key = `${gy}-${String(gm).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      cells.push({ day: d, key, today: isCurMonth && d === today.getDate(), label: String(d) });
    }
    return { title, weekdays: WEEKDAYS_EN, cells };
  }
}

/* ---------------- i18n ---------------- */
const I18N = {
  fa: {
    plan: "برنامهٔ انتشار", recent: "آخرین پست‌ها", my_chats: "چت‌های ثبت‌شده",
    auto_reg: "چت‌هایی که بات در آن‌ها ادمین است خودکار ثبت می‌شوند؛ برای ثبت فوری در گروه، /syncchat را همان‌جا بفرست.",
    add_channel: "افزودن دستی کانال جدید", ch_ph: "@username یا لینک", add: "افزودن",
    f_all: "همه", f_draft: "پیش‌نویس", f_approved: "تأییدشده", f_scheduled: "زمان‌بندی",
    f_published: "منتشرشده", f_failed: "ناموفق", f_rejected: "ردشده",
    signature: "امضای پایین پست", sig_enable: "افزودن امضا هنگام انتشار", save: "ذخیره",
    ai_title: "هوش مصنوعی", about: "درباره",
    about_text: "VoidFeed Studio v3 — تولید محتوا برای تلگرام و شبکه‌های اجتماعی؛ همه‌چیز روی سرور خودت.",
    new_post: "＋ پست جدید", tab_home: "خانه", tab_chats: "چت‌ها", tab_posts: "پست‌ها", tab_profile: "پروفایل", tab_connections: "اتصال‌ها",
    conn_title: "مرکز اتصال‌ها", conn_hint: "اتصال اکانت‌های شبکه‌های اجتماعی برای انتشار از استودیو. تلگرام از طریق بات متصل است؛ بقیه نیاز به تنظیم کلید توسعه‌دهنده دارند.",
    conn_status_configured: "پیکربندی‌شده", conn_status_awaiting_setup: "در انتظار تنظیم", conn_status_connected: "متصل", conn_status_expired: "منقضی‌شده",
    conn_accounts: "اکانت‌ها", conn_no_accounts: "اکانتی متصل نیست", conn_connect: "اتصال", conn_disconnect: "قطع اتصال",
    conn_missing_env: "کلیدهای لازم تنظیم نشده:", conn_never_connected: "هنوز متصل نشده", conn_verified_at: "آخرین بررسی:",
    dr_head: "منو", dr_create: "ایجاد پست", dr_cancel: "لغو", dr_posts: "پست‌های من", dr_profile: "پروفایل",
    dr_lang: "تغییر زبان", dr_back: "بازگشت", dr_linkpreview: "پیش‌نمایش لینک", dr_autofwd: "ذخیره خودکار فوروارد", dr_help: "راهنما",
    dr_linkpreview_on: "پیش‌نمایش لینک روشن شد", dr_linkpreview_off: "پیش‌نمایش لینک خاموش شد",
    dr_autofwd_on: "ذخیره خودکار فوروارد روشن شد", dr_autofwd_off: "ذخیره خودکار فوروارد خاموش شد",
    tab_schedule: "برنامه", sched_title: "زمان‌بندی انتشار", sched_hint: "پست‌های زمان‌بندی‌شده اینجا مدیریت می‌شوند؛ بات در زمان مقرر منتشر می‌کند.",
    sched_empty: "پست زمان‌بندی‌شده‌ای نیست", sched_target: "کانال مقصد", sched_when: "زمان انتشار",
    sched_change: "تغییر زمان", sched_save: "ثبت زمان", sched_unschedule: "لغو زمان‌بندی",
    sched_saved: "زمان انتشار به‌روزرسانی شد ✓", sched_unscheduled: "زمان‌بندی لغو شد", sched_invalid: "زمان نامعتبر است",
    tab_history: "تاریخچه", hist_title: "تاریخچه انتشار", hist_hint: "ثبت رویدادهای انتشار/زمان‌بندی (فقط از طریق استودیو; انتشار توسط بات در حالت برنامه‌ریزی ثبت نمی‌شود).",
    hist_empty: "رخدادی ثبت نشده است", hist_all: "همه", hist_scheduled: "زمان‌بندی", hist_published: "منتشرشده",
    hist_failed: "ناموفق", hist_unscheduled: "لغو", hist_channel: "کانال", hist_when: "زمان", hist_event: "رخداد",
    lib_title: "کتابخانه رسانه", lib_open: "کتابخانه", lib_empty: "هنوز رسانه‌ای بارگذاری نشده", lib_attach: "استفاده",
    lib_del: "حذف", lib_saved: "ذخیره شد ✓", lib_deleted: "حذف شد", lib_refused: "این فایل در پست‌ها استفاده شده",
    tpl_title: "قالب‌های پست", tpl_open: "قالب‌ها", tpl_name_ph: "نام قالب", tpl_body_ph: "متن قالب",
    tpl_create: "افزودن قالب", tpl_created: "قالب ساخته شد ✓", tpl_insert: "درج", tpl_append: "افزودن به متن",
    tpl_replace: "جایگزینی متن", tpl_delete: "حذف", tpl_empty: "قالبی ساخته نشده", tpl_deleted: "قالب حذف شد",
    post_text_ph: "متن پست…", ai_topic_ph: "موضوع پست برای هوش مصنوعی…",
    ai_gen: "تولید", tone_friendly: "لحن: صمیمی", tone_formal: "رسمی",
    tone_funny: "طنز", tone_promo: "تبلیغاتی", tone_news: "خبری",
    ai_not_configured: "هوش مصنوعی تنظیم نشده است؛ AI_API_BASE و AI_API_KEY را در سرویس استودیو تنظیم کن.",
    ai_need_topic: "موضوع بنویس",
    ai_key_set: "کلید تنظیم شده", ai_host: "میزبان", ai_models: "مدل‌ها",
    ai_test: "آزمایش اتصال", ai_test_ok: "اتصال برقرار است ✓", ai_test_fail: "اتصال ناموفق", ai_test_unconfigured: "اول کلیدها را تنظیم کن",
    rec_hint: "پیش‌نویس ذخیره‌نشده‌ای از قبل وجود دارد", rec_restore: "بازگردانی", rec_applied: "پیش‌نویس بازگردانی شد ✓",
    prof_desc_fa: "معرفی برند (فارسی)", prof_desc_en: "معرفی برند (انگلیسی)",
    prof_social_title: "حضور اجتماعی", prof_social_hint: "لینک‌های عمومی؛ ✓ سبز یعنی لینک تأییدشده، آیکن اطلاعات یعنی لینک کاربر بدون تأیید مستقل.", prof_verified: "لینک تأییدشده", prof_unverified: "لینک کاربر، بدون تأیید مستقل (لینک همان‌طور که تنظیم شده باز می‌شود)", prof_no_link: "لینکی تنظیم نشده",
    prof_saved: "برند ذخیره شد ✓",
    conn_title2: "اتصال‌ها", conn_hint2: "حضور اجتماعی با اتصال فنی متفاوت است؛ هیچ OAuth فعال نیست.",
    conn_social_col: "حضور اجتماعی", conn_tech_col: "اتصال فنی",
    conn_st_setup_ready: "آماده تنظیم", conn_st_setup_required: "نیازمند تنظیم",
    conn_st_not_supported: "پشتیبانی نمی‌شود", conn_st_not_implemented: "پیاده‌سازی نشده", conn_st_not_connected: "متصل نیست",
    conn_kind_bot_api: "از طریق API بات", conn_kind_public_profile_only: "فقط پروفایل عمومی",
    conn_cap_publish_via_bot: "انتشار از طریق بات",
    conn_open_profile: "بازکردن پروفایل", conn_pending_asset: "لوگوی رسمی هنوز تأیید نشده",
    conn_telegram_note: "استودیو برای انتشار به بات تلگرام اتکا دارد؛ هیچ OAuth فعال نیست.",
    conn_unsupported_note: "تنها حضور عمومی؛ ادغام فنی پیاده‌سازی نشده است.",
    conn_g_method: "روش اتصال", conn_g_prereq: "پیش‌نیازها", conn_g_where: "محل تنظیم",
    conn_g_steps: "مراحل", conn_g_test: "آزمون", conn_g_enabled: "پس از راه‌اندازی",
    conn_g_limits: "محدودیت‌ها", conn_g_next: "قدم بعدی",
    conn_token_present: "توکن بات موجود است (هنوز یک اتصال آزموده‌شده نیست).",
    conn_token_absent: "توکن بات یافت نشد.",
    conn_requires: "نیازمند", conn_not_implemented: "پیاده‌سازی نشده", conn_in_development: "در دست توسعه",
    conn_never: "هرگز", conn_future: "مسیر آینده", conn_note: "یادداشت",


    len_short: "کوتاه", len_medium: "متوسط", len_long: "بلند",
    rw_improve: "بازنویسی", rw_shorten: "کوتاه‌تر", rw_emoji: "ایموجی‌دار",
    networks: "شبکه‌های هدف", attach: "تصویر / ویدیو", schedule: "زمان‌بندی",
    close: "بستن", save_draft: "ذخیره", publish_now: "انتشار فوری",
    mgen: "تولید تصویر/ویدیو برنددار", mgen_photo: "تصویر", mgen_video: "ویدیو",
    mgen_sec: "طول ویدیو (ثانیه)", mgen_go: "ساخت از متن پست",
    news_title: "اخبار خودکار", news_enable: "دریافت و انتشار خودکار خبر",
    news_auto: "انتشار مستقیم در کانال پیش‌فرض", news_interval_ph: "بازه (دقیقه)",
    news_now: "واکشی و انتشار فوری یک خبر",
    st_draft: "پیش‌نویس", st_approved: "تأییدشده", st_scheduled: "زمان‌بندی‌شده",
    st_published: "منتشرشده", st_publish_failed: "ناموفق", st_rejected: "ردشده",
    stat_ready: "آماده", stat_scheduled: "زمان‌بندی", stat_published: "منتشرشده", stat_failed: "ناموفق",
    chars: "نویسه", chars_media: "(با رسانه حداکثر ۱۰۰۰)", empty_day: "پستی در این روز نیست",
    empty_posts: "چیزی اینجا نیست", empty_recent: "هنوز پستی نیست — با «＋ پست جدید» شروع کن",
    empty_chats: "هنوز کانالی اضافه نشده", default_tag: "پیش‌فرض",
    toast_published: "منتشر شد ✓", toast_scheduled: "زمان‌بندی شد ✓", toast_saved: "ذخیره شد ✓",
    toast_draft_saved: "پیش‌نویس ذخیره شد ✓", toast_refreshed: "به‌روزرسانی شد",
    toast_img_attached: "رسانه پیوست شد ✓", toast_ai_done: "متن ساخته شد ✓",
    toast_rewritten: "بازنویسی شد ✓", toast_deleted: "حذف شد", toast_rejected: "رد شد",
    toast_unscheduled: "زمان‌بندی لغو شد", toast_confirm_del: "حذف شود؟",
    sched_prompt: "زمان انتشار (YYYY-MM-DD HH:MM به وقت تهران):",
    preview: "پیش‌نمایش", preview_title: "پیش‌نمایش پست",
    preview_trunc: "هنگام انتشار متن به {n} نویسه کوتاه می‌شود (محدودیت تلگرام).",
    preview_fallback: "متن اصلی (واریانت {net} ذخیره نشده)", preview_copy_fail: "کپی ناموفق بود",
    logout: "خروج و حذف توکن دسترسی", logout_done: "توکن حذف شد؛ در حال بازگشت…",
    editor_new: "پست جدید", editor_edit: "ویرایش پست #", need_text: "متن یا رسانه لازم است",
    too_long_media: "با رسانه حداکثر ۱۰۰۰ نویسه", ai_need_topic: "اول موضوع را بنویس",
    need_content: "اول متنی بنویس", mgen_need_text: "اول متن پست را بنویس",
    mgen_done: "ساخته شد ✓ — به پست پیوست شد", mgen_fail: "خطا در ساخت: ",
    news_saved: "تنظیمات اخبار ذخیره شد ✓", news_fetched: "منتشر شد: ", news_drafted: "پیش‌نویس # ذخیره شد",
    net_over: "بیش از حد مجاز!", copy: "کپی", copied: "کپی شد ✓",
    variant_for: "برای", no_channel: "— اول کانال اضافه کن —", char_unit: "نویسه",
    lang_btn_fa: "EN", lang_btn_en: "FA",
    day_posts: "پست‌های",
    months: ["ژانویه","فوریه","مارس","آوریل","مه","ژوئن","ژوئیه","اوت","سپتامبر","اکتبر","نوامبر","دسامبر"],
    weekdays: ["ش","ی","د","س","چ","پ","ج"],
    dr_mod: "مدیریت محتوا", dr_stats: "آمار", dr_news: "اخبار خودکار",
    mod_title: "مدیریت محتوا", mod_hint: "کلمات ممنوعه هنگام دریافت پیام بررسی می‌شوند؛ با «بازدارنده» (Regex) می‌توانید الگو بسازید.",
    mod_term_ph: "کلمه / الگو", mod_regex: "Regex", mod_add_word: "افزودن",
    mod_chats: "گفتگوهای تحت نظارت", mod_log: "لاگ بازداشت", mod_banned: "کاربران مسدود",
    mod_empty_words: "هنوز کلمه‌ای ثبت نشده", mod_empty_chats: "گفتگویی تحت نظارت نیست",
    mod_empty_log: "لاگی ثبت نشده", mod_empty_banned: "کاربر مسدودی نیست",
    mod_disable: "لغو نظارت", mod_enable: "تحت نظارت", mod_unban: "رفع مسدودی",
    mod_need_term: "اول دسته و کلمه را وارد کن",
    stats_title: "آمار استودیو", stats_hint: "همه عددها از داده واقعی سرور خوانده می‌شوند؛ اگر سرویسی در دسترس نباشد، جای آن «ناموجود» نشان داده می‌شود.",
    stat_rejected: "ردشده", stats_unavailable: "ناموجود",
    stat_channels: "کانال‌ها", stat_media: "رسانه‌ها", stat_templates: "قالب‌ها", stat_news: "منابع خبر",
    news_admin_title: "اخبار خودکار", src_title: "منابع خبر", src_hint: "فقط آدرس‌های http(s) پذیرفته می‌شوند؛ نام و دسته برای هر منبع الزامی است.",
    src_name_ph: "نام منبع", src_url_ph: "آدرس خوراک", src_cat_ph: "دسته",
    src_add: "افزودن", src_del: "حذف", src_empty: "منبعی ثبت نشده", src_invalid: "نام، دسته و آدرس معتبر لازم است",
    news_meta_seen: "دیده‌شده", news_meta_last: "آخرین واکشی", news_meta_error: "خطای آخر", news_meta_none: "هنوز واکشی‌ای انجام نشده",
    ai_format: "قالب‌بندی (AI)",
  },
  en: {
    plan: "Publishing plan", recent: "Recent posts", my_chats: "Registered chats",
    auto_reg: "Chats where the bot is admin are registered automatically; send /syncchat in a group to register it now.",
    add_channel: "Add a channel manually", ch_ph: "@username or link", add: "Add",
    f_all: "All", f_draft: "Drafts", f_approved: "Approved", f_scheduled: "Scheduled",
    f_published: "Published", f_failed: "Failed", f_rejected: "Rejected",
    signature: "Post signature", sig_enable: "Append signature on publish", save: "Save",
    ai_title: "AI", about: "About",
    about_text: "VoidFeed Studio v3 — content production for Telegram and social networks; everything on your own server.",
    new_post: "＋ New post", tab_home: "Home", tab_chats: "Chats", tab_posts: "Posts", tab_profile: "Me", tab_connections: "Connections",
    conn_title: "Connection Center", conn_hint: "Connect social accounts for publishing from Studio. Telegram connects through the bot; the others require developer credentials.",
    conn_status_configured: "Configured", conn_status_awaiting_setup: "Awaiting setup", conn_status_connected: "Connected", conn_status_expired: "Expired",
    conn_accounts: "Accounts", conn_no_accounts: "No account connected", conn_connect: "Connect", conn_disconnect: "Disconnect",
    conn_missing_env: "Missing required keys:", conn_never_connected: "Never verified", conn_verified_at: "Last verified:",
    dr_head: "Menu", dr_create: "Create post", dr_cancel: "Cancel", dr_posts: "My posts", dr_profile: "Profile",
    dr_lang: "Change language", dr_back: "Back", dr_linkpreview: "Link preview", dr_autofwd: "Auto-save forwards", dr_help: "Help",
    dr_linkpreview_on: "Link preview enabled", dr_linkpreview_off: "Link preview disabled",
    dr_autofwd_on: "Auto-save forwards enabled", dr_autofwd_off: "Auto-save forwards disabled",
    tab_schedule: "Schedule", sched_title: "Scheduled posts", sched_hint: "Scheduled posts are managed here; the bot publishes them at the set time.",
    sched_empty: "No scheduled posts", sched_target: "Target channel", sched_when: "Publish at",
    sched_change: "Change time", sched_save: "Save time", sched_unschedule: "Unschedule",
    sched_saved: "Publish time updated ✓", sched_unscheduled: "Unschedule", sched_invalid: "Invalid time",
    tab_history: "History", hist_title: "Publishing history", hist_hint: "Event log for publish/schedule (Studio-originated only; bot-side scheduled publishing is not recorded yet).",
    hist_empty: "No events recorded yet", hist_all: "All", hist_scheduled: "Scheduled", hist_published: "Published",
    hist_failed: "Failed", hist_unscheduled: "Unschedule", hist_channel: "Channel", hist_when: "When", hist_event: "Event",
    lib_title: "Media library", lib_open: "Library", lib_empty: "No media uploaded yet", lib_attach: "Use",
    lib_del: "Delete", lib_saved: "Saved ✓", lib_deleted: "Deleted", lib_refused: "This file is used by posts and cannot be deleted",
    tpl_title: "Post templates", tpl_open: "Templates", tpl_name_ph: "Template name", tpl_body_ph: "Template body",
    tpl_create: "Add template", tpl_created: "Template created ✓", tpl_insert: "Insert", tpl_append: "Append to text",
    tpl_replace: "Replace text", tpl_delete: "Delete", tpl_empty: "No templates yet", tpl_deleted: "Template deleted",
    post_text_ph: "Post text…", ai_topic_ph: "Post topic for AI…",
    ai_gen: "Generate", tone_friendly: "Tone: friendly", tone_formal: "Formal",
    tone_funny: "Funny", tone_promo: "Promo", tone_news: "News",
    ai_not_configured: "AI is not configured; set AI_API_BASE and AI_API_KEY in the Studio service.",
    ai_need_topic: "Write a topic",
    ai_key_set: "Key set", ai_host: "Host", ai_models: "Models",
    ai_test: "Test connection", ai_test_ok: "Connection OK ✓", ai_test_fail: "Connection failed", ai_test_unconfigured: "Configure keys first",
    rec_hint: "You have an unsaved draft", rec_restore: "Restore", rec_applied: "Draft restored ✓",
    prof_desc_fa: "Brand intro (Persian)", prof_desc_en: "Brand intro (English)",
    prof_social_title: "Social presence", prof_social_hint: "Public links; green ✓ = verified link, info icon = user-supplied link (not independently verified).", prof_verified: "Verified link", prof_unverified: "User-supplied link, not independently verified (opens exactly as configured)", prof_no_link: "No link set",
    prof_saved: "Brand saved ✓",
    conn_title2: "Connections", conn_hint2: "Social presence differs from a technical connection; no OAuth is active.",
    conn_social_col: "Social presence", conn_tech_col: "Technical connection",
    conn_st_setup_ready: "Setup ready", conn_st_setup_required: "Setup required",
    conn_st_not_supported: "Not supported", conn_st_not_implemented: "Not implemented", conn_st_not_connected: "Not connected",
    conn_kind_bot_api: "Via bot API", conn_kind_public_profile_only: "Public profile only",
    conn_cap_publish_via_bot: "Publish via bot",
    conn_open_profile: "Open profile", conn_pending_asset: "Official logo not yet verified",
    conn_telegram_note: "Studio relies on the Telegram bot for publishing; no OAuth active.",
    conn_unsupported_note: "Public presence only; technical integration not implemented.",
    conn_g_method: "Connection method", conn_g_prereq: "Prerequisites", conn_g_where: "Where to configure",
    conn_g_steps: "Steps", conn_g_test: "Test", conn_g_enabled: "After setup",
    conn_g_limits: "Limitations", conn_g_next: "Next step",
    conn_token_present: "Bot token is present (not yet a verified connection).",
    conn_token_absent: "No bot token found.",
    conn_requires: "Requires", conn_not_implemented: "Not implemented", conn_in_development: "In development",
    conn_never: "Never", conn_future: "Future path", conn_note: "Note",


    len_short: "Short", len_medium: "Medium", len_long: "Long",
    rw_improve: "Rewrite", rw_shorten: "Shorter", rw_emoji: "Add emoji",
    networks: "Target networks", attach: "Photo / video", schedule: "Schedule",
    close: "Close", save_draft: "Save", publish_now: "Publish now",
    mgen: "Branded image/video", mgen_photo: "Photo", mgen_video: "Video",
    mgen_sec: "Video length (seconds)", mgen_go: "Generate from post text",
    news_title: "Auto news", news_enable: "Fetch & publish news automatically",
    news_auto: "Publish directly to default channel", news_interval_ph: "Interval (minutes)",
    news_now: "Fetch & publish one item now",
    st_draft: "Draft", st_approved: "Approved", st_scheduled: "Scheduled",
    st_published: "Published", st_publish_failed: "Failed", st_rejected: "Rejected",
    stat_ready: "Ready", stat_scheduled: "Scheduled", stat_published: "Published", stat_failed: "Failed",
    chars: "chars", chars_media: "(max 1000 with media)", empty_day: "Nothing on this day",
    empty_posts: "Nothing here yet", empty_recent: "No posts yet — start with “＋ New post”",
    empty_chats: "No chats yet", default_tag: "default",
    toast_published: "Published ✓", toast_scheduled: "Scheduled ✓", toast_saved: "Saved ✓",
    toast_draft_saved: "Draft saved ✓", toast_refreshed: "Refreshed",
    toast_img_attached: "Media attached ✓", toast_ai_done: "Text generated ✓",
    toast_rewritten: "Rewritten ✓", toast_deleted: "Deleted", toast_rejected: "Rejected",
    toast_unscheduled: "Schedule cancelled", toast_confirm_del: "Delete?",
    sched_prompt: "Publish time (YYYY-MM-DD HH:MM, Tehran):",
    preview: "Preview", preview_title: "Post preview",
    preview_trunc: "On publish the text is cut to {n} chars (Telegram limit).",
    preview_fallback: "Main text (no {net} variant saved)", preview_copy_fail: "Copy failed",
    logout: "Log out (remove access token)", logout_done: "Token removed; reloading…",
    editor_new: "New post", editor_edit: "Edit post #", need_text: "Text or media is required",
    too_long_media: "Max 1000 chars with media", ai_need_topic: "Write a topic first",
    need_content: "Write some text first", mgen_need_text: "Write the post text first",
    mgen_done: "Generated ✓ — attached to the post", mgen_fail: "Generation failed: ",
    news_saved: "News settings saved ✓", news_fetched: "Published: ", news_drafted: "Draft # saved",
    net_over: "over limit!", copy: "copy", copied: "copied ✓",
    variant_for: "for", no_channel: "— add a channel first —", char_unit: "chars",
    lang_btn_fa: "EN", lang_btn_en: "FA",
    day_posts: "Posts on",
    months: ["January","February","March","April","May","June","July","August","September","October","November","December"],
    weekdays: ["Sa","Su","Mo","Tu","We","Th","Fr"],
    dr_mod: "Moderation", dr_stats: "Statistics", dr_news: "Auto news",
    mod_title: "Moderation", mod_hint: "Banned words are checked on incoming messages; use regex for patterns.",
    mod_term_ph: "word / pattern", mod_regex: "Regex", mod_add_word: "Add",
    mod_chats: "Monitored chats", mod_log: "Hold log", mod_banned: "Banned users",
    mod_empty_words: "No words yet", mod_empty_chats: "No monitored chats",
    mod_empty_log: "No log entries", mod_empty_banned: "Nobody banned",
    mod_disable: "Unmonitor", mod_enable: "Monitor", mod_unban: "Unban",
    mod_need_term: "Choose a category and enter a word",
    stats_title: "Statistics", stats_hint: "All numbers are read from real server data; if a service is unavailable it shows “unavailable”.",
    stat_rejected: "Rejected", stats_unavailable: "unavailable",
    stat_channels: "Channels", stat_media: "Media", stat_templates: "Templates", stat_news: "News sources",
    news_admin_title: "Auto news", src_title: "News sources", src_hint: "Only http(s) URLs are accepted; name and category are required.",
    src_name_ph: "Source name", src_url_ph: "Feed URL", src_cat_ph: "Category",
    src_add: "Add", src_del: "Delete", src_empty: "No sources yet", src_invalid: "Valid name, category and URL are required",
    news_meta_seen: "Seen", news_meta_last: "Last fetch", news_meta_error: "Last error", news_meta_none: "Not fetched yet",
    ai_format: "Format (AI)",
  },
};

let LANG = localStorage.getItem("vf_lang") || "fa";

function t(key) {
  return (I18N[LANG] && I18N[LANG][key]) || (I18N.fa && I18N.fa[key]) || key;
}

function applyI18n() {
  document.documentElement.lang = LANG;
  document.documentElement.dir = LANG === "fa" ? "rtl" : "ltr";

  $$("[data-i18n]").forEach((el) => {
    if (el.dataset.faText === undefined) el.dataset.faText = el.textContent;
    el.textContent = LANG === "en" ? t(el.dataset.i18n) : (el.dataset.faText || t(el.dataset.i18n));
  });
  $$("[data-i18n-ph]").forEach((el) => {
    if (el.dataset.faPh === undefined) el.dataset.faPh = el.placeholder;
    el.placeholder = LANG === "en" ? t(el.dataset.i18nPh) : (el.dataset.faPh || t(el.dataset.i18nPh));
  });

  const lb = $("btn-lang");
  if (lb) lb.textContent = LANG === "fa" ? "EN" : "FA";

}

/* ---------------- state ---------------- */
let state = {
  me: null,
  channels: [],
  filter: "",
  editingId: null,
  mediaUrl: null,
  editVariants: {},
  calMonth: new Date(),
  planCache: {},
  schedOn: false,
  settings: null,
  selectedNets: new Set(["telegram"]), // default
  networkDefs: null, // /api/networks defs (server = source of truth)
  // preview modal state (network-aware preview)
  previewNet: "telegram",
  previewVariants: {},
  previewMainText: "",
  previewMediaUrl: null,
  previewChannelId: null,
  previewSettings: null,
  previewShownText: "",
  previewHasVariant: false,
};

/* ---------------- Social Networks with real limits ----------------
   Built-in fallback; replaced at boot by the backend /api/networks
   definitions (NETWORK_SPECS) so limits/keys always match the server. */
const NETWORKS = {
  telegram: {
    id: "telegram",
    label: "Telegram",
    maxText: 4096,
    maxWithMedia: 1024,
    supportsVideo: true,
    supportsPhoto: true,
    url: "https://t.me/FeedTheVoids",
  },
  instagram: {
    id: "instagram",
    label: "Instagram",
    maxText: 2200,
    maxWithMedia: 2200,
    supportsVideo: true,
    supportsPhoto: true,
    url: "https://instagram.com/voidfeedmedia",
  },
  twitter: {
    id: "twitter",
    label: "X / Twitter",
    maxText: 280,
    maxWithMedia: 280,
    supportsVideo: true,
    supportsPhoto: true,
    url: "https://x.com/VoidFeedMedia",
  },
  facebook: {
    id: "facebook",
    label: "Facebook",
    maxText: 5000,
    maxWithMedia: 5000,
    supportsVideo: true,
    supportsPhoto: true,
    url: "https://facebook.com/TheVoidFeedMedia",
  },
  tiktok: {
    id: "tiktok",
    label: "TikTok",
    maxText: 4000,
    maxWithMedia: 4000,
    supportsVideo: true,
    supportsPhoto: true,
    url: "https://tiktok.com/@voidfeedmedia",
  },
  youtube: {
    id: "youtube",
    label: "YouTube",
    maxText: 5000,
    maxWithMedia: 5000,
    supportsVideo: true,
    supportsPhoto: true,
    url: "https://youtube.com/@voidfeedmedia",
  },
};

/* ---------------- api ---------------- */
async function api(path, opts = {}) {
  const headers = Object.assign(authHeader(), opts.headers || {});
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  const res = await fetch(path, Object.assign({ headers }, opts));
  let data = {};
  try { data = await res.json(); } catch (e) {}
  if (!res.ok) {
    const err = new Error(data.detail || data.message || ("Error " + res.status));
    err.status = res.status;
    throw err;
  }
  return data;
}

/* ---------------- authenticated media (Blob URLs) ----------------
   <img>/<video> cannot send the Authorization header, so media URLs are
   fetched with the header and rendered via blob: object URLs. Cache holds
   blob URLs for connected elements; revoked when unused or evicted. */
const mediaBlobCache = new Map(); // url -> {blobUrl, ts, els:Set}
const MEDIA_BLOB_MAX = 16;
const MEDIA_BLOB_IDLE_MS = 60 * 1000;

function pruneMediaCache() {
  const now = Date.now();
  for (const [url, entry] of [...mediaBlobCache]) {
    let connected = false;
    entry.els.forEach((el) => { if (el.isConnected) connected = true; });
    if (!connected && now - entry.ts > MEDIA_BLOB_IDLE_MS) {
      try { URL.revokeObjectURL(entry.blobUrl); } catch (e) {}
      mediaBlobCache.delete(url);
    }
  }
  while (mediaBlobCache.size > MEDIA_BLOB_MAX) { // evict oldest unused first
    let evicted = null;
    for (const [url, entry] of mediaBlobCache) {
      let connected = false;
      entry.els.forEach((el) => { if (el.isConnected) connected = true; });
      if (!connected) { evicted = url; break; }
    }
    if (!evicted) break; // all in use; keep (bounded by page size)
    try { URL.revokeObjectURL(mediaBlobCache.get(evicted).blobUrl); } catch (e) {}
    mediaBlobCache.delete(evicted);
  }
}

async function fetchMediaBlobUrl(url) {
  const hit = mediaBlobCache.get(url);
  if (hit) return hit.blobUrl;
  const res = await fetch(url, { headers: authHeader() });
  if (!res.ok) throw new Error("Error " + res.status);
  const blob = await res.blob();
  const blobUrl = URL.createObjectURL(blob);
  mediaBlobCache.set(url, { blobUrl, ts: Date.now(), els: new Set() });
  pruneMediaCache();
  return blobUrl;
}

// Attach blob sources to every [data-media] element under rootEl.
function hydrateMedia(rootEl) {
  $$("[data-media]", rootEl).forEach((el) => {
    const url = el.dataset.media;
    if (!url || el.dataset.hydrated === "1") return;
    el.dataset.hydrated = "1";
    const entry = mediaBlobCache.get(url);
    if (entry) entry.els.add(el);
    fetchMediaBlobUrl(url)
      .then((blobUrl) => {
        const e2 = mediaBlobCache.get(url);
        if (e2) e2.els.add(el);
        if (el.isConnected) el.src = blobUrl;
      })
      .catch(() => {
        el.classList.add("media-fail");
        el.removeAttribute("data-media");
      });
  });
}

/* preview modal media: fetched per open, revoked on close (videos can be
   large, so they are not kept in the shared cache) */
let previewBlobUrl = null;

function clearPreviewMedia() {
  if (previewBlobUrl) {
    try { URL.revokeObjectURL(previewBlobUrl); } catch (e) {}
    previewBlobUrl = null;
  }
}

async function loadPreviewMedia(el, url) {
  clearPreviewMedia();
  if (!el || !url) return;
  try {
    const res = await fetch(url, { headers: authHeader() });
    if (!res.ok) throw new Error("Error " + res.status);
    const blobUrl = URL.createObjectURL(await res.blob());
    previewBlobUrl = blobUrl;
    if (el.isConnected) el.src = blobUrl;
  } catch (e) {
    el.classList.add("media-fail");
  }
}

function toast(msg) {
  const el = $("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._h);
  el._h = setTimeout(() => el.classList.remove("show"), 2600);
}

function fmtTime(iso) {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat(LANG === "fa" ? "fa-IR" : "en-GB", {
      timeZone: "Asia/Tehran",
      dateStyle: "short",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch (e) { return iso; }
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
}
function escFull(s) {
  const d = document.createElement("div");
  d.textContent = s || "";
  return d.innerHTML;
}

/* ---------------- navigation ---------------- */
function currentPage() {
  const active = document.querySelector(".bottom-nav .tab.active");
  return active ? active.dataset.page : "home";
}

function showPage(name) {
  $$(".bottom-nav .tab").forEach((b) => b.classList.toggle("active", b.dataset.page === name));
  $$(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + name));
  if (name === "home") loadHome();
  if (name === "channels") loadChannels();
  if (name === "connections") loadConnections();
  if (name === "posts") loadPosts();
  if (name === "schedule") loadSchedule();
  if (name === "history") loadHistory();
  if (name === "profile") loadProfile();
  if (name === "mod") loadMod();
  if (name === "stats") loadStats();
  if (name === "news") loadNewsAdmin();
}

/* ---------------- Home + Calendar ---------------- */
const STATUS_LABEL = {
  draft: () => t("st_draft"),
  approved: () => t("st_approved"),
  scheduled: () => t("st_scheduled"),
  published: () => t("st_published"),
  publish_failed: () => t("st_publish_failed"),
  rejected: () => t("st_rejected"),
};

async function loadHome() {
  try {
    const me = await api("/api/me");
    state.me = me;
    const un = $("user-name");
    if (un) un.textContent = (me.user && (me.user.first_name || me.user.username)) || "Admin";
    renderStats(me.stats);
    await loadCalendar();
    await loadRecent();
  } catch (e) {
    console.warn("loadHome failed", e);
    // still show empty UI
    renderStats({ draft: 0, approved: 0, scheduled: 0, published: 0, publish_failed: 0 });
    await loadCalendar();
  }
}

function renderStats(s) {
  const el = $("stats");
  if (!el) return;
  const ready = (s.draft || 0) + (s.approved || 0);
  el.innerHTML = `
    <div class="stat s-draft"><b>${LANG === "fa" ? faDigits(ready) : ready}</b><span>${t("stat_ready")}</span></div>
    <div class="stat s-scheduled"><b>${LANG === "fa" ? faDigits(s.scheduled || 0) : (s.scheduled || 0)}</b><span>${t("stat_scheduled")}</span></div>
    <div class="stat s-published"><b>${LANG === "fa" ? faDigits(s.published || 0) : (s.published || 0)}</b><span>${t("stat_published")}</span></div>
    <div class="stat s-failed"><b>${LANG === "fa" ? faDigits(s.publish_failed || 0) : (s.publish_failed || 0)}</b><span>${t("stat_failed")}</span></div>`;
}

/* ---------------- Admin: Moderation / Stats / News ---------------- */
function errLine(msg) {
  return `<div class="hint" style="color:var(--danger,#e05d5d)">${esc(msg)}</div>`;
}

async function loadMod() {
  const wordsEl = $("mod-words"), chatsEl = $("mod-chats"),
        logEl = $("mod-log"), bannedEl = $("mod-banned");
  if (!wordsEl || !chatsEl || !logEl || !bannedEl) return;
  try {
    const w = await api("/api/mod/words");
    const cats = Object.keys(w);
    const sel = $("mod-cat");
    if (sel) sel.innerHTML = cats.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
    if (!cats.length) wordsEl.innerHTML = `<div class="hint">${t("mod_empty_words")}</div>`;
    else wordsEl.innerHTML = cats.map((c) => `
      <div class="card sub"><div class="card-title small">${esc(c)}</div>
        <div class="chips">${(w[c] || []).map((term) => `
          <span class="chip">${esc(term)}<button type="button" class="chip-x" data-cat="${esc(c)}" data-term="${esc(term)}">×</button></span>`).join("")}
        </div></div>`).join("");
  } catch (e) { wordsEl.innerHTML = errLine(e.message); }
  try {
    const chats = await api("/api/mod/chats");
    if (!Array.isArray(chats) || !chats.length) chatsEl.innerHTML = `<div class="hint">${t("mod_empty_chats")}</div>`;
    else chatsEl.innerHTML = chats.map((c) => `
      <div class="row ch-row">
        <span class="grow">${esc(c.title || c.username || c.chat_id || c.id)} <em class="hint">${esc(String(c.chat_id ?? c.id ?? ""))}</em></span>
        <button class="btn ghost" data-toggle="${esc(String(c.chat_id ?? c.id))}">${c.enabled ? t("mod_disable") : t("mod_enable")}</button>
      </div>`).join("");
  } catch (e) { chatsEl.innerHTML = errLine(e.message); }
  try {
    const log = await api("/api/mod/log");
    if (!Array.isArray(log) || !log.length) logEl.innerHTML = `<div class="hint">${t("mod_empty_log")}</div>`;
    else logEl.innerHTML = log.slice(0, 50).map((l) => `
      <div class="log-line"><span>${esc(String(l.ts || l.time || ""))}</span>
        <span>${esc(String(l.category || ""))}</span>
        <span>${esc(String(l.text || l.content || ""))}</span></div>`).join("");
  } catch (e) { logEl.innerHTML = errLine(e.message); }
  try {
    const banned = await api("/api/mod/banned");
    if (!Array.isArray(banned) || !banned.length) bannedEl.innerHTML = `<div class="hint">${t("mod_empty_banned")}</div>`;
    else bannedEl.innerHTML = banned.map((u) => `
      <div class="row ch-row">
        <span class="grow">${esc(u.username || u.first_name || u.user_id)} <em class="hint">${esc(String(u.chat_id))} / ${esc(String(u.user_id))}</em></span>
        <button class="btn ghost" data-chat="${esc(String(u.chat_id))}" data-user="${esc(String(u.user_id))}">${t("mod_unban")}</button>
      </div>`).join("");
  } catch (e) { bannedEl.innerHTML = errLine(e.message); }
}

function modWordsHandlers() {
  const addBtn = $("mod-add");
  if (addBtn) addBtn.addEventListener("click", async () => {
    const cat = ($("mod-cat")?.value || "").trim();
    const term = ($("mod-term")?.value || "").trim();
    if (!cat || !term) { toast(t("mod_need_term")); return; }
    addBtn.disabled = true;
    try {
      await api("/api/mod/words", { method: "POST", json: { category: cat, term, is_regex: !!($("mod-regex")?.checked) } });
      const termEl = $("mod-term"); if (termEl) termEl.value = "";
      toast(t("toast_saved"));
      await loadMod();
    } catch (e) { toast(e.message); }
    addBtn.disabled = false;
  });
  const wordsEl = $("mod-words");
  if (wordsEl) wordsEl.addEventListener("click", async (e) => {
    const btn = e.target.closest(".chip-x");
    if (!btn) return;
    btn.disabled = true;
    try {
      await api("/api/mod/words", { method: "DELETE", json: { category: btn.dataset.cat, term: btn.dataset.term } });
      await loadMod();
    } catch (err) { toast(err.message); btn.disabled = false; }
  });
}
function modChatsHandlers() {
  const el = $("mod-chats");
  if (el) el.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-toggle]");
    if (!btn) return;
    btn.disabled = true;
    try {
      await api(`/api/mod/chats/${encodeURIComponent(btn.dataset.toggle)}/toggle`, { method: "POST" });
      await loadMod();
    } catch (err) { toast(err.message); btn.disabled = false; }
  });
  const bEl = $("mod-banned");
  if (bEl) bEl.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-chat]");
    if (!btn) return;
    btn.disabled = true;
    try {
      await api(`/api/mod/banned/${encodeURIComponent(btn.dataset.chat)}/${encodeURIComponent(btn.dataset.user)}/unban`, { method: "POST" });
      await loadMod();
    } catch (err) { toast(err.message); btn.disabled = false; }
  });
}

async function loadStats() {
  const ov = $("stats-overview"), more = $("stats-more");
  if (!ov || !more) return;
  let stats = {};
  try {
    const me = state.me || await api("/api/me");
    state.me = me;
    stats = me.stats || {};
  } catch (e) { /* leave zeros */ }
  const num = (n) => LANG === "fa" ? faDigits(n) : n;
  ov.innerHTML = `
    <div class="stat s-draft"><b>${num((stats.draft || 0) + (stats.approved || 0))}</b><span>${t("stat_ready")}</span></div>
    <div class="stat s-scheduled"><b>${num(stats.scheduled || 0)}</b><span>${t("stat_scheduled")}</span></div>
    <div class="stat s-published"><b>${num(stats.published || 0)}</b><span>${t("stat_published")}</span></div>
    <div class="stat s-failed"><b>${num(stats.publish_failed || 0)}</b><span>${t("stat_failed")}</span></div>
    <div class="stat s-rejected"><b>${num(stats.rejected || 0)}</b><span>${t("stat_rejected")}</span></div>`;
  const rows = [];
  const jobs = [
    ["channels", "/api/channels", (d) => Array.isArray(d) ? d.length : (d && d.total)],
    ["media", "/api/media/library", (d) => (d && d.items) ? d.items.length : (Array.isArray(d) ? d.length : null)],
    ["templates", "/api/templates", (d) => Array.isArray(d) ? d.length : null],
    ["news", "/api/news/config", (d) => (d && Array.isArray(d.sources)) ? d.sources.length : null],
  ];
  for (const [key, url, pick] of jobs) {
    try {
      const d = await api(url);
      const v = pick(d);
      rows.push(`<div class="stat"><b>${v == null ? t("stats_unavailable") : num(v)}</b><span>${t("stat_" + key)}</span></div>`);
    } catch (e) {
      rows.push(`<div class="stat"><b>${t("stats_unavailable")}</b><span>${t("stat_" + key)}</span></div>`);
    }
  }
  more.innerHTML = `<div class="stats">${rows.join("")}</div>`;
}

async function loadNewsAdmin() {
  const meta = $("na-meta"), srcEl = $("na-sources");
  if (!srcEl) return;
  let cfg = { enabled: false, auto_publish: false, interval_min: 30, sources: [] };
  try {
    cfg = await api("/api/news/config");
  } catch (e) {
    srcEl.innerHTML = errLine(e.message);
    return;
  }
  const en = $("na-enabled"), au = $("na-auto"), iv = $("na-interval");
  if (en) en.checked = !!cfg.enabled;
  if (au) au.checked = !!cfg.auto_publish;
  if (iv) iv.value = cfg.interval_min || 30;
  if (meta) {
    const parts = [];
    if (typeof cfg.seen_count === "number") parts.push(t("news_meta_seen") + ": " + (LANG === "fa" ? faDigits(cfg.seen_count) : cfg.seen_count));
    if (cfg.last_fetch) parts.push(t("news_meta_last") + ": " + esc(cfg.last_fetch));
    if (cfg.last_error) parts.push(`<span style="color:var(--danger,#e05d5d)">${t("news_meta_error")}: ${esc(cfg.last_error)}</span>`);
    meta.innerHTML = parts.length ? parts.join(" · ") : t("news_meta_none");
  }
  state.newsSources = (Array.isArray(cfg.sources) ? cfg.sources : []).map((s) => ({
    name: s.name || "", url: s.url || "", cat: s.cat || s.category || "",
  }));
  renderNewsSources();
}

function renderNewsSources() {
  const srcEl = $("na-sources");
  if (!srcEl) return;
  const list = state.newsSources || [];
  if (!list.length) { srcEl.innerHTML = `<div class="hint">${t("src_empty")}</div>`; return; }
  srcEl.innerHTML = list.map((s, i) => `
    <div class="row ch-row src-row" data-i="${i}">
      <input type="text" class="grow src-name" value="${esc(s.name)}" placeholder="${esc(t("src_name_ph"))}">
      <input type="text" class="grow src-url" value="${esc(s.url)}" placeholder="${esc(t("src_url_ph"))}">
      <input type="text" class="src-cat" value="${esc(s.cat)}" placeholder="${esc(t("src_cat_ph"))}">
      <button type="button" class="btn ghost src-del" data-i="${i}">${t("src_del")}</button>
    </div>`).join("");
  $$(".src-row", srcEl).forEach((row) => {
    const i = Number(row.dataset.i);
    const read = () => {
      state.newsSources[i].name = row.querySelector(".src-name").value.trim();
      state.newsSources[i].url = row.querySelector(".src-url").value.trim();
      state.newsSources[i].cat = row.querySelector(".src-cat").value.trim();
    };
    row.querySelectorAll("input").forEach((inp) => inp.addEventListener("input", read));
    row.querySelector(".src-del").addEventListener("click", () => {
      state.newsSources.splice(i, 1);
      renderNewsSources();
    });
  });
}

function clampInt(v, lo, hi, dflt) {
  const n = parseInt(v, 10);
  if (Number.isNaN(n)) return dflt;
  return Math.max(lo, Math.min(hi, n));
}
async function saveNewsConfig() {
  const list = state.newsSources || [];
  for (const s of list) {
    if (!s.name || !s.cat || !/^https?:\/\//i.test(s.url)) { toast(t("src_invalid")); return false; }
  }
  const payload = {
    enabled: !!($("na-enabled")?.checked),
    auto_publish: !!($("na-auto")?.checked),
    interval_min: clampInt($("na-interval")?.value, 10, 240, 30),
    sources: list,
  };
  try {
    await api("/api/news/config", { method: "PUT", json: payload });
    toast(t("news_saved"));
    return true;
  } catch (e) { toast(e.message); return false; }
}

function newsHandlers() {
  const save = $("na-save");
  if (save) save.addEventListener("click", () => saveNewsConfig());
  const add = $("na-add");
  if (add) add.addEventListener("click", () => {
    const name = ($("na-name")?.value || "").trim();
    const url = ($("na-url")?.value || "").trim();
    const cat = ($("na-cat")?.value || "").trim();
    if (!name || !url || !cat || !/^https?:\/\//i.test(url)) { toast(t("src_invalid")); return; }
    state.newsSources = state.newsSources || [];
    state.newsSources.push({ name, url, cat });
    const nEl = $("na-name"), uEl = $("na-url"), cEl = $("na-cat");
    if (nEl) nEl.value = ""; if (uEl) uEl.value = ""; if (cEl) cEl.value = "";
    renderNewsSources();
  });
  const fetchBtn = $("na-fetch");
  if (fetchBtn) fetchBtn.addEventListener("click", async () => {
    fetchBtn.disabled = true;
    const lbl = fetchBtn.querySelector("span"); if (lbl) lbl.textContent = "…";
    try {
      const r = await api("/api/news/fetch_now", { method: "POST" });
      if (r.published) toast(t("news_fetched") + ((r.title_fa || r.title_en || "").slice(0, 60)));
      else toast(t("news_drafted") + " #" + r.draft_id);
      loadNewsAdmin();
    } catch (e) { toast(e.message); }
    if (lbl) lbl.textContent = t("news_now");
    fetchBtn.disabled = false;
  });
}

function fillAiFormatNet() {
  const sel = $("ai-format-net");
  if (!sel) return;
  const nets = activeNetworks();
  const ids = Object.keys(nets);
  if (!ids.length) { sel.innerHTML = `<option value="telegram">Telegram</option>`; return; }
  sel.innerHTML = ids.map((id) => `<option value="${esc(id)}" ${id === "telegram" ? "selected" : ""}>${esc(nets[id].label || id)}</option>`).join("");
}

function initAdminUi() {
  modWordsHandlers();
  modChatsHandlers();
  newsHandlers();
  const fmt = $("ai-format");
  if (fmt) fmt.addEventListener("click", async () => {
    const edText = $("ed-text");
    const content = edText ? edText.value.trim() : "";
    if (!content) { toast(t("need_content")); return; }
    const net = $("ai-format-net")?.value || "telegram";
    fmt.disabled = true;
    try {
      const r = await api("/api/ai/format", { method: "POST", json: { content, network: net } });
      if (edText) edText.value = r.text || r.content || content;
      updateCount();
      renderNetworkVariants();
      toast(t("toast_rewritten"));
    } catch (e) { toast(e.status === 503 ? t("ai_not_configured") : e.message); }
    fmt.disabled = false;
  });
  fillAiFormatNet();
}

function renderWeekdays() {
  const names = t("weekdays") || ["Sa","Su","Mo","Tu","We","Th","Fr"];
  const el = $("cal-weekdays");
  if (el) el.innerHTML = names.map((w) => `<span>${w}</span>`).join("");
}

async function loadCalendar() {
  if (calState.fa.jy === 0) initCalState();
  const titleEl = $("cal-title");
  const wh = $("cal-weekdays");
  const grid = $("cal-grid");
  if (!titleEl || !wh || !grid) return;

  const { title: ttl, weekdays, cells } = buildCalendarMonth();
  titleEl.textContent = ttl;
  wh.innerHTML = weekdays.map((w) => `<span>${w}</span>`).join("");

  // Jalali months often span two Gregorian months → fetch plan for every
  // touched month (key = Gregorian "YYYY-MM-DD").
  const datedCells = cells.filter((c) => !c.empty && c.key);
  const months = new Set();
  datedCells.forEach((c) => months.add(c.key.slice(0, 7)));

  const byDay = {};
  for (const mk of months) {
    if (!state.planCache[mk]) {
      try { state.planCache[mk] = await api("/api/plan?month=" + mk); }
      catch (e) { state.planCache[mk] = []; }
    }
    const items = Array.isArray(state.planCache[mk]) ? state.planCache[mk] : [];
    items.forEach((it) => {
      if (!it || !it.day) return;
      let full;
      if (/^\d{4}-\d{2}-\d{2}/.test(String(it.day))) full = String(it.day).slice(0, 10);
      else full = mk + "-" + String(it.day).padStart(2, "0");
      (byDay[full] = byDay[full] || []).push(it);
    });
  }

  let html = "";
  cells.forEach((c) => {
    if (c.empty) { html += `<span class="cal-cell empty"></span>`; return; }
    const list = byDay[c.key] || [];
    // Render at most MAX_CAL_DOTS individual dots; show every +N when more.
    const MAX_CAL_DOTS = 5;
    const dotHtml = (it) => {
      const cls = it.status === "published" ? "published"
        : it.status === "publish_failed" ? "failed" : "scheduled";
      return `<i class="dot-${cls}"></i>`;
    };
    let dots;
    if (list.length > MAX_CAL_DOTS) {
      dots = list.slice(0, MAX_CAL_DOTS).map(dotHtml).join("")
        + `<i class="dot-more">+${list.length - MAX_CAL_DOTS}</i>`;
    } else {
      dots = list.map(dotHtml).join("");
    }
    html += `<span class="cal-cell${c.today ? " today" : ""}" data-key="${c.key}" data-day="${c.day}">${c.label}<span class="dots">${dots}</span></span>`;
  });
  grid.innerHTML = html;

  $$("#cal-grid .cal-cell[data-key]").forEach((cell) => {
    cell.addEventListener("click", () => {
      $$("#cal-grid .cal-cell").forEach((c) => c.classList.remove("sel"));
      cell.classList.add("sel");
      showDayList(cell.dataset.key, byDay[cell.dataset.key] || []);
    });
  });
}

function showDayList(dateKey, list) {
  const card = $("day-list-card");
  const title = $("day-list-title");
  const listEl = $("day-list");
  if (!card || !title || !listEl) return;

  card.style.display = "";
  const [gy, gm, gd] = dateKey.split("-").map(Number);
  let label;
  if (LANG === "fa") {
    const [jy, jm, jd] = g2j(gy, gm, gd);
    label = `${num(jd)} ${MONTHS_FA[jm - 1]} ${num(jy)}`;
  } else {
    label = `${MONTHS_EN[gm - 1]} ${gd}, ${gy}`;
  }
  title.textContent = `${t("day_posts")} ${label}`;

  listEl.innerHTML = list.length
    ? list.map((it) => `
        <div class="day-item">
          <span class="badge ${it.status}">${STATUS_LABEL[it.status] ? STATUS_LABEL[it.status]() : it.status}</span>
          <span class="txt">${esc(it.content || "(media)")}</span>
        </div>`).join("")
    : `<div class="empty-state">${t("empty_day")}</div>`;
}

async function loadRecent() {
  const el = $("home-recent");
  if (!el) return;
  try {
    const rows = await api("/api/drafts?limit=5");
    el.innerHTML = rows.length
      ? rows.map((r) => `
          <div class="day-item">
            <span class="badge ${r.status}">${STATUS_LABEL[r.status] ? STATUS_LABEL[r.status]() : r.status}</span>
            <span class="txt">${esc(r.content || "(media)")}</span>
            <span class="post-time">${fmtTime(r.published_at || r.scheduled_at || r.created_at)}</span>
          </div>`).join("")
      : `<div class="empty-state">${t("empty_recent")}</div>`;
  } catch (e) {
    el.innerHTML = `<div class="empty-state">${t("empty_recent")}</div>`;
  }
}

/* ---------------- Connection Center (multi-network) ---------------- */
/* ============ Technical Connection guidance (honest, actionable) ============ */
/* Public profile is NOT a technical connection. Statuses never claim "Connected"
   unless a real connection test passes. OAuth stays documented-only (out of scope). */
const TECH_GUIDANCE = {
  telegram: {
    fa: {
      method: "API بات تلگرام (Bot API)",
      prereq: "توکن بات از @BotFather؛ بات باید مدیر کانال هدف باشد (دسترسی انتشار).",
      where: "فایل .env پروژه (TELEGRAM_BOT_TOKEN) — هنگام راه‌اندازی سرویس خوانده می‌شود.",
      steps: [
        "بات را با @BotFather بسازید و توکن را کپی کنید.",
        "توکن را در فایل .env با کلید TELEGRAM_BOT_TOKEN قرار دهید (هرگز در چت/UI نمایش ندهید).",
        "بات را به‌عنوان مدیر کانال هدف اضافه کنید و دسترسی «انتشار پست» بدهید.",
        "سرویس voidfeed-studio را راه‌اندازی مجدد کنید تا توکن خوانده شود.",
        "در استودیو کانال را ثبت و یک پست آزمایشی منتشر کنید.",
      ],
      test: "یک پست پیش‌نویس (بدون برنامه‌ریزی) در کانال ثبت‌شده منتشر کنید؛ موفقیت = اتصال واقعی.",
      enabled: "انتشار مستقیم به کانال تلگرام از استودیو (متن، تصویر، ویدیو).",
      limits: "بدون OAuth؛ ویدیو تا ~50MB؛ نیاز به مدیر بودن بات در کانال.",
      next: "توکن را تنظیم کنید، سپس با انتشار آزمایشی تأیید کنید.",
    },
    en: {
      method: "Telegram Bot API",
      prereq: "Bot token from @BotFather; the bot must be admin of the target channel (post permission).",
      where: "Project .env file (TELEGRAM_BOT_TOKEN) — read at service startup.",
      steps: [
        "Create the bot via @BotFather and copy the token.",
        "Put the token in the .env file as TELEGRAM_BOT_TOKEN (never show it in chat/UI).",
        "Add the bot as admin of the target channel with 'post messages' permission.",
        "Restart the voidfeed-studio service so the token is loaded.",
        "Register the channel in Studio and publish a test post.",
      ],
      test: "Publish an unscheduled draft to a registered channel; success = a real connection.",
      enabled: "Direct publishing to the Telegram channel from Studio (text, photo, video).",
      limits: "No OAuth; video up to ~50MB; bot must be channel admin.",
      next: "Configure the token, then confirm with a test publish.",
    },
  },
  instagram: {
    fa: { method: "OAuth — Instagram Graph API (Meta)", prereq: "حساب توسعه‌دهنده متا؛ اپ با محصول Instagram؛ اکانت تجاری/سازنده.", where: "developers.facebook.com — کنسول متا.", steps: ["اپ بسازید و محصول Instagram را اضافه کنید.", "URI بازگشت را ثبت کنید.", "دسترسی‌های لازم (pages_read, instagram_manage_content) را درخواست کنید."], test: "تا پیاده‌سازی، آزمون ممکن نیست.", enabled: "—", limits: "پیاده‌سازی نشده؛ انتشار به دسترسی پیشرفته و تأیید اپ نیاز دارد.", next: "منتظر تصمیم پیاده‌سازی؛ دکمه اتصال واقعی وجود ندارد." },
    en: { method: "OAuth — Instagram Graph API (Meta)", prereq: "Meta developer account; app with Instagram product; business/creator IG account.", where: "developers.facebook.com — Meta console.", steps: ["Create the app and add the Instagram product.", "Register the redirect URI.", "Request required permissions (pages_read, instagram_manage_content)."], test: "Not testable until implemented.", enabled: "—", limits: "Not implemented; publishing requires advanced access & app review.", next: "Awaiting implementation decision; no real Connect button exists." },
  },
  facebook: {
    fa: { method: "OAuth — Meta Graph API (Page)", prereq: "اپ متا؛ دسترسی مدیر صفحه؛ مجوز pages_manage_posts.", where: "developers.facebook.com.", steps: ["اپ بسازید و مجوزهای صفحه را تنظیم کنید.", "URI بازگشت را ثبت کنید."], test: "تا پیاده‌سازی، آزمون ممکن نیست.", enabled: "—", limits: "پیاده‌سازی نشده.", next: "منتظر تصمیم پیاده‌سازی." },
    en: { method: "OAuth — Meta Graph API (Page)", prereq: "Meta app; Page admin access; pages_manage_posts permission.", where: "developers.facebook.com.", steps: ["Create the app and configure Page permissions.", "Register the redirect URI."], test: "Not testable until implemented.", enabled: "—", limits: "Not implemented.", next: "Awaiting implementation decision." },
  },
  youtube: {
    fa: { method: "OAuth — YouTube Data API v3 (Google)", prereq: "پروژه Google Cloud؛ فعال‌سازی YouTube Data API؛ کانال یوتیوب.", where: "console.cloud.google.com.", steps: ["پروژه بسازید و API را فعال کنید.", "OAuth Client ID بسازید و URI بازگشت را ثبت کنید.", "محدوده‌های youtube.upload و youtube.readonly را درخواست کنید."], test: "تا پیاده‌سازی، آزمون ممکن نیست.", enabled: "—", limits: "پیاده‌سازی نشده.", next: "منتظر تصمیم پیاده‌سازی." },
    en: { method: "OAuth — YouTube Data API v3 (Google)", prereq: "Google Cloud project; YouTube Data API enabled; YouTube channel.", where: "console.cloud.google.com.", steps: ["Create a project and enable the API.", "Create an OAuth Client ID and register the redirect URI.", "Request youtube.upload and youtube.readonly scopes."], test: "Not testable until implemented.", enabled: "—", limits: "Not implemented.", next: "Awaiting implementation decision." },
  },
  x: {
    fa: { method: "OAuth — X API (developer portal)", prereq: "حساب توسعه‌دهنده X؛ اپ با دسترسی خواندن/نوشتن.", where: "developer.x.com.", steps: ["اپ بسازید و مجوزهای نوشتن را درخواست کنید.", "URI بازگشت را ثبت کنید."], test: "تا پیاده‌سازی، آزمون ممکن نیست.", enabled: "—", limits: "پیاده‌سازی نشده.", next: "منتظر تصمیم پیاده‌سازی." },
    en: { method: "OAuth — X API (developer portal)", prereq: "X developer account; app with read/write access.", where: "developer.x.com.", steps: ["Create the app and request write permissions.", "Register the redirect URI."], test: "Not testable until implemented.", enabled: "—", limits: "Not implemented.", next: "Awaiting implementation decision." },
  },
  tiktok: {
    fa: { method: "OAuth — TikTok for Business", prereq: "حساب توسعه‌دهنده TikTok؛ اپ با مجوز ویدیو.", where: "developers.tiktok.com.", steps: ["اپ بسازید و محصول Content Posting را اضافه کنید.", "URI بازگشت را ثبت کنید."], test: "تا پیاده‌سازی، آزمون ممکن نیست.", enabled: "—", limits: "پیاده‌سازی نشده.", next: "منتظر تصمیم پیاده‌سازی." },
    en: { method: "OAuth — TikTok for Business", prereq: "TikTok developer account; app with video posting scope.", where: "developers.tiktok.com.", steps: ["Create the app and add the Content Posting product.", "Register the redirect URI."], test: "Not testable until implemented.", enabled: "—", limits: "Not implemented.", next: "Awaiting implementation decision." },
  },
  quora: {
    fa: { method: "بدون API عمومی انتشار (فقط پروفایل)", prereq: "—", where: "—", steps: [], test: "—", enabled: "—", limits: "کورا API عمومی برای انتشار ارائه نمی‌دهد.", next: "فقط حضور عمومی؛ بدون ادغام فنی." },
    en: { method: "No public publishing API (profile only)", prereq: "—", where: "—", steps: [], test: "—", enabled: "—", limits: "Quora offers no public publishing API.", next: "Public presence only; no technical integration." },
  },
  discord: {
    fa: { method: "ربات Discord (Developer Portal)", prereq: "اپ در Discord Developer Portal؛ توکن ربات.", where: "discord.com/developers/applications.", steps: ["اپ بسازید و توکن ربات بسازید.", "ربات را به سرور دعوت کنید."], test: "تا پیاده‌سازی، آزمون ممکن نیست.", enabled: "—", limits: "پیاده‌سازی نشده؛ لوگوی رسمی هنوز تأیید نشده.", next: "منتظر تصمیم پیاده‌سازی." },
    en: { method: "Discord bot (Developer Portal)", prereq: "App in Discord Developer Portal; bot token.", where: "discord.com/developers/applications.", steps: ["Create the app and generate a bot token.", "Invite the bot to a server."], test: "Not testable until implemented.", enabled: "—", limits: "Not implemented; official logo not yet verified.", next: "Awaiting implementation decision." },
  },
  clubhouse: {
    fa: { method: "بدون API رسمی عمومی", prereq: "—", where: "—", steps: [], test: "—", enabled: "—", limits: "کلاب‌هاوس API عمومی ارائه نمی‌دهد.", next: "فقط حضور عمومی؛ بدون ادغام فنی." },
    en: { method: "No official public API", prereq: "—", where: "—", steps: [], test: "—", enabled: "—", limits: "Clubhouse offers no public API.", next: "Public presence only; no technical integration." },
  },
};

async function loadConnections() {
  const el = $("conn-list");
  if (!el) return;
  try {
    const list = await api("/api/connections/spec");
    const fa = LANG === "fa";
    const social = list.map((p) => {
      const name = fa ? p.fa : p.en;
      const ident = p.display ? escFull(p.display) : (p.handle ? escFull(p.handle) : "—");
      const link = p.social_profile.url
        ? `<a class="conn-link" href="${esc(p.social_profile.url)}" target="_blank" rel="noopener">${t("conn_open_profile")} ↗</a>`
        : `<span class="hint">${t("prof_no_link")}</span>`;
      const logo = p.logo
        ? `<img class="plat-logo" src="${themedLogo(p)}" alt="${esc(name)}" loading="lazy">`
        : `<div class="plat-logo pending" title="${t("conn_pending_asset")}">…</div>`;
      return `<div class="plat-card ${p.id==="quora" ? "quora-card" : ""}">
        <div class="p-logo">${logo}</div>
        <div class="p-info">
          <div class="p-name">${escFull(name)}</div>
          <div class="p-sub">${ident}</div>
          <div class="p-foot">${link}</div>
        </div>
      </div>`;
    }).join("");
    const tech = list.map((p) => {
      const name = fa ? p.fa : p.en;
      const st = p.technical.status;
      const stLabel = t("conn_st_" + st) || st;
      const badgeCls = st === "setup_ready" ? "badge scheduled"
        : (st === "not_supported" || st === "not_implemented") ? "badge rejected" : "badge";
      const cap = (p.technical.capabilities && p.technical.capabilities.length)
        ? p.technical.capabilities.map((c) => t("conn_cap_" + c)).join("، ")
        : (fa ? "—" : "—");
      const kind = t("conn_kind_" + p.technical.kind) || p.technical.kind;
      const note = (p.technical.note_key && t(p.technical.note_key)) ? t(p.technical.note_key) : "";
      const logo = p.logo
        ? `<img class="plat-logo" src="${themedLogo(p)}" alt="${esc(name)}" loading="lazy">`
        : `<div class="plat-logo pending" title="${t("conn_pending_asset")}">…</div>`;
      const g = TECH_GUIDANCE[p.technical.guidance || p.id];
      const gu = (g && (fa ? g.fa : g.en)) || null;
      let detail = "";
      if (gu) {
        const stepList = (gu.steps && gu.steps.length)
          ? `<ol class="g-steps">${gu.steps.map(s => `<li>${escFull(s)}</li>`).join("")}</ol>`
          : `<div class="hint">${fa ? "—" : "—"}</div>`;
        const row = (k, v) => `<div class="g-row"><span class="g-k">${t(k)}</span><span class="g-v">${escFull(v)}</span></div>`;
        let rows = "";
        if (gu.method) rows += row("conn_g_method", gu.method);
        if (gu.prereq && gu.prereq !== "—") rows += row("conn_g_prereq", gu.prereq);
        if (gu.where && gu.where !== "—") rows += row("conn_g_where", gu.where);
        if (gu.steps && gu.steps.length) rows += `<div class="g-row"><span class="g-k">${t("conn_g_steps")}</span><span class="g-v">${stepList}</span></div>`;
        if (gu.test) rows += row("conn_g_test", gu.test);
        if (gu.enabled) rows += row("conn_g_enabled", gu.enabled);
        if (gu.limits) rows += row("conn_g_limits", gu.limits);
        if (gu.next) rows += row("conn_g_next", gu.next);
        if (p.id === "telegram") {
          rows += `<div class="g-row"><span class="g-k">${t("conn_g_test")}</span><span class="g-v">${p.technical.has_bot_token ? t("conn_token_present") : t("conn_token_absent")}</span></div>`;
        }
        detail = `<details class="g-details"><summary>${t("conn_note")} / ${fa ? "راهنما" : "guide"}</summary>${rows}</details>`;
      }
      return `<div class="plat-card tech ${p.id==="quora" ? "quora-card" : ""}">
        <div class="p-logo">${logo}</div>
        <div class="p-info">
          <div class="p-name">${escFull(name)}</div>
          <div class="p-badge"><span class="${badgeCls}">${escFull(stLabel)}</span></div>
          <div class="p-kind">${escFull(kind)}</div>
          <div class="p-cap">${escFull(cap)}${note ? ` · ${escFull(note)}` : ""}</div>
          ${detail}
        </div>
      </div>`;
    }).join("");
    el.innerHTML = `
      <div class="conn-panel">
        <div class="conn-panel-title">${t("conn_social_col")}</div>
        <div class="plat-grid">${social}</div>
      </div>
      <div class="conn-panel">
        <div class="conn-panel-title">${t("conn_tech_col")}</div>
        <div class="plat-grid">${tech}</div>
      </div>`;
  } catch (e) {
    el.innerHTML = `<div class="empty-state">${escFull(e.message || "")}</div>`;
  }
}

/* ---------------- Media library + Templates ---------------- */
function libSheet(open) { const bd = $("library-backdrop"); if (bd) bd.classList.toggle("open", !!open); }
function tplSheet(open) { const bd = $("templates-backdrop"); if (bd) bd.classList.toggle("open", !!open); }

async function loadLibrary() {
  const el = $("lib-list");
  if (!el) return;
  try {
    const items = await api("/api/media/library");
    if (!items.length) { el.innerHTML = `<div class="empty-state">${escFull(t("lib_empty"))}</div>`; return; }
    el.innerHTML = items.map((it) => `
      <div class="lib-item">
        ${it.kind === "video"
          ? `<video src="${escFull(it.url)}" muted playsinline preload="metadata"></video>`
          : `<img src="${escFull(it.url)}" alt="">`}
        <div class="lib-meta">
          <input class="lib-alt" data-id="${it.id}" value="${escFull(it.alt_text || "")}" placeholder="alt">
          <input class="lib-cap" data-id="${it.id}" value="${escFull(it.caption || "")}" placeholder="caption">
          <div class="lib-row">
            <button class="btn ghost" data-lib-attach="${it.url}" data-kind="${it.kind}">${t("lib_attach")}</button>
            <button class="pbtn danger" data-lib-del="${it.id}">${t("lib_del")}</button>
          </div>
        </div>
      </div>`).join("");
    el.querySelectorAll("[data-lib-attach]").forEach((b) => {
      b.addEventListener("click", () => {
        state.mediaUrl = b.dataset.libAttach;
        state.mediaKind = b.dataset.kind;
        renderMedia();
        libSheet(false);
        toast("✓");
      });
    });
    const saveMeta = async (input) => {
      const id = input.dataset.id;
      try {
        const altEl = el.querySelector(`.lib-alt[data-id="${id}"]`);
        const capEl = el.querySelector(`.lib-cap[data-id="${id}"]`);
        await api(`/api/media/library/${id}`, { method: "PUT", json: { alt_text: altEl ? altEl.value : "", caption: capEl ? capEl.value : "" } });
        toast(t("lib_saved"));
      } catch (e) { toast(e.message); }
    };
    el.querySelectorAll(".lib-alt").forEach((i) => i.addEventListener("change", () => saveMeta(i)));
    el.querySelectorAll(".lib-cap").forEach((i) => i.addEventListener("change", () => saveMeta(i)));
    el.querySelectorAll("[data-lib-del]").forEach((b) => {
      b.addEventListener("click", async () => {
        if (!confirm(t("lib_del") + "?")) return;
        try {
          await api(`/api/media/library/${b.dataset.libDel}`, { method: "DELETE" });
          toast(t("lib_deleted"));
          loadLibrary();
        } catch (e) { toast(e.status === 409 ? t("lib_refused") : e.message); }
      });
    });
  } catch (e) {
    el.innerHTML = `<div class="empty-state">${escFull(e.message)}</div>`;
  }
}

async function loadTemplates() {
  const el = $("tpl-list");
  if (!el) return;
  try {
    const rows = await api("/api/templates");
    if (!rows.length) { el.innerHTML = `<div class="empty-state">${escFull(t("tpl_empty"))}</div>`; return; }
    el.innerHTML = rows.map((tl) => `
      <div class="tpl-item">
        <div class="tpl-name">${escFull(tl.name)}</div>
        <div class="tpl-body">${esc(tl.body)}</div>
        <div class="tpl-row">
          <button class="btn ghost" data-tpl-append="${tl.id}">${t("tpl_append")}</button>
          <button class="btn ghost" data-tpl-replace="${tl.id}">${t("tpl_replace")}</button>
          <button class="pbtn danger" data-tpl-del="${tl.id}">${t("tpl_delete")}</button>
        </div>
      </div>`).join("");
    const edText = $("ed-text");
    el.querySelectorAll("[data-tpl-append]").forEach((b) => {
      b.addEventListener("click", async () => {
        const tpl = rows.find((x) => String(x.id) === b.dataset.tplAppend);
        if (!tpl || !edText) return;
        const cur = edText.value || "";
        edText.value = cur ? cur + "\n\n" + tpl.body : tpl.body;
        updateCount();
        renderNetworkVariants();
        tplSheet(false);
      });
    });
    el.querySelectorAll("[data-tpl-replace]").forEach((b) => {
      b.addEventListener("click", async () => {
        const tpl = rows.find((x) => String(x.id) === b.dataset.tplReplace);
        if (!tpl || !edText) return;
        edText.value = tpl.body;
        updateCount();
        renderNetworkVariants();
        tplSheet(false);
      });
    });
    el.querySelectorAll("[data-tpl-del]").forEach((b) => {
      b.addEventListener("click", async () => {
        if (!confirm(t("tpl_delete") + "?")) return;
        try {
          await api(`/api/templates/${b.dataset.tplDel}`, { method: "DELETE" });
          toast(t("tpl_deleted"));
          loadTemplates();
        } catch (e) { toast(e.message); }
      });
    });
  } catch (e) {
    el.innerHTML = `<div class="empty-state">${escFull(e.message)}</div>`;
  }
}

/* ---------------- Publish history ---------------- */
async function loadHistory(filter) {
  const el = $("history-list");
  if (!el) return;
  const f = filter !== undefined ? filter : (state.histFilter || "");
  state.histFilter = f;
  $$("#hist-filters .chip").forEach((c) => c.classList.toggle("active", (c.dataset.h || "") === f));
  try {
    const q = f ? `?event=${encodeURIComponent(f)}` : "";
    const rows = await api("/api/history" + q);
    if (!rows.length) {
      el.innerHTML = `<div class="empty-state">${escFull(t("hist_empty"))}</div>`;
      return;
    }
    const evBadge = (ev) => ev === "published" ? "badge published"
      : ev === "failed" ? "badge publish_failed"
      : ev === "scheduled" ? "badge scheduled" : "badge rejected";
    const evLabel = (ev) => t("hist_" + ev) || ev;
    el.innerHTML = rows.map((r) => `
      <div class="hist-item">
        <span class="badge ${evBadge(r.event)}">${escFull(evLabel(r.event))}</span>
        <div class="hist-info">
          <div class="hist-when">${escFull(schedLocal(r.created_at))}</div>
          <div class="hist-sub">
            ${t("hist_channel")}: <b>${escFull(r.channel_title || "—")}</b>
            ${r.draft_snippet ? `· ${esc(r.draft_snippet)}` : ""}
          </div>
          ${r.details ? `<div class="hist-details">${esc(r.details)}</div>` : ""}
        </div>
      </div>`).join("");
    el.querySelectorAll(".chip").length; // noop, keep
  } catch (e) {
    el.innerHTML = `<div class="empty-state">${escFull(e.message || t("hist_empty"))}</div>`;
  }
}

/* ---------------- Schedule management ---------------- */
function schedLocal(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const da = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const date = `${y}-${mo}-${da}`;
  const time = `${hh}:${mm}`;
  if (LANG === "fa") {
    const [jy, jm, jd] = g2j(y, +mo, +da);
    return `${faDigits(jd)}/${faDigits(jm)}/${faDigits(jy)} ${faDigits(time)}`;
  }
  return `${date} ${time}`;
}

async function loadSchedule() {
  const el = $("schedule-list");
  if (!el) return;
  try {
    if (!state.channels || !state.channels.length) {
      try { state.channels = await api("/api/channels"); } catch (e) {}
    }
    const chById = {};
    (state.channels || []).forEach((c) => { chById[c.id] = c; });
    const rows = await api("/api/drafts?status=scheduled");
    if (!rows.length) {
      el.innerHTML = `<div class="empty-state">${escFull(t("sched_empty"))}</div>`;
      return;
    }
    el.innerHTML = rows.map((r) => {
      const ch = chById[r.channel_id];
      const chName = ch ? escFull(ch.title) : "—";
      const mediaBadge = r.media_url ? uiIconHTML(r.media_kind === "video" ? "media" : "images", 15) : "";
      return `
        <div class="sched-item" data-id="${r.id}">
          <div class="sched-info">
            <div class="sched-when">${uiIconHTML("schedule",14)} ${escFull(schedLocal(r.scheduled_at))}</div>
            <div class="sched-sub">${t("sched_target")}: <b>${chName}</b> ${mediaBadge}</div>
            <div class="sched-preview">${esc(r.content || "")}</div>
          </div>
          <div class="sched-actions">
            <input type="datetime-local" class="sched-input" value="${toTehranInput(r.scheduled_at)}">
            <button class="btn ghost" data-sched-save="${r.id}">${t("sched_save")}</button>
            <button class="pbtn danger" data-sched-un="${r.id}">${t("sched_unschedule")}</button>
          </div>
        </div>`;
    }).join("");
    el.querySelectorAll("[data-sched-save]").forEach((b) => {
      b.addEventListener("click", async () => {
        const item = b.closest(".sched-item");
        const input = item ? item.querySelector(".sched-input") : null;
        const v = (input && input.value) || "";
        if (!v) { toast(t("sched_invalid")); return; }
        const id = b.dataset.schedSave;
        try {
          await api(`/api/drafts/${id}/schedule`, { method: "POST", json: { scheduled_at: v } });
          toast(t("sched_saved"));
          loadSchedule();
        } catch (e) { toast(e.message); }
      });
    });
    el.querySelectorAll("[data-sched-un]").forEach((b) => {
      b.addEventListener("click", async () => {
        if (!confirm(t("sched_unschedule") + "?")) return;
        const id = b.dataset.schedUn;
        try {
          await api(`/api/drafts/${id}/unschedule`, { method: "POST", json: {} });
          toast(t("sched_unscheduled"));
          loadSchedule();
        } catch (e) { toast(e.message); }
      });
    });
  } catch (e) {
    el.innerHTML = `<div class="empty-state">${escFull(e.message || t("sched_empty"))}</div>`;
  }
}

/* ---------------- Channels ---------------- */
async function loadChannels() {
  const listEl = $("ch-list");
  if (!listEl) return;
  try {
    const list = await api("/api/channels");
    state.channels = list || [];
    listEl.innerHTML = state.channels.length
      ? state.channels.map((c) => `
          <div class="ch-item">
            <div class="ch-avatar">${esc((c.title || "?").slice(0, 1))}</div>
            <div class="ch-info">
              <div class="ch-title">${esc(c.title)} ${c.is_default ? `<span class="default-tag">${t("default_tag")}</span>` : ""}</div>
              <div class="ch-sub">${c.username ? "@" + c.username : "ID " + (LANG === "fa" ? faDigits(c.chat_id) : c.chat_id)}</div>
            </div>
            ${c.is_default ? "" : `<button class="pbtn" data-def="${c.id}">${t("default_tag")}</button>`}
            <button class="pbtn danger" data-del="${c.id}">${uiIconHTML("cancel",14)}</button>
          </div>`).join("")
      : `<div class="empty-state">${t("empty_chats")}</div>`;

    listEl.querySelectorAll("[data-def]").forEach((b) => {
      b.addEventListener("click", async () => {
        try {
          await api(`/api/channels/${b.dataset.def}/default`, { method: "POST", json: {} });
          toast("✓");
          loadChannels();
        } catch (e) { toast(e.message); }
      });
    });
    listEl.querySelectorAll("[data-del]").forEach((b) => {
      b.addEventListener("click", async () => {
        try {
          await api(`/api/channels/${b.dataset.del}`, { method: "DELETE" });
          toast(t("toast_deleted"));
          loadChannels();
        } catch (e) { toast(e.message); }
      });
    });
  } catch (e) {
    listEl.innerHTML = `<div class="empty-state">${t("empty_chats")}</div>`;
  }
}

/* ---------------- Posts ---------------- */
async function loadPosts() {
  const listEl = $("post-list");
  if (!listEl) return;
  try {
    const q = state.filter ? `?status=${state.filter}` : "";
    const rows = await api("/api/drafts" + q);
    listEl.innerHTML = rows.length
      ? rows.map((r) => postCard(r)).join("")
      : `<div class="empty-state">${t("empty_posts")}</div>`;
    hydrateMedia(listEl);
    bindPostActions();
  } catch (e) {
    listEl.innerHTML = `<div class="empty-state">${t("empty_posts")}</div>`;
  }
}

function postCard(r) {
  const actions = [];
  actions.push(`<button class="pbtn" data-a="preview" data-id="${r.id}">${t("preview")}</button>`);
  if (["draft", "approved", "publish_failed"].includes(r.status)) {
    actions.push(`<button class="pbtn ok" data-a="publish" data-id="${r.id}">${t("publish_now")}</button>`);
    actions.push(`<button class="pbtn" data-a="schedule" data-id="${r.id}">${t("schedule")}</button>`);
  }
  if (r.status === "scheduled") {
    actions.push(`<button class="pbtn warn" data-a="unschedule" data-id="${r.id}">${t("toast_unscheduled")}</button>`);
  }
  if (["draft", "approved"].includes(r.status)) {
    actions.push(`<button class="pbtn" data-a="edit" data-id="${r.id}">${uiIconHTML("penLine",14)}</button>`);
    actions.push(`<button class="pbtn danger" data-a="reject" data-id="${r.id}">${t("toast_rejected")}</button>`);
  }
  actions.push(`<button class="pbtn danger" data-a="delete" data-id="${r.id}">${uiIconHTML("cancel",14)}</button>`);

  return `
    <div class="post-card">
      <div class="post-head">
        <span class="badge ${r.status}">${STATUS_LABEL[r.status] ? STATUS_LABEL[r.status]() : r.status}</span>
        <span class="post-time">${fmtTime(r.published_at || r.scheduled_at || r.created_at)}</span>
      </div>
      ${r.media_url ? `<img class="post-img" data-media="${escFull(r.media_url)}" alt="">` : ""}
      <div class="post-body">${esc(r.content)}</div>
      ${r.publish_error ? `<div class="post-error">⚠ ${esc(r.publish_error)}</div>` : ""}
      <div class="post-actions">${actions.join("")}</div>
    </div>`;
}

function bindPostActions() {
  $$(".post-actions .pbtn").forEach((b) => {
    b.addEventListener("click", async () => {
      const id = b.dataset.id, a = b.dataset.a;
      try {
        if (a === "edit") {
          const d = await api("/api/drafts/" + id);
          openEditor(d);
        } else if (a === "preview") {
          const d = await api("/api/drafts/" + id);
          await showPreview(d.content || "", d.media_url || null, d.channel_id || null, d.variants || null);
        } else if (a === "publish") {
          await api(`/api/drafts/${id}/publish`, { method: "POST", json: {} });
          toast(t("toast_published"));
          loadPosts();
        } else if (a === "schedule") {
          const when = prompt(t("sched_prompt"));
          if (!when) return;
          await api(`/api/drafts/${id}/schedule`, {
            method: "POST",
            json: { scheduled_at: when.trim().replace(" ", "T") },
          });
          toast(t("toast_scheduled"));
          loadPosts();
        } else if (a === "unschedule") {
          await api(`/api/drafts/${id}/unschedule`, { method: "POST", json: {} });
          toast(t("toast_unscheduled"));
          loadPosts();
        } else if (a === "reject") {
          await api(`/api/drafts/${id}/reject`, { method: "POST", json: {} });
          toast(t("toast_rejected"));
          loadPosts();
        } else if (a === "delete") {
          if (!confirm(t("toast_confirm_del"))) return;
          await api(`/api/drafts/${id}/delete`, { method: "POST", json: {} });
          toast(t("toast_deleted"));
          loadPosts();
        }
      } catch (e) { toast(e.message); }
    });
  });
}

/* ---------------- Editor + Networks ---------------- */
function toTehranInput(iso) {
  try {
    const p = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Tehran",
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }).formatToParts(new Date(iso));
    const g = (t) => (p.find((x) => x.type === t) || {}).value || "";
    return `${g("year")}-${g("month")}-${g("day")}T${g("hour")}:${g("minute")}`;
  } catch (e) { return ""; }
}

function openEditor(draft) {
  state.editingId = draft ? draft.id : null;
  state.mediaUrl = draft ? (draft.media_url || null) : null;
  state.editVariants = (draft && draft.variants && typeof draft.variants === "object")
    ? draft.variants : {};
  // Restore saved variant networks so their textareas are visible on edit.
  // Only ids that exist in the active network definitions; Set avoids dupes;
  // default selection mirrors loadNetworks (telegram, else first id).
  const availableNets = Object.keys(activeNetworks());
  state.selectedNets = new Set(availableNets.includes("telegram")
    ? ["telegram"]
    : (availableNets.slice(0, 1)));
  Object.keys(state.editVariants)
    .filter((id) => availableNets.includes(id))
    .forEach((id) => state.selectedNets.add(id));
  state.schedOn = draft ? !!draft.scheduled_at : false;

  const title = $("editor-title");
  if (title) title.textContent = draft ? `${t("editor_edit")}${LANG === "fa" ? faDigits(draft.id) : draft.id}` : t("editor_new");

  const textEl = $("ed-text");
  if (textEl) textEl.value = draft ? (draft.content || "") : "";

  const msg = $("ed-msg");
  if (msg) { msg.textContent = ""; msg.className = "msg"; }

  renderMedia();
  fillChannelSelect(draft ? draft.channel_id : null);
  renderNetworkChips();
  renderNetworkVariants();

  const sched = $("ed-sched");
  if (sched) {
    sched.style.display = state.schedOn ? "" : "none";
    sched.value = draft && draft.scheduled_at ? toTehranInput(draft.scheduled_at) : "";
  }
  updateCount();
  // Recover unsaved new-post draft (only for fresh composer; never overwrite
  // an existing draft's server content).
  if (!draft) {
    state.pendingRecover = readRecover();
    if (state.pendingRecover) setTimeout(renderRecoverNotice, 0);
  } else {
    state.pendingRecover = null;
  }
  const backdrop = $("editor-backdrop");
  if (backdrop) backdrop.classList.add("open");
}

function closeEditor() {
  const backdrop = $("editor-backdrop");
  if (backdrop) backdrop.classList.remove("open");
}

function fillChannelSelect(selectedId) {
  const sel = $("ed-channel");
  if (!sel) return;
  const def = state.channels.find((c) => c.is_default) || state.channels[0];
  sel.innerHTML = state.channels.length
    ? state.channels.map((c) =>
        `<option value="${c.id}" ${((selectedId || (def && def.id)) == c.id) ? "selected" : ""}>${escFull(c.title)}</option>`
      ).join("")
    : `<option value="">${t("no_channel")}</option>`;
}

function renderMedia() {
  const el = $("ed-media");
  if (!el) return;
  if (state.mediaUrl) {
    const m = escFull(state.mediaUrl);
    const isVid = /\.(mp4|mov|webm)(\?|$)/i.test(state.mediaUrl);
    el.innerHTML = (isVid
      ? `<video data-media="${m}" controls playsinline preload="metadata"></video>`
      : `<img data-media="${m}" alt="">`)
      + `<button class="pbtn danger" id="ed-media-del">${uiIconHTML("cancel",14)}</button>`;
    hydrateMedia(el);
  } else {
    el.innerHTML = "";
  }
  const del = $("ed-media-del");
  if (del) {
    del.addEventListener("click", () => {
      state.mediaUrl = null;
      renderMedia();
      updateCount();
      renderNetworkVariants();
    });
  }
}

function updateCount() {
  const textEl = $("ed-text");
  const countEl = $("ed-count");
  if (!textEl || !countEl) return;
  const len = textEl.value.length;
  const hasMedia = !!state.mediaUrl;
  let extra = "";
  if (hasMedia && len > 1000) extra = " " + t("chars_media");
  countEl.textContent = (LANG === "fa" ? faDigits(len) : len) + " " + t("chars") + extra;
  countEl.style.color = (hasMedia && len > 1000) ? "var(--danger)" : "";
}

/* ---- Networks UI ---- */
/* Shared official-brand logo helper. One implementation for the whole app:
   replaces emoji placeholders with the official platform mark, theme-aware
   for X. Platforms without verified marks (discord/clubhouse) get no mark. */
const PLATFORM_ASSETS = {
  telegram:   { dark: "telegram.svg",        light: "telegram.svg" },
  instagram:  { dark: "instagram.svg",       light: "instagram.svg" },
  facebook:   { dark: "facebook.svg",        light: "facebook.svg" },
  youtube:    { dark: "youtube.svg",         light: "youtube.svg" },
  x:          { dark: "x-white.svg",         light: "x.svg" },
  twitter:     { dark: "x-white.svg",         light: "x.svg" },
  tiktok:    { dark: "tiktok-symbol.svg",   light: "tiktok-symbol.svg" },
  quora:     { dark: "quora.svg",           light: "quora.svg" },
  discord:    { dark: "discord.svg",          light: "discord.svg" },
  clubhouse:  { dark: "clubhouse.svg",        light: "clubhouse.svg" },
};
function uiIconHTML(key, size) {
  const w = size || 18;
  return `<svg class="uiic" width="${w}" height="${w}" aria-hidden="true"><use href="#ui-${key}"/></svg>`;
}
function platformMarkHTML(id) {
  const a = PLATFORM_ASSETS[id];
  if (!a) return NET_FALLBACK_ICONS[id] || "";
  const f = currentTheme() === "dark" ? a.dark : a.light;
  return `<img class="plat-logo net-mark" src="/static-assets/icons/platforms/${f}" alt="" loading="lazy">`;
}
function netMark(net) {
  return (net && net.mark) ? net.mark : platformMarkHTML(net && net.id);
}
const NET_FALLBACK_ICONS = { telegram: "✈️", x: "𝕏", instagram: "📸", youtube: "▶️", facebook: "📘", tiktok: "🎵" };

function activeNetworks() {
  return state.networkDefs || NETWORKS;
}

async function loadNetworks() {
  try {
    const specs = await api("/api/networks");
    if (specs && Object.keys(specs).length) {
      const defs = {};
      for (const [id, s] of Object.entries(specs)) {
        const local = NETWORKS[id === "x" ? "twitter" : id] || {};
        defs[id] = {
          id,
          label: s.label || id,
          mark: platformMarkHTML(id),
          icon: local.icon || NET_FALLBACK_ICONS[id] || "",
          maxText: s.text_max || 4096,
          maxWithMedia: s.caption_max || s.text_max || 4096,
        };
      }
      state.networkDefs = defs;
      const ids = Object.keys(defs);
      state.selectedNets = new Set(ids.includes("telegram") ? ["telegram"] : ids.slice(0, 1));
    }
  } catch (e) { /* unreachable backend → keep built-in definitions */ }
}

function renderNetworkChips() {
  const container = $("net-chips");
  if (!container) return;

  container.innerHTML = Object.values(activeNetworks()).map((net) => {
    const on = state.selectedNets.has(net.id) ? "on" : "";
    return `<button type="button" class="net-chip ${on}" data-net="${net.id}">
      ${netMark(net)} ${net.label}
    </button>`;
  }).join("");

  container.querySelectorAll(".net-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.net;
      if (state.selectedNets.has(id)) {
        if (state.selectedNets.size > 1) state.selectedNets.delete(id);
      } else {
        state.selectedNets.add(id);
      }
      renderNetworkChips();
      renderNetworkVariants();
    });
  });
}

function getLimit(netId) {
  const net = activeNetworks()[netId];
  if (!net) return 4096;
  return state.mediaUrl ? net.maxWithMedia : net.maxText;
}

function updateVariantCounter(ta) {
  const netId = ta.dataset.net;
  const limit = getLimit(netId);
  const head = ta.closest(".variant-item")?.querySelector(".variant-head span:last-child");
  if (!head) return;
  const len = ta.value.length;
  const over = len > limit;
  const countStr = LANG === "fa" ? faDigits(len) + " / " + faDigits(limit) : `${len} / ${limit}`;
  head.className = over ? "over" : "";
  head.textContent = `${countStr} ${t("char_unit")} ${over ? "— " + t("net_over") : ""}`;
}

function renderNetworkVariants() {
  const container = $("net-variants");
  if (!container) return;

  const mainText = ($("ed-text") && $("ed-text").value) || "";
  // preserve edits already made in this editor session
  const current = {};
  container.querySelectorAll(".variant-text").forEach((ta) => {
    current[ta.dataset.net] = ta.value;
  });

  let html = "";
  state.selectedNets.forEach((netId) => {
    const net = activeNetworks()[netId];
    if (!net) return;
    const saved = state.editVariants[netId];
    const value = current[netId] !== undefined
      ? current[netId]
      : (saved !== undefined && saved !== null ? String(saved) : mainText);
    html += `
      <div class="variant-item" data-net="${netId}">
        <div class="variant-head">
          <span>${netMark(net)} ${net.label} ${t("variant_for")}</span>
          <span></span>
        </div>
        <textarea class="variant-text" data-net="${netId}" rows="3" placeholder="${net.label}...">${escFull(value)}</textarea>
      </div>`;
  });

  container.innerHTML = html;

  container.querySelectorAll(".variant-text").forEach((ta) => {
    const saved = state.editVariants[ta.dataset.net];
    if (current[ta.dataset.net] === undefined && saved !== undefined) {
      ta.dataset.dirty = "1"; // loaded from the saved draft: don't overwrite with main text
    }
    updateVariantCounter(ta);
    ta.addEventListener("input", () => {
      ta.dataset.dirty = "1";
      updateVariantCounter(ta);
    });
  });
}

// While the user types the main text, refresh untouched variant textareas
// (full re-render would destroy focus and per-network edits).
function syncVariantPrefill() {
  const mainText = ($("ed-text") && $("ed-text").value) || "";
  $$("#net-variants .variant-text").forEach((ta) => {
    if (ta.dataset.dirty !== "1") ta.value = mainText;
    updateVariantCounter(ta);
  });
}

// Per-network overrides to persist: only what the user actually customized.
function collectVariants() {
  const mainText = (($("ed-text") && $("ed-text").value) || "").trim();
  const out = {};
  $$("#net-variants .variant-text").forEach((ta) => {
    const val = (ta.value || "").trim();
    if (val && val !== mainText) out[ta.dataset.net] = val;
  });
  return out;
}

/* ---------------- Preview ---------------- */
async function ensureSettings() {
  if (!state.settings) {
    try { state.settings = await api("/api/settings"); }
    catch (e) { state.settings = { signature_enabled: "0", signature_text: "" }; }
  }
  return state.settings;
}

function finalPostText(content, settings) {
  let text = (content || "").trim();
  let sig = "";
  if (settings && settings.signature_enabled === "1") sig = (settings.signature_text || "").trim();
  if (sig && !text.includes(sig)) text = text ? (text + "\n\n" + sig) : sig;
  return text;
}

function renderTgText(text) {
  const safe = escFull(text);
  return safe.replace(/#[\w\u0600-\u06FF_]+/g, '<span class="tg-hashtag">$&</span>');
}

function tgTimeNow() {
  const d = new Date();
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  return LANG === "fa" ? faDigits(h + ":" + m) : h + ":" + m;
}

async function showPreview(content, mediaUrl, channelId, variants) {
  const settings = await ensureSettings();
  const netIds = Object.keys(activeNetworks());
  state.previewNet = netIds.includes("telegram") ? "telegram" : (netIds[0] || "telegram");
  state.previewVariants = (variants && typeof variants === "object") ? variants : {};
  state.previewMainText = content || "";
  state.previewMediaUrl = mediaUrl || null;
  state.previewChannelId = channelId || null;
  state.previewSettings = settings;

  const ch = state.channels.find((c) => String(c.id) === String(channelId))
    || state.channels.find((c) => c.is_default)
    || state.channels[0];
  const chTitle = ch ? ch.title : "Channel";
  const chLetter = escFull((chTitle || "?").trim().slice(0, 1));
  const isVideo = mediaUrl && /\.(mp4|mov|webm)(\?|$)/i.test(mediaUrl);

  const mock = $("tg-mock");
  if (mock) {
    mock.innerHTML = `
      <div class="tg-chat-head">
        <div class="tg-avatar">${chLetter}</div>
        <div class="tg-chat-name">
          <div class="tg-chat-title">${escFull(chTitle)}</div>
          <div class="tg-chat-sub">Channel</div>
        </div>
      </div>
      <div class="tg-msg">
        ${mediaUrl ? (isVideo
          ? `<video class="tg-photo" data-preview-media controls playsinline preload="metadata"></video>`
          : `<img class="tg-photo" data-preview-media alt="">`) : ""}
        <div class="tg-text" id="tg-text"></div>
        <div class="tg-meta"><span>${tgTimeNow()}</span> <span class="tg-ticks">✓✓</span></div>
      </div>`;
  }

  if (mediaUrl && mock) {
    loadPreviewMedia($q("[data-preview-media]"), mediaUrl);
  } else {
    clearPreviewMedia();
  }

  renderPreviewNetworks();
  updatePreviewText();

  const backdrop = $("preview-backdrop");
  if (backdrop) backdrop.classList.add("open");
}

/* ---- network-aware preview helpers ---- */

function renderPreviewNetworks() {
  const container = $("preview-net-chips");
  if (!container) return;
  container.innerHTML = Object.values(activeNetworks()).map((net) => {
    const on = state.previewNet === net.id ? "on" : "";
    return `<button type="button" class="net-chip ${on}" data-net="${net.id}">
      ${netMark(net)} ${net.label}
    </button>`;
  }).join("");
  container.querySelectorAll(".net-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.previewNet = btn.dataset.net;
      renderPreviewNetworks();
      updatePreviewText(); // text/counter only — modal stays open, media untouched
    });
  });
}

function updatePreviewText() {
  const textEl = $("tg-text");
  const countEl = $("preview-count");
  const noteEl = $("preview-note");
  if (!textEl) return;
  const netId = state.previewNet;
  const net = activeNetworks()[netId];
  const isTg = netId === "telegram";
  let text, limit, truncated = false;

  if (isTg) {
    // Telegram keeps its existing rules: signature append + caption/body cut
    text = finalPostText(state.previewMainText, state.previewSettings);
    limit = state.previewMediaUrl ? 1024 : 4096;
    truncated = text.length > limit;
    state.previewShownText = truncated ? text.slice(0, limit) : text;
    state.previewHasVariant = true; // telegram always shows the (final) main text
  } else {
    // other networks: variant as-is (no signature, no cut); main text as fallback
    limit = (net && (net.text_max || net.maxText)) || 4096;
    const variant = (state.previewVariants[netId] || "").trim();
    state.previewHasVariant = !!variant;
    text = variant || state.previewMainText;
    state.previewShownText = text;
  }

  textEl.innerHTML = state.previewShownText ? renderTgText(state.previewShownText) : "";

  if (countEl) {
    const len = state.previewShownText.length;
    const over = len > limit;
    const warn = !over && len >= Math.floor(limit * 0.9);
    const countStr = LANG === "fa" ? faDigits(len) + " / " + faDigits(limit) : `${len} / ${limit}`;
    countEl.className = "preview-count" + (over ? " over" : (warn ? " warn" : ""));
    countEl.textContent = ((net && net.label) || netId) + ": " + countStr
      + (over ? " — " + t("net_over") : "");
  }

  if (noteEl) {
    if (isTg && truncated) {
      noteEl.textContent = t("preview_trunc").replace("{n}", LANG === "fa" ? faDigits(limit) : limit);
      noteEl.style.display = "";
    } else if (!isTg && !state.previewHasVariant && state.previewShownText) {
      noteEl.textContent = t("preview_fallback")
        .replace("{net}", (net && net.label) || netId);
      noteEl.style.display = "";
    } else {
      noteEl.style.display = "none";
    }
  }
}

async function copyPreviewText() {
  const btn = $("preview-copy");
  const text = state.previewShownText || "";
  let ok = false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      ok = true;
    }
  } catch (e) { ok = false; }
  if (!ok) { // legacy fallback for non-secure contexts
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      ok = document.execCommand("copy");
      ta.remove();
    } catch (e) { ok = false; }
  }
  if (btn) {
    const original = btn.innerHTML;
    btn.innerHTML = ok ? t("copied") : t("preview_copy_fail");
    setTimeout(() => { btn.innerHTML = original; }, 1600);
  }
  toast(ok ? t("copied") : t("preview_copy_fail"));
}

function closePreview() {
  clearPreviewMedia();
  const backdrop = $("preview-backdrop");
  if (backdrop) backdrop.classList.remove("open");
}

/* ---------------- Save from editor ---------------- */
/* ---------------- Unsaved-draft recovery ---------------- */
const RECOVER_KEY = "vf_draft_recover";
const RECOVER_MAX_AGE = 24 * 3600 * 1000;
let _recTimer = null;

function saveRecover() {
  const textEl = $("ed-text");
  if (!textEl) return;
  const text = (textEl.value || "").trim();
  if (!text) return;
  try {
    localStorage.setItem(RECOVER_KEY, JSON.stringify({
      text, mediaUrl: state.mediaUrl || "", ts: Date.now(),
    }));
  } catch (e) {}
}
function scheduleRecover() {
  clearTimeout(_recTimer);
  _recTimer = setTimeout(saveRecover, 800);
}
function clearRecover() {
  clearTimeout(_recTimer);
  try { localStorage.removeItem(RECOVER_KEY); } catch (e) {}
}
function readRecover() {
  try {
    const raw = localStorage.getItem(RECOVER_KEY);
    if (!raw) return null;
    const o = JSON.parse(raw);
    if (!o || !o.text) return null;
    if (Date.now() - (o.ts || 0) > RECOVER_MAX_AGE) return null;
    return o;
  } catch (e) { return null; }
}
function renderRecoverNotice() {
  const textEl = $("ed-text");
  if (!textEl) return;
  let n = $("ed-recover");
  if (!n) {
    n = document.createElement("div");
    n.id = "ed-recover";
    n.className = "recover-notice";
    textEl.parentNode.insertBefore(n, textEl.nextSibling);
  }
  n.style.display = "";
  n.innerHTML = `
    <span>${escFull(t("rec_hint"))}</span>
    <button class="btn ghost" id="rec-restore">${t("rec_restore")}</button>
    <button class="pbtn" id="rec-dismiss" aria-label="close">${uiIconHTML("cancel",14)}</button>`;
  const rb = $("rec-restore");
  if (rb) rb.addEventListener("click", () => {
    const r = state.pendingRecover;
    if (r) {
      textEl.value = r.text;
      if (r.mediaUrl) {
        state.mediaUrl = r.mediaUrl;
        state.mediaKind = /\.(mp4|mov|webm)(\?|$)/i.test(r.mediaUrl) ? "video" : "photo";
      }
      renderMedia();
      updateCount();
      renderNetworkVariants();
      toast(t("rec_applied"));
    }
    n.style.display = "none";
  });
  const rd = $("rec-dismiss");
  if (rd) rd.addEventListener("click", () => { n.style.display = "none"; });
}

async function saveFromEditor(mode) {
  const textEl = $("ed-text");
  const content = textEl ? textEl.value.trim() : "";
  const channelEl = $("ed-channel");
  const channel = channelEl && channelEl.value ? parseInt(channelEl.value) : null;
  const schedEl = $("ed-sched");
  const schedVal = state.schedOn && schedEl && schedEl.value ? schedEl.value : null;
  const msg = $("ed-msg");

  if (msg) { msg.className = "msg"; msg.textContent = "…"; }

  if (!content && !state.mediaUrl) {
    if (msg) { msg.textContent = t("need_text"); msg.classList.add("err"); }
    return;
  }
  if (state.mediaUrl && content.length > 1000) {
    if (msg) { msg.textContent = t("too_long_media"); msg.classList.add("err"); }
    return;
  }

  try {
    const variants = collectVariants();
    let draft;
    if (state.editingId) {
      draft = await api(`/api/drafts/${state.editingId}`, {
        method: "PUT",
        json: { content, channel_id: channel, media_url: state.mediaUrl, variants },
      });
    } else {
      draft = await api("/api/drafts", {
        method: "POST",
        json: { content, channel_id: channel, media_url: state.mediaUrl, variants },
      });
    }

    clearRecover();

    if (mode === "publish") {
      await api(`/api/drafts/${draft.id}/publish`, { method: "POST", json: {} });
      toast(t("toast_published"));
      closeEditor();
      showPage("posts");
      return;
    }
    if (schedVal) {
      await api(`/api/drafts/${draft.id}/schedule`, {
        method: "POST",
        json: { scheduled_at: schedVal, channel_id: channel },
      });
      toast(t("toast_scheduled"));
    } else {
      toast(state.editingId ? t("toast_saved") : t("toast_draft_saved"));
    }
    closeEditor();
    showPage("posts");
  } catch (e) {
    if (msg) { msg.textContent = e.message; msg.classList.add("err"); }
  }
}

/* ---------------- Profile / News / AI (API dependent) ---------------- */
async function loadProfile() {
  try {
    await loadBrand();
    bindProfileSave();
    const s = await api("/api/settings");
    const se = $("sig-enabled");
    const st = $("sig-text");
    if (se) se.checked = s.signature_enabled === "1";
    if (st) st.value = s.signature_text || "";

    const aiStatus = $("ai-status");
    if (aiStatus) {
      try {
        const st = await api("/api/ai/status");
        const lines = [];
        lines.push(st.configured ? t("ai_key_set") + " ✓" : t("ai_not_configured"));
        if (st.base_host) lines.push(`${t("ai_host")}: ${esc(st.base_host)}`);
        if (st.model) lines.push(`${t("ai_models")}: ${esc(st.model)}`);
        if (st.fallbacks && st.fallbacks.length) lines.push(`${esc(st.fallbacks.join(", "))}`);
        aiStatus.innerHTML = lines.join("<br>");
      } catch (e) {
        aiStatus.innerHTML = esc(e.message || "");
      }
    }
  } catch (e) {
    console.warn("loadProfile", e);
  }
  loadNews();
}

async function loadNews() {
  const status = $("news-status");
  if (!status) return;
  try {
    const cfg = await api("/api/news/config");
    const ne = $("news-enabled");
    const na = $("news-auto");
    const ni = $("news-interval");
    if (ne) ne.checked = !!cfg.enabled;
    if (na) na.checked = !!cfg.auto_publish;
    if (ni) ni.value = cfg.interval_min || 30;
    status.textContent = `Seen: ${cfg.seen_count || 0} | Last: ${cfg.last_fetch ? fmtTime(cfg.last_fetch) : "—"}`;
  } catch (e) {
    status.textContent = "—";
  }
}

/* ===== Brand Profile + Connections + Studio icon sprite ===== */
const UI_ICONS = {
  home: '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  channels: '<path d="M16 10a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 14.286V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/><path d="M20 9a2 2 0 0 1 2 2v10.286a.71.71 0 0 1-1.212.502l-2.202-2.202A2 2 0 0 0 17.172 19H10a2 2 0 0 1-2-2v-1"/>',
  posts: '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  schedule: '<path d="M16 14v2.2l1.6 1"/><path d="M16 2v3"/><path d="M21 7.338V5a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2h2.338"/><path d="M3 9h5.859"/><path d="M8 2v3"/><circle cx="16" cy="16" r="6"/>',
  history: '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
  profile: '<circle cx="12" cy="8" r="5"/><path d="M20 21a8 8 0 0 0-16 0"/>',
  menu: '<path d="M4 5h16"/><path d="M4 12h16"/><path d="M4 19h16"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  language: '<path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/>',
  back: '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
  help: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
  cancel: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  library: '<path d="m16 6 4 14"/><path d="M12 6v14"/><path d="M8 8v12"/><path d="M4 4v16"/>',
  templates: '<rect width="18" height="7" x="3" y="3" rx="1"/><rect width="9" height="7" x="3" y="14" rx="1"/><rect width="5" height="7" x="16" y="14" rx="1"/>',
  media: '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
  settings: '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.319 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319-1.915"/><circle cx="12" cy="12" r="3"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  moon: '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/>',
  brand: '<path d="M20.341 6.484A10 10 0 0 1 10.266 21.85"/><path d="M3.659 17.516A10 10 0 0 1 13.74 2.152"/><circle cx="12" cy="12" r="3"/><circle cx="19" cy="5" r="2"/><circle cx="5" cy="19" r="2"/>',
  cable: '<path d="M17 19a1 1 0 0 1-1-1v-2a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2a1 1 0 0 1-1 1z"/><path d="M17 21v-2"/><path d="M19 14V6.5a1 1 0 0 0-7 0v11a1 1 0 0 1-7 0V10"/><path d="M21 21v-2"/><path d="M3 5V3"/><path d="M4 10a2 2 0 0 1-2-2V6a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2a2 2 0 0 1-2 2z"/><path d="M7 5V3"/>',
  folder: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
  save: '<path d="M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M17 21v-7a1 1 0 0 0-1-1H8a1 1 0 0 0-1 1v7"/><path d="M7 3v4a1 1 0 0 0 1 1h7"/>',
  squarePen: '<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.853.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z"/>',
  messages: '<path d="M16 10a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.202A.71.71 0 0 1 2 14.286V4a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/><path d="M20 9a2 2 0 0 1 2 2v10.286a.71.71 0 0 1-1.212.502l-2.202-2.202A2 2 0 0 0 17.172 19H10a2 2 0 0 1-2-2v-1"/>',
  network: '<rect x="16" y="16" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="9" y="2" width="6" height="6" rx="1"/><path d="M5 16v-3a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v3"/><path d="M12 12V8"/>',
  sparkles: '<path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"/><path d="M20 2v4"/><path d="M22 4h-4"/><circle cx="4" cy="20" r="2"/>',
  penLine: '<path d="M13 21h8"/><path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/>',
  shrink: '<path d="m15 15 6 6m-6-6v4.8m0-4.8h4.8"/><path d="M9 19.8V15m0 0H4.2M9 15l-6 6"/><path d="M15 4.2V9m0 0h4.8M15 9l6-6"/><path d="M9 4.2V9m0 0H4.2M9 9 3 3"/>',
  smile: '<path d="M15 10V9"/><path d="M16.472 15a6 6 0 01-8.943 0"/><path d="M9 10V9"/><circle cx="12" cy="12" r="10"/>',
  paperclip: '<path d="m16 6-8.414 8.586a2 2 0 0 0 2.829 2.829l8.414-8.586a4 4 0 1 0-5.657-5.657l-8.379 8.551a6 6 0 1 0 8.485 8.485l8.379-8.551"/>',
  images: '<path d="m22 11-1.296-1.296a2.4 2.4 0 0 0-3.408 0L11 16"/><path d="M4 8a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2"/><circle cx="13" cy="7" r="1" fill="currentColor"/><rect x="8" y="2" width="14" height="14" rx="2"/>',
  layoutTemplate: '<rect width="18" height="7" x="3" y="3" rx="1"/><rect width="9" height="7" x="3" y="14" rx="1"/><rect width="5" height="7" x="16" y="14" rx="1"/>',
  eye: '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/>',
  send: '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',
  copy: '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
  languages: '<path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  repeat: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
  wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.106-3.105c.32-.322.863-.22.983.218a6 6 0 0 1-8.259 7.057l-7.91 7.91a1 1 0 0 1-2.999-3l7.91-7.91a6 6 0 0 1 7.057-8.259c.438.12.54.662.219.984z"/>',
  circleMinus: '<circle cx="12" cy="12" r="10"/><path d="M8 12h8"/>',
  badgeCheck: '<path d="M3.85 8.62a4 4 0 0 1 4.78-4.77 4 4 0 0 1 6.74 0 4 4 0 0 1 4.78 4.78 4 4 0 0 1 0 6.74 4 4 0 0 1-4.77 4.78 4 4 0 0 1-6.75 0 4 4 0 0 1-4.78-4.77 4 4 0 0 1 0-6.76Z"/><path d="m16 9-5.5 5.5L8 12"/>',
  download: '<path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/>',
  target: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" x2="15.42" y1="13.51" y2="17.49"/><line x1="15.41" x2="8.59" y1="6.51" y2="10.49"/>',
  theme: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>',
  search: '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>',
  bell: '<path d="M10.268 21a2 2 0 0 0 3.464 0"/><path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"/>',

};

let __spriteInjected = false;
function ensureUiSprite() {
  if (__spriteInjected) return;
  try {
    const syms = Object.entries(UI_ICONS).map(([k, body]) =>
      `<symbol id="ui-${k}" viewBox="0 0 24 24">${body}</symbol>`).join("");
    const holder = document.createElement("div");
    holder.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true">${syms}</svg>`;
    if (holder.firstElementChild) document.body.appendChild(holder.firstElementChild);
  } catch (e) {
    __spriteInjected = true;  // never crash icon swap on limited DOM impls
    return;
  }
  __spriteInjected = true;
}



/* ============ Theme system ============ */
const THEME_KEY = "vf_theme";
function currentTheme() {
  const de = document.documentElement;
  if (!de || !de.dataset) return "dark";
  return de.dataset.theme === "light" ? "light" : "dark";
}
function applyTheme(t) {
  const de = document.documentElement;
  if (!de || !de.dataset) return;
  const mode = t === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = mode;
  try { localStorage.setItem(THEME_KEY, mode); } catch (e) {}
  const btn = $("btn-theme");
  const use = $("theme-use");
  // Icon shows the destination theme: sun in dark (switch to light), crescent moon in light.
  if (btn) btn.setAttribute("aria-label", mode === "dark" ? "Switch to light" : "Switch to dark");
  if (use) use.setAttribute("href", mode === "dark" ? "#ui-sun" : "#ui-moon");
  // re-render theme-aware logo panels if visible
  if ($("page-profile") && $("page-profile").classList.contains("active")) loadBrand();
  else if ($("page-connections") && $("page-connections").classList.contains("active")) loadConnections();
}
function themedLogo(p) {
  return currentTheme() === "dark"
    ? (p.logo_dark || p.logo)
    : (p.logo_light || p.logo);
}
function bindThemeToggle() {
  const btn = $("btn-theme");
  if (!btn || btn.dataset.bound) return;
  btn.dataset.bound = "1";
  btn.addEventListener("click", () => applyTheme(currentTheme() === "dark" ? "light" : "dark"));
}

async function loadBrand() {
  const el = $("brand-name");
  if (!el) return;
  try {
    const pr = await api("/api/profile");
    const fa = LANG === "fa";
    $("brand-name").textContent = fa ? pr.brand.name_fa : pr.brand.name_en;
    $("brand-slogan-fa").textContent = pr.brand.slogan_fa;
    $("brand-slogan-en").textContent = pr.brand.slogan_en;
    $("brand-email").textContent = pr.brand.email;
    $("prof-desc-fa").value = pr.desc_fa || "";
    $("prof-desc-en").value = pr.desc_en || "";
    renderSocialGrid(pr.social);
  } catch (e) {
    console.warn("loadBrand", e);
  }
}
function renderSocialGrid(social) {
  const grid = $("social-grid");
  if (!grid) return;
  const fa = LANG === "fa";
  grid.innerHTML = social.map((p) => {
    const name = fa ? p.fa : p.en;
    const ident = p.display ? escFull(p.display) : (p.handle ? escFull(p.handle) : "—");
    const logo = p.logo ? `<img class="plat-logo" src="${themedLogo(p)}" alt="${esc(name)}" loading="lazy">`
      : `<div class="plat-logo pending" title="${t("conn_pending_asset")}">…</div>`;
    const link = p.url ? `<a class="conn-link" href="${esc(p.url)}" target="_blank" rel="noopener">${t("conn_open_profile")} ↗</a>`
      : `<span class="hint">${t("prof_no_link")}</span>`;
    const check = p.status === "verified"
      ? `<span class="verified-badge" title="${t("prof_verified")}">✓</span>`
      : (p.status === "unverified"
        ? `<span class="unverified-badge" title="${t("prof_unverified")}"><svg class="uiic" width="14" height="14" aria-hidden="true"><use href="#ui-info"/></svg></span>`
        : "");
    return `<div class="soc-card ${p.id==="quora" ? "quora-card" : ""}">
      <div class="soc-head">${logo}${check}</div>
      <div class="soc-name">${escFull(name)}</div>
      <div class="soc-sub">${ident}</div>
      <div class="soc-foot">${link}</div>
    </div>`;
  }).join("");
}
function bindProfileSave() {
  const btn = $("prof-save");
  if (!btn || btn.dataset.bound) return;
  btn.dataset.bound = "1";
  btn.addEventListener("click", async () => {
    const msg = $("prof-save-msg");
    try {
      await api("/api/profile", {
        method: "PUT", json: {
          brand_desc_fa: $("prof-desc-fa").value,
          brand_desc_en: $("prof-desc-en").value,
        },
      });
      if (msg) msg.textContent = t("prof_saved");
    } catch (e) {
      if (msg) msg.textContent = esc(e.message || "");
    }
  });
}

/* ---------------- Boot + Startup Animation ---------------- */
function showBootError(msg) {
  const bs = $("boot-status");
  if (bs) {
    bs.style.display = "block";
    bs.textContent = msg;
    bs.style.background = "#3a1212";
    bs.style.color = "#ffb4b4";
  }
}

function hideBoot() {
  const bs = $("boot-status");
  if (bs) {
    bs.style.opacity = "0";
    setTimeout(() => { bs.style.display = "none"; }, 320);
  }
  // Hide splash with animation, then reveal app
  const splash = $("splash");
  const minSplashMs = 1600; // keep splash visible at least this long
  const started = window.__splashStarted || Date.now();
  const wait = Math.max(0, minSplashMs - (Date.now() - started));

  setTimeout(() => {
    if (splash) splash.classList.add("hide");
    const app = $("app");
    if (app) app.classList.add("app-ready");
    // remove splash from DOM after fade
    setTimeout(() => { if (splash && splash.parentNode) splash.remove(); }, 600);
  }, wait);
}

async function boot() {
  const bs = $("boot-status");
  if (bs) bs.textContent = tg ? "Connecting…" : (DEMO ? "Demo mode…" : "Loading…");

  if (!AUTH) {
    const savedTok = studioToken();
    if (!savedTok) {
      hideBoot();
      const pages = $("pages");
      if (pages && !pages.querySelector("[data-login-notice]")) {
        pages.insertAdjacentHTML("beforeend",
          `<div data-login-notice class="empty-state" style="padding-top:100px">
            این استودیو از داخل تلگرام یا با توکن مدیر باز می‌شود.<br>
            بات را باز کن و دکمه «استودیو» را بزن.
            <div class="token-login">
              <input id="vf-token-input" type="password" autocomplete="off" placeholder="STUDIO_ADMIN_TOKEN">
              <button class="btn primary" id="vf-token-save">ورود</button>
            </div>
            <br><small>For testing add <code>?demo</code> to URL</small>
          </div>`);
        const saveBtn = $("vf-token-save");
        const tryLogin = () => {
          const v = (($("vf-token-input") || {}).value || "").trim();
          if (v) {
            try { localStorage.setItem("vf_studio_token", v); } catch (e) {}
            location.reload();
          }
        };
        if (saveBtn) saveBtn.addEventListener("click", tryLogin);
        const tokInp = $("vf-token-input");
        if (tokInp) tokInp.addEventListener("keydown", (e) => {
          if (e.key === "Enter") tryLogin();
        });
      }
      return;
    }
    // a saved standalone token exists → continue boot; api() sends Bearer
  }

  try {
    const me = await api("/api/me");
    state.me = me;
    const un = $("user-name");
    if (un) un.textContent = (me.user && (me.user.first_name || me.user.username)) || "Admin";
    renderStats(me.stats || {});
    initCalState();
    await loadCalendar();
    await loadRecent();
    try {
      const ch = await api("/api/channels");
      state.channels = ch || [];
    } catch (e) {}
    hideBoot();
  } catch (e) {
    console.error("Boot error", e);
    // Invalid standalone token → drop it and show the login form (no reload loop:
    // network errors don't match /token/i and keep the current error surface)
    const bootMsg = String((e && e.message) || "");
    if (!AUTH && studioToken() && /token/i.test(bootMsg)) {
      try { localStorage.removeItem("vf_studio_token"); } catch (e2) {}
      location.reload();
      return;
    }
    // Still show the UI so user is not stuck on black screen
    renderStats({ draft: 0, approved: 0, scheduled: 0, published: 0, publish_failed: 0 });
    await loadCalendar();
    hideBoot();
    toast(e.message || "Connection error");
    if (bs) {
      bs.style.display = "block";
      bs.textContent = "Server connection issue — UI is available in limited mode";
      bs.style.background = "#3a2a12";
      bs.style.color = "#ffd9a0";
    }
  }
}

/* ---------------- INIT (all listeners here) ---------------- */
function initApp() {
  ensureUiSprite();
  // Language
  const langBtn = $("btn-lang");
  if (langBtn) {
    langBtn.addEventListener("click", () => {
      LANG = LANG === "fa" ? "en" : "fa";
      localStorage.setItem("vf_lang", LANG);
      applyI18n();
      if (state.me) renderStats(state.me.stats);
      if (currentPage() === "posts") loadPosts();
      if (currentPage() === "home") {
        loadCalendar();
        loadRecent();
      }
      if (currentPage() === "profile") loadNews();
      renderNetworkChips();
      renderNetworkVariants();
    });
  }

  // Bottom nav
  $$(".bottom-nav .tab").forEach((btn) => {
    btn.addEventListener("click", () => showPage(btn.dataset.page));
  });
  initAdminUi();

  // Calendar nav
  const calPrev = $("cal-prev");
  const calNext = $("cal-next");
  if (calPrev) calPrev.addEventListener("click", () => {
    if (LANG === "fa") {
      let { jy, jm } = calState.fa;
      jm--; if (jm < 1) { jm = 12; jy--; }
      calState.fa = { jy, jm };
    } else {
      let { gy, gm } = calState.en;
      gm--; if (gm < 1) { gm = 12; gy--; }
      calState.en = { gy, gm };
    }
    loadCalendar();
  });
  if (calNext) calNext.addEventListener("click", () => {
    if (LANG === "fa") {
      let { jy, jm } = calState.fa;
      jm++; if (jm > 12) { jm = 1; jy++; }
      calState.fa = { jy, jm };
    } else {
      let { gy, gm } = calState.en;
      gm++; if (gm > 12) { gm = 1; gy++; }
      calState.en = { gy, gm };
    }
    loadCalendar();
  });

  // Refresh
  const refreshBtn = $("btn-refresh");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      state.planCache = {};
      showPage(currentPage());
      toast(t("toast_refreshed"));
    });
  }

  // Channels add
  const chAdd = $("ch-add");
  if (chAdd) {
    chAdd.addEventListener("click", async () => {
      const input = $("ch-input");
      const ref = input ? input.value.trim() : "";
      if (!ref) return;
      chAdd.disabled = true;
      try {
        await api("/api/channels", { method: "POST", json: { ref } });
        toast("✓");
        if (input) input.value = "";
        loadChannels();
      } catch (e) { toast(e.message); }
      chAdd.disabled = false;
    });
  }

  // Post filters
  $$("#post-filters .chip").forEach((c) => {
    c.addEventListener("click", () => {
      $$("#post-filters .chip").forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
      state.filter = c.dataset.f || "";
      loadPosts();
    });
  });

  // History filters
  $$("#hist-filters .chip").forEach((c) => {
    c.addEventListener("click", () => {
      loadHistory(c.dataset.h || "");
    });
  });

  // Media library + templates
  const libBtn = $("btn-library");
  if (libBtn) libBtn.addEventListener("click", () => { loadLibrary(); libSheet(true); });
  const libBd = $("library-backdrop");
  if (libBd) libBd.addEventListener("click", (e) => { if (e.target === libBd) libSheet(false); });
  const tplBtn = $("btn-templates");
  if (tplBtn) tplBtn.addEventListener("click", () => { loadTemplates(); tplSheet(true); });
  const tplBd = $("templates-backdrop");
  if (tplBd) tplBd.addEventListener("click", (e) => { if (e.target === tplBd) tplSheet(false); });
  const tplCreate = $("tpl-create");
  if (tplCreate) tplCreate.addEventListener("click", async () => {
    const nm = $("tpl-name"), bd = $("tpl-body");
    const name = (nm && nm.value || "").trim();
    const body = (bd && bd.value || "").trim();
    if (!name || !body) { toast(t("tpl_empty")); return; }
    try {
      await api("/api/templates", { method: "POST", json: { name, body } });
      toast(t("tpl_created"));
      if (nm) nm.value = ""; if (bd) bd.value = "";
      loadTemplates();
    } catch (e) { toast(e.message); }
  });

  // AI test
  const aiTestBtn = $("ai-test-btn");
  if (aiTestBtn) aiTestBtn.addEventListener("click", async () => {
    const resEl = $("ai-test-result");
    if (resEl) resEl.textContent = "…";
    try {
      const r = await api("/api/ai/test", { method: "POST", json: {} });
      if (resEl) resEl.textContent = r.ok ? t("ai_test_ok") : t("ai_test_fail");
    } catch (e) {
      if (resEl) resEl.textContent = e.status === 409 ? t("ai_test_unconfigured") : t("ai_test_fail");
    }
  });

  // Escape closes any open overlay
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    ["drawer-backdrop", "library-backdrop", "templates-backdrop", "preview-backdrop", "editor-backdrop"].forEach((id) => {
      const bd = $(id);
      if (bd) bd.classList.remove("open");
    });
  });

  // FAB
  const fab = $("fab-create");
  if (fab) fab.addEventListener("click", () => openEditor(null));

  // Editor controls
  const edClose = $("ed-close");
  if (edClose) edClose.addEventListener("click", closeEditor);

  const editorBackdrop = $("editor-backdrop");
  if (editorBackdrop) {
    editorBackdrop.addEventListener("click", (e) => {
      if (e.target === editorBackdrop) closeEditor();
    });
  }

  const schedToggle = $("ed-sched-toggle");
  if (schedToggle) {
    schedToggle.addEventListener("click", () => {
      state.schedOn = !state.schedOn;
      const sched = $("ed-sched");
      if (sched) sched.style.display = state.schedOn ? "" : "none";
    });
  }

  const edText = $("ed-text");
  if (edText) {
    edText.addEventListener("input", () => {
      updateCount();
      syncVariantPrefill();
      scheduleRecover();
    });
  }

  const edFile = $("ed-file");
  if (edFile) {
    edFile.addEventListener("change", async () => {
      const file = edFile.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);
      try {
        const r = await fetch("/api/media", {
          method: "POST",
          headers: authHeader(),
          body: fd,
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.detail || "Upload failed");
        state.mediaUrl = data.url;
        renderMedia();
        updateCount();
        renderNetworkVariants();
        toast(t("toast_img_attached"));
      } catch (e) { toast(e.message); }
      edFile.value = "";
    });
  }

  const edSave = $("ed-save");
  if (edSave) edSave.addEventListener("click", () => saveFromEditor("draft"));

  const edPublish = $("ed-publish");
  if (edPublish) edPublish.addEventListener("click", () => saveFromEditor("publish"));

  const edPreview = $("ed-preview");
  if (edPreview) {
    edPreview.addEventListener("click", async () => {
      const content = edText ? edText.value.trim() : "";
      if (!content && !state.mediaUrl) { toast(t("need_text")); return; }
      await showPreview(content, state.mediaUrl, $("ed-channel")?.value || null, collectVariants());
    });
  }

  const previewCopy = $("preview-copy");
  if (previewCopy) previewCopy.addEventListener("click", copyPreviewText);

  const pLogout = $("profile-logout");
  if (pLogout && studioToken()) pLogout.style.display = ""; // only for standalone-token sessions
  if (pLogout) pLogout.addEventListener("click", () => {
    try { localStorage.removeItem("vf_studio_token"); } catch (e) {}
    toast(t("logout_done") || "Access token removed");
    location.reload();
  });

  const previewClose = $("preview-close");
  if (previewClose) previewClose.addEventListener("click", closePreview);

  const previewBackdrop = $("preview-backdrop");
  if (previewBackdrop) {
    previewBackdrop.addEventListener("click", (e) => {
      if (e.target === previewBackdrop) closePreview();
    });
  }

  // AI
  const aiGen = $("ai-gen");
  if (aiGen) {
    aiGen.addEventListener("click", async () => {
      const topicEl = $("ai-topic");
      const topic = topicEl ? topicEl.value.trim() : "";
      if (!topic) { toast(t("ai_need_topic")); return; }
      aiGen.disabled = true;
      aiGen.textContent = "…";
      try {
        const r = await api("/api/ai/generate", {
          method: "POST",
          json: {
            topic,
            tone: $("ai-tone")?.value || "friendly",
            length: $("ai-length")?.value || "medium",
          },
        });
        if (edText) edText.value = r.text;
        updateCount();
        renderNetworkVariants();
        toast(t("toast_ai_done"));
      } catch (e) { toast(e.status === 503 ? t("ai_not_configured") : e.message); }
      aiGen.disabled = false;
      aiGen.textContent = t("ai_gen");
    });
  }

  $$("[data-rewrite]").forEach((b) => {
    b.addEventListener("click", async () => {
      const content = edText ? edText.value.trim() : "";
      if (!content) { toast(t("need_content")); return; }
      b.disabled = true;
      try {
        const r = await api("/api/ai/rewrite", {
          method: "POST",
          json: { content, mode: b.dataset.rewrite },
        });
        if (edText) edText.value = r.text;
        updateCount();
        renderNetworkVariants();
        toast(t("toast_rewritten"));
      } catch (e) { toast(e.status === 503 ? t("ai_not_configured") : e.message); }
      b.disabled = false;
    });
  });

  // Signature
  const sigSave = $("sig-save");
  if (sigSave) {
    sigSave.addEventListener("click", async () => {
      try {
        await api("/api/settings", {
          method: "PUT",
          json: {
            signature_enabled: $("sig-enabled")?.checked ? "1" : "0",
            signature_text: $("sig-text")?.value || "",
          },
        });
        toast(t("toast_saved"));
      } catch (e) { toast(e.message); }
    });
  }

  // News
  const newsSave = $("news-save");
  if (newsSave) {
    newsSave.addEventListener("click", async () => {
      try {
        await api("/api/news/config", {
          method: "PUT",
          json: {
            enabled: $("news-enabled")?.checked || false,
            auto_publish: $("news-auto")?.checked || false,
            interval_min: parseInt($("news-interval")?.value) || 30,
          },
        });
        toast(t("news_saved"));
      } catch (e) { toast(e.message); }
    });
  }

  const newsNow = $("news-now");
  if (newsNow) {
    newsNow.addEventListener("click", async () => {
      newsNow.disabled = true;
      newsNow.textContent = "…";
      try {
        const r = await api("/api/news/fetch_now", { method: "POST" });
        if (r.published) toast(t("news_fetched") + (r.title_fa || r.title_en || "").slice(0, 60));
        else toast(t("news_drafted") + " #" + r.draft_id);
      } catch (e) { toast(e.message); }
      newsNow.disabled = false;
      newsNow.textContent = t("news_now");
    });
  }

  // Media generation
  const mgenKind = $("mgen-kind");
  if (mgenKind) {
    mgenKind.addEventListener("change", () => {
      const row = $("mgen-sec-row");
      if (row) row.style.display = mgenKind.value === "video" ? "" : "none";
    });
  }

  const mgenGo = $("mgen-go");
  if (mgenGo) {
    mgenGo.addEventListener("click", async () => {
      const text = edText ? edText.value.trim() : "";
      if (!text) { toast(t("mgen_need_text")); return; }
      mgenGo.disabled = true;
      mgenGo.textContent = "…";
      try {
        const r = await api("/api/media/generate", {
          method: "POST",
          json: {
            text,
            platform: $("mgen-platform")?.value || "telegram",
            kind: $("mgen-kind")?.value || "photo",
            seconds: parseInt($("mgen-seconds")?.value) || 8,
            source: "VoidFeed",
          },
        });
        state.mediaUrl = r.url;
        renderMedia();
        updateCount();
        renderNetworkVariants();
        toast(t("mgen_done"));
      } catch (e) { toast(t("mgen_fail") + e.message); }
      mgenGo.disabled = false;
      mgenGo.textContent = t("mgen_go");
    });
  }

  // Load platforms for mgen if available
  (async () => {
    try {
      const pfs = await api("/api/platforms");
      const sel = $("mgen-platform");
      if (sel && pfs) {
        sel.innerHTML = Object.entries(pfs).map(([k, v]) =>
          `<option value="${k}">${v.label} (${v.w}×${v.h})</option>`
        ).join("");
      }
    } catch (e) {}
  })();

  // Initial i18n + networks
  applyI18n();
  renderNetworkChips();
  loadNetworks().then(() => renderNetworkChips()).catch(() => {});

  // Start
  boot();
}

// Global error → prevent silent black screen
window.addEventListener("error", (e) => {
  console.error(e);
  const bs = $("boot-status");
  if (bs) {
    bs.style.display = "block";
    bs.textContent = "JS Error: " + (e.message || "unknown") + " (see console)";
    bs.style.background = "#3a1212";
    bs.style.color = "#ffb4b4";
  }
});

// Track when splash started (for minimum display time)
window.__splashStarted = Date.now();

// Run when DOM is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initApp);
} else {
  initApp();
}
/* ===== Drawer menu (منوی کشویی) ===== */
(function () {
  var bd = $("drawer-backdrop");
  var dr = $("drawer");
  function openDrawer() { if (bd) bd.classList.add("open"); }
  function closeDrawer() { if (bd) bd.classList.remove("open"); }
  var menuBtn = $("btn-menu");
  if (menuBtn) menuBtn.addEventListener("click", openDrawer);
  if (bd) bd.addEventListener("click", function (e) {
    if (e.target === bd) closeDrawer();
  });
  if (dr) $$(".drawer-item", dr).forEach(function (el) {
    el.addEventListener("click", function () {
      var act = el.dataset.act;
      closeDrawer();
      if (act === "create") openEditor(null);
      else if (act === "posts") showPage("posts");
      else if (act === "profile") showPage("profile");
      else if (act === "mod") showPage("mod");
      else if (act === "stats") showPage("stats");
      else if (act === "news") showPage("news");
      else if (act === "lang") { var lb = $("btn-lang"); if (lb) lb.click(); }
      else if (act === "back") {
        if (window.history && history.length > 1) history.back();
        else closeDrawer();
      }
      else if (act === "help") {
        toast(t("about_text") || "VoidFeed Studio — Start with the ＋ button for a new post; manage drafts in Posts; connect networks in Connections.");
      }
      // "cancel" => فقط بستن کشو
    });
  });
  var lpEl = $("dr-linkprev"), afEl = $("dr-autofwd");
  if (lpEl) {
    lpEl.checked = localStorage.getItem("vf_linkpreview") === "1";
    lpEl.addEventListener("change", function () {
      localStorage.setItem("vf_linkpreview", lpEl.checked ? "1" : "0");
      toast(lpEl.checked ? t("dr_linkpreview_on") : t("dr_linkpreview_off"));
    });
  }
  if (afEl) {
    afEl.checked = localStorage.getItem("vf_autofwd") === "1";
    afEl.addEventListener("change", function () {
      localStorage.setItem("vf_autofwd", afEl.checked ? "1" : "0");
      toast(afEl.checked ? t("dr_autofwd_on") : t("dr_autofwd_off"));
    });
  }
  // منوی-اول: با باز شدن استودیو کشو خودکار باز شود
  setTimeout(openDrawer, 400);
})();
setTimeout(() => { bindThemeToggle(); applyTheme(currentTheme()); }, 0);
