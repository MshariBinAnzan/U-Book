import os
import secrets
from datetime import date, datetime
from functools import wraps
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from supabase import Client, create_client
from translations import TRANSLATIONS

load_dotenv()

app = Flask(__name__)

# Load secrets and environment flags strictly via os.environ.get(...)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

IS_LOCAL_DEBUG = os.environ.get("FLASK_DEBUG", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
IS_PRODUCTION = (
    os.environ.get("FLASK_ENV", "").strip().lower() == "production"
    or not IS_LOCAL_DEBUG
)

# Harden Flask session cookies
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = (
    os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or ""
).strip()

ALLOWED_ROLES = ("doctor", "staff", "admin")


def get_lang() -> str:
    """Return active language code ('en' or 'ar') from Flask session."""
    try:
        lang = session.get("lang", "en")
        return lang if lang in ("en", "ar") else "en"
    except RuntimeError:
        return "en"


def tr(key: str) -> str:
    """Translate a key into the active session language."""
    lang = get_lang()
    return TRANSLATIONS.get(lang, TRANSLATIONS["en"]).get(
        key, TRANSLATIONS["en"].get(key, key)
    )


def localize_room(room: dict, lang: str) -> dict:
    """Populate localized display fields on a room dictionary with fallbacks."""
    if not room:
        return room
    name_en = room.get("name_en") or ""
    name_ar = room.get("name_ar") or name_en
    building_en = room.get("building_en") or ""
    building_ar = room.get("building_ar") or building_en
    raw_equip_en = str(room.get("equipment_en") or "")
    raw_equip_ar = str(room.get("equipment_ar") or raw_equip_en)

    room["name_en"] = name_en
    room["name_ar"] = name_ar
    room["building_en"] = building_en
    room["building_ar"] = building_ar
    room["equipment_en"] = raw_equip_en
    room["equipment_ar"] = raw_equip_ar

    room["display_name"] = name_ar if lang == "ar" else name_en
    room["display_building"] = building_ar if lang == "ar" else building_en
    room["display_equipment"] = raw_equip_ar if lang == "ar" else raw_equip_en
    return room


def is_supabase_configured() -> bool:
    """Return True if real Supabase credentials are set in the environment."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    placeholders = ("your_project_url", "your-project-ref", "your_anon_key")
    if any(p in SUPABASE_URL for p in placeholders) or any(
        p in SUPABASE_KEY for p in placeholders
    ):
        return False
    return True


def get_supabase_client() -> Client | None:
    """Initialize and return a Supabase client instance using the public anon key."""
    if not is_supabase_configured():
        return None
    try:
        client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        try:
            access_token = session.get("access_token")
            if access_token:
                client.postgrest.auth(access_token)
        except RuntimeError:
            pass
        return client
    except Exception:
        return None


def get_current_user() -> dict | None:
    """Retrieve the currently authenticated user profile from the Flask session."""
    return session.get("user")


def parse_valid_date(date_str: str) -> date | None:
    """Validate and parse an ISO YYYY-MM-DD date string."""
    try:
        return datetime.strptime((date_str or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def normalize_time_str(time_val: str) -> str | None:
    """Validate and normalize HH:MM or HH:MM:SS into HH:MM:SS."""
    time_val = (time_val or "").strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            dt = datetime.strptime(time_val, fmt)
            return dt.strftime("%H:%M:%S")
        except ValueError:
            continue
    return None


def format_time_display(time_val: str) -> str:
    """Format an HH:MM(:SS) string into a readable 12-hour format."""
    if not time_val:
        return ""
    try:
        clean = str(time_val)[:5]
        dt = datetime.strptime(clean, "%H:%M")
        return dt.strftime("%I:%M %p")
    except ValueError:
        return str(time_val)


app.jinja_env.filters["time12"] = format_time_display


@app.context_processor
def inject_globals():
    """Provide active language, translations, and user context to all templates."""
    lang = get_lang()
    t = TRANSLATIONS.get(lang, TRANSLATIONS["en"])
    user = get_current_user()
    role_labels = {
        "doctor": t["role_doctor"],
        "staff": t["role_staff"],
        "admin": t["role_admin"],
    }
    quick_login_enabled = bool(
        IS_LOCAL_DEBUG
        and os.environ.get("QUICK_LOGIN_EMAIL")
        and os.environ.get("QUICK_LOGIN_PASSWORD")
    )
    return {
        "current_user": user,
        "lang": lang,
        "is_rtl": lang == "ar",
        "t": t,
        "role_labels": role_labels,
        "supabase_configured": is_supabase_configured(),
        "quick_login_enabled": quick_login_enabled,
        "today_iso": date.today().isoformat(),
    }


# -----------------------------------------------------------------------------
# Language Switcher Route
# -----------------------------------------------------------------------------
@app.route("/set-language/<lang_code>")
def set_language(lang_code: str):
    if lang_code in ("en", "ar"):
        session["lang"] = lang_code
    referrer = request.referrer
    if referrer and referrer.startswith(request.host_url):
        return redirect(referrer)
    return redirect(url_for("index"))


# -----------------------------------------------------------------------------
# Access Control Decorators (Server-Side Role & Auth Enforcement)
# -----------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            flash(tr("flash_login_required"), "warning")
            return redirect(url_for("login", next=request.path))
        if user.get("role") not in ALLOWED_ROLES:
            session.clear()
            flash(tr("flash_access_restricted"), "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            flash(tr("flash_login_required"), "warning")
            return redirect(url_for("login"))
        if user.get("role") != "admin":
            flash(tr("flash_admin_required"), "danger")
            return redirect(url_for("index"))
        return f(*args, **kwargs)

    return decorated_function


# -----------------------------------------------------------------------------
# Authentication Routes (Doctors, Staff & Admins Only)
# -----------------------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if get_current_user():
        return redirect(url_for("index"))

    if request.method == "POST":
        sb = get_supabase_client()
        if not sb:
            flash(tr("flash_supabase_unconfigured"), "danger")
            return render_template("register.html")

        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        department = request.form.get("department", "").strip()
        role = request.form.get("role", "doctor").strip().lower()

        if not all([full_name, email, password, department]):
            flash(tr("flash_all_fields_required"), "danger")
            return render_template("register.html")

        if role not in ALLOWED_ROLES:
            flash(tr("flash_invalid_role"), "danger")
            return render_template("register.html")

        if len(password) < 6:
            flash(tr("flash_password_short"), "danger")
            return render_template("register.html")

        try:
            auth_res = sb.auth.sign_up(
                {
                    "email": email,
                    "password": password,
                    "options": {
                        "data": {
                            "full_name": full_name,
                            "department": department,
                            "role": role,
                        }
                    },
                }
            )

            auth_user = auth_res.user
            if not auth_user:
                flash(tr("flash_all_fields_required"), "danger")
                return render_template("register.html")

            profile_payload = {
                "id": auth_user.id,
                "full_name": full_name,
                "email": email,
                "department": department,
                "role": role,
            }

            if auth_res.session:
                session["access_token"] = auth_res.session.access_token
                sb.postgrest.auth(auth_res.session.access_token)
                try:
                    sb.table("profiles").upsert(profile_payload).execute()
                except Exception:
                    pass
                session["user"] = profile_payload
                flash(tr("flash_welcome"), "success")
                return redirect(url_for("index"))
            else:
                flash(tr("flash_check_email"), "info")
                return redirect(url_for("login"))

        except Exception as exc:
            flash(str(exc), "danger")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if get_current_user():
        return redirect(url_for("index"))

    if request.method == "POST":
        sb = get_supabase_client()
        if not sb:
            flash(tr("flash_supabase_unconfigured"), "danger")
            return render_template("login.html")

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash(tr("flash_all_fields_required"), "danger")
            return render_template("login.html")

        try:
            auth_res = sb.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            auth_user = auth_res.user
            if not auth_user:
                flash(tr("flash_invalid_credentials"), "danger")
                return render_template("login.html")

            if auth_res.session:
                session["access_token"] = auth_res.session.access_token
                sb.postgrest.auth(auth_res.session.access_token)

            prof_res = (
                sb.table("profiles").select("*").eq("id", auth_user.id).execute()
            )
            if prof_res.data:
                profile = prof_res.data[0]
            else:
                meta = auth_user.user_metadata or {}
                profile = {
                    "id": auth_user.id,
                    "full_name": meta.get("full_name", email.split("@")[0]),
                    "email": auth_user.email or email,
                    "department": meta.get("department", "Administration"),
                    "role": meta.get("role", "doctor"),
                }
                try:
                    sb.table("profiles").upsert(profile).execute()
                except Exception:
                    pass

            if profile.get("role") not in ALLOWED_ROLES:
                logged_lang = get_lang()
                session.clear()
                session["lang"] = logged_lang
                flash(tr("flash_access_restricted"), "danger")
                return render_template("login.html")

            session["user"] = {
                "id": profile["id"],
                "full_name": profile["full_name"],
                "email": profile["email"],
                "department": profile["department"],
                "role": profile["role"],
            }

            flash(tr("flash_welcome"), "success")
            next_url = request.args.get("next", "")
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("index"))

        except Exception as exc:
            flash(str(exc), "danger")

    return render_template("login.html")


@app.route("/quick-login", methods=["POST"])
def quick_login():
    """Optional local-only sign-in helper loaded strictly from environment variables."""
    quick_email = os.environ.get("QUICK_LOGIN_EMAIL", "").strip()
    quick_password = os.environ.get("QUICK_LOGIN_PASSWORD", "")
    if not (IS_LOCAL_DEBUG and quick_email and quick_password):
        return redirect(url_for("login"))

    sb = get_supabase_client()
    if not sb:
        flash(tr("flash_supabase_unconfigured"), "danger")
        return redirect(url_for("login"))

    try:
        auth_res = sb.auth.sign_in_with_password(
            {"email": quick_email, "password": quick_password}
        )
        if auth_res.session:
            session["access_token"] = auth_res.session.access_token
            sb.postgrest.auth(auth_res.session.access_token)

        prof_res = (
            sb.table("profiles").select("*").eq("id", auth_res.user.id).execute()
        )
        profile = prof_res.data[0]
        session["user"] = {
            "id": profile["id"],
            "full_name": profile["full_name"],
            "email": profile["email"],
            "department": profile["department"],
            "role": profile["role"],
        }
        flash(tr("flash_welcome"), "success")
        return redirect(url_for("index"))
    except Exception as exc:
        flash(str(exc), "danger")
        return redirect(url_for("login"))


@app.route("/logout")
def logout():
    sb = get_supabase_client()
    if sb:
        try:
            sb.auth.sign_out()
        except Exception:
            pass
    current_lang = get_lang()
    session.clear()
    session["lang"] = current_lang
    flash(tr("flash_logged_out"), "info")
    return redirect(url_for("login"))


# -----------------------------------------------------------------------------
# Core Pages: Meeting Rooms Directory & Room Booking
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    sb = get_supabase_client()
    lang = get_lang()

    selected_building = request.args.get("building", "").strip()
    min_capacity_raw = request.args.get("min_capacity", "").strip()
    raw_date = request.args.get("booking_date", "").strip()
    parsed_date = parse_valid_date(raw_date)
    selected_date = parsed_date.isoformat() if parsed_date else date.today().isoformat()

    min_capacity = int(min_capacity_raw) if min_capacity_raw.isdigit() else 0

    rooms = []
    buildings = []
    bookings_by_room: dict[str, list[dict]] = {}

    if sb:
        try:
            all_active_res = (
                sb.table("rooms").select("*").eq("is_active", True).execute()
            )
            all_rooms = [localize_room(r, lang) for r in (all_active_res.data or [])]
            all_rooms.sort(key=lambda r: (r["display_building"], r["display_name"]))

            buildings = sorted(
                {r["display_building"] for r in all_rooms if r["display_building"]}
            )

            filtered = all_rooms
            if selected_building:
                filtered = [
                    r
                    for r in filtered
                    if selected_building
                    in (r["display_building"], r["building_en"], r["building_ar"])
                ]
            if min_capacity > 0:
                filtered = [
                    r for r in filtered if (r.get("capacity") or 0) >= min_capacity
                ]

            rooms = filtered

            if selected_date:
                b_res = (
                    sb.table("bookings")
                    .select("id, room_id, start_time, end_time, purpose, status")
                    .eq("booking_date", selected_date)
                    .neq("status", "cancelled")
                    .order("start_time")
                    .execute()
                )
                for b in b_res.data or []:
                    bookings_by_room.setdefault(b["room_id"], []).append(b)

        except Exception as exc:
            flash(str(exc), "warning")

    for room in rooms:
        room["day_bookings"] = bookings_by_room.get(room["id"], [])

    return render_template(
        "index.html",
        rooms=rooms,
        buildings=buildings,
        filters={
            "building": selected_building,
            "min_capacity": min_capacity_raw,
            "booking_date": selected_date,
        },
    )


@app.route("/rooms/<room_id>/book", methods=["GET", "POST"])
@login_required
def book_room(room_id: str):
    sb = get_supabase_client()
    lang = get_lang()
    if not sb:
        flash(tr("flash_supabase_unconfigured"), "danger")
        return redirect(url_for("index"))

    user = get_current_user()
    raw_date = request.values.get("booking_date", "").strip()
    parsed_date = parse_valid_date(raw_date)
    selected_date = parsed_date.isoformat() if parsed_date else date.today().isoformat()

    try:
        room_res = sb.table("rooms").select("*").eq("id", room_id).execute()
        if not room_res.data:
            flash(tr("flash_room_not_found"), "danger")
            return redirect(url_for("index"))
        room = localize_room(room_res.data[0], lang)
    except Exception as exc:
        flash(str(exc), "danger")
        return redirect(url_for("index"))

    if not room.get("is_active") and user["role"] != "admin":
        flash(tr("flash_room_inactive"), "warning")
        return redirect(url_for("index"))

    if request.method == "POST":
        booking_date_str = request.form.get("booking_date", "").strip()
        start_time_raw = request.form.get("start_time", "").strip()
        end_time_raw = request.form.get("end_time", "").strip()
        purpose = request.form.get("purpose", "").strip()

        if not all([booking_date_str, start_time_raw, end_time_raw, purpose]):
            flash(tr("flash_all_fields_required"), "danger")
            return redirect(
                url_for("book_room", room_id=room_id, booking_date=selected_date)
            )

        booking_date_obj = parse_valid_date(booking_date_str)
        if not booking_date_obj:
            flash(tr("flash_all_fields_required"), "danger")
            return redirect(
                url_for("book_room", room_id=room_id, booking_date=selected_date)
            )

        if booking_date_obj < date.today():
            flash(tr("flash_past_date"), "danger")
            return redirect(
                url_for(
                    "book_room",
                    room_id=room_id,
                    booking_date=date.today().isoformat(),
                )
            )

        start_norm = normalize_time_str(start_time_raw)
        end_norm = normalize_time_str(end_time_raw)

        if not start_norm or not end_norm or end_norm <= start_norm:
            flash(tr("flash_invalid_time_order"), "danger")
            return redirect(
                url_for("book_room", room_id=room_id, booking_date=booking_date_obj.isoformat())
            )

        try:
            # Strict Server-Side Overlap Validation:
            # [A_start, A_end) and [B_start, B_end) overlap iff A_start < B_end AND A_end > B_start
            existing_res = (
                sb.table("bookings")
                .select("id, start_time, end_time, purpose, status")
                .eq("room_id", room_id)
                .eq("booking_date", booking_date_obj.isoformat())
                .neq("status", "cancelled")
                .execute()
            )
            existing_bookings = existing_res.data or []

            conflict = None
            for b in existing_bookings:
                b_start = normalize_time_str(b["start_time"]) or b["start_time"]
                b_end = normalize_time_str(b["end_time"]) or b["end_time"]
                if start_norm < b_end and end_norm > b_start:
                    conflict = b
                    break

            if conflict:
                flash(
                    f"{tr('flash_time_conflict')} ({format_time_display(conflict['start_time'])} - {format_time_display(conflict['end_time'])})",
                    "danger",
                )
                return redirect(
                    url_for(
                        "book_room",
                        room_id=room_id,
                        booking_date=booking_date_obj.isoformat(),
                    )
                )

            sb.table("bookings").insert(
                {
                    "room_id": room_id,
                    "user_id": user["id"],
                    "booking_date": booking_date_obj.isoformat(),
                    "start_time": start_norm,
                    "end_time": end_norm,
                    "purpose": purpose,
                    "status": "confirmed",
                }
            ).execute()

            flash(tr("flash_booking_confirmed"), "success")
            return redirect(url_for("my_bookings"))

        except Exception as exc:
            flash(str(exc), "danger")
            return redirect(
                url_for(
                    "book_room",
                    room_id=room_id,
                    booking_date=booking_date_obj.isoformat(),
                )
            )

    day_bookings = []
    try:
        sched_res = (
            sb.table("bookings")
            .select("*, profiles(full_name, department, role)")
            .eq("room_id", room_id)
            .eq("booking_date", selected_date)
            .neq("status", "cancelled")
            .order("start_time")
            .execute()
        )
        day_bookings = sched_res.data or []
    except Exception as exc:
        flash(str(exc), "warning")

    return render_template(
        "book_room.html",
        room=room,
        selected_date=selected_date,
        day_bookings=day_bookings,
    )


# -----------------------------------------------------------------------------
# My Bookings & One-Click Cancellation
# -----------------------------------------------------------------------------
@app.route("/my-bookings")
@login_required
def my_bookings():
    sb = get_supabase_client()
    lang = get_lang()
    user = get_current_user()
    upcoming_bookings = []
    past_or_cancelled = []
    today_str = date.today().isoformat()

    if sb:
        try:
            res = (
                sb.table("bookings")
                .select("*, rooms(*)")
                .eq("user_id", user["id"])
                .order("booking_date", desc=False)
                .order("start_time", desc=False)
                .execute()
            )
            for b in res.data or []:
                if b.get("rooms"):
                    b["rooms"] = localize_room(b["rooms"], lang)
                if (
                    b.get("status") != "cancelled"
                    and b.get("booking_date", "") >= today_str
                ):
                    upcoming_bookings.append(b)
                else:
                    past_or_cancelled.append(b)
            past_or_cancelled.sort(
                key=lambda x: (x.get("booking_date", ""), x.get("start_time", "")),
                reverse=True,
            )
        except Exception as exc:
            flash(str(exc), "danger")

    return render_template(
        "my_bookings.html",
        upcoming_bookings=upcoming_bookings,
        past_bookings=past_or_cancelled,
    )


@app.route("/bookings/<booking_id>/cancel", methods=["POST"])
@login_required
def cancel_booking(booking_id: str):
    sb = get_supabase_client()
    user = get_current_user()
    if not sb:
        flash(tr("flash_supabase_unconfigured"), "danger")
        return redirect(url_for("my_bookings"))

    try:
        b_res = (
            sb.table("bookings")
            .select("id, user_id, status")
            .eq("id", booking_id)
            .execute()
        )
        if not b_res.data:
            return redirect(url_for("my_bookings"))

        booking = b_res.data[0]
        if booking["user_id"] != user["id"] and user["role"] != "admin":
            flash(tr("flash_unauthorized_cancel"), "danger")
            return redirect(url_for("my_bookings"))

        sb.table("bookings").update({"status": "cancelled"}).eq(
            "id", booking_id
        ).execute()
        flash(tr("flash_booking_cancelled"), "info")
    except Exception as exc:
        flash(str(exc), "danger")

    next_target = request.form.get("next")
    if next_target == "admin" and user["role"] == "admin":
        return redirect(url_for("admin_dashboard"))
    return redirect(url_for("my_bookings"))


# -----------------------------------------------------------------------------
# Admin Portal: Manage Meeting Rooms, Reservations, and User Roles
# -----------------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin_dashboard():
    sb = get_supabase_client()
    lang = get_lang()
    rooms = []
    bookings = []
    profiles = []

    if sb:
        try:
            rooms_res = sb.table("rooms").select("*").execute()
            rooms = [localize_room(r, lang) for r in (rooms_res.data or [])]
            rooms.sort(key=lambda r: (r["display_building"], r["display_name"]))

            bookings_res = (
                sb.table("bookings")
                .select("*, rooms(*), profiles(full_name, email, department, role)")
                .order("booking_date", desc=True)
                .order("start_time", desc=True)
                .execute()
            )
            for b in bookings_res.data or []:
                if b.get("rooms"):
                    b["rooms"] = localize_room(b["rooms"], lang)
                bookings.append(b)

            profiles_res = (
                sb.table("profiles")
                .select("*")
                .order("created_at", desc=True)
                .execute()
            )
            profiles = profiles_res.data or []
        except Exception as exc:
            flash(str(exc), "danger")

    return render_template(
        "admin.html",
        rooms=rooms,
        bookings=bookings,
        profiles=profiles,
    )


@app.route("/admin/rooms/create", methods=["POST"])
@admin_required
def admin_create_room():
    sb = get_supabase_client()
    if not sb:
        flash(tr("flash_supabase_unconfigured"), "danger")
        return redirect(url_for("admin_dashboard"))

    name_en = request.form.get("name_en", "").strip()
    name_ar = request.form.get("name_ar", "").strip() or name_en
    building_en = request.form.get("building_en", "").strip()
    building_ar = request.form.get("building_ar", "").strip() or building_en
    floor_raw = request.form.get("floor", "1").strip()
    capacity_raw = request.form.get("capacity", "12").strip()
    equipment_en = request.form.get("equipment_en", "").strip()
    equipment_ar = request.form.get("equipment_ar", "").strip() or equipment_en

    if not name_en or not building_en:
        flash(tr("flash_all_fields_required"), "danger")
        return redirect(url_for("admin_dashboard"))

    try:
        floor = int(floor_raw)
        capacity = int(capacity_raw)
        if capacity <= 0:
            raise ValueError
    except ValueError:
        flash(tr("flash_all_fields_required"), "danger")
        return redirect(url_for("admin_dashboard"))

    try:
        sb.table("rooms").insert(
            {
                "name_en": name_en,
                "name_ar": name_ar,
                "building_en": building_en,
                "building_ar": building_ar,
                "floor": floor,
                "capacity": capacity,
                "equipment_en": equipment_en,
                "equipment_ar": equipment_ar,
                "is_active": True,
            }
        ).execute()
        flash(tr("flash_room_created"), "success")
    except Exception as exc:
        flash(str(exc), "danger")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/rooms/<room_id>/edit", methods=["POST"])
@admin_required
def admin_edit_room(room_id: str):
    sb = get_supabase_client()
    if not sb:
        return redirect(url_for("admin_dashboard"))

    name_en = request.form.get("name_en", "").strip()
    name_ar = request.form.get("name_ar", "").strip() or name_en
    building_en = request.form.get("building_en", "").strip()
    building_ar = request.form.get("building_ar", "").strip() or building_en
    floor_raw = request.form.get("floor", "1").strip()
    capacity_raw = request.form.get("capacity", "12").strip()
    equipment_en = request.form.get("equipment_en", "").strip()
    equipment_ar = request.form.get("equipment_ar", "").strip() or equipment_en

    try:
        floor = int(floor_raw)
        capacity = int(capacity_raw)
        if capacity <= 0:
            raise ValueError
        sb.table("rooms").update(
            {
                "name_en": name_en,
                "name_ar": name_ar,
                "building_en": building_en,
                "building_ar": building_ar,
                "floor": floor,
                "capacity": capacity,
                "equipment_en": equipment_en,
                "equipment_ar": equipment_ar,
            }
        ).eq("id", room_id).execute()
        flash(tr("flash_room_updated"), "success")
    except Exception as exc:
        flash(str(exc), "danger")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/rooms/<room_id>/toggle", methods=["POST"])
@admin_required
def admin_toggle_room(room_id: str):
    sb = get_supabase_client()
    if not sb:
        return redirect(url_for("admin_dashboard"))

    try:
        res = sb.table("rooms").select("is_active").eq("id", room_id).execute()
        if res.data:
            room = res.data[0]
            new_state = not room.get("is_active", True)
            sb.table("rooms").update({"is_active": new_state}).eq(
                "id", room_id
            ).execute()
            flash(tr("flash_room_toggled"), "info")
    except Exception as exc:
        flash(str(exc), "danger")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/bookings/<booking_id>/status", methods=["POST"])
@admin_required
def admin_update_booking_status(booking_id: str):
    sb = get_supabase_client()
    if not sb:
        return redirect(url_for("admin_dashboard"))

    new_status = request.form.get("status", "").strip().lower()
    if new_status not in ("confirmed", "pending", "cancelled"):
        return redirect(url_for("admin_dashboard"))

    try:
        sb.table("bookings").update({"status": new_status}).eq(
            "id", booking_id
        ).execute()
        flash(tr("flash_status_updated"), "success")
    except Exception as exc:
        flash(str(exc), "danger")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/users/<user_id>/role", methods=["POST"])
@admin_required
def admin_update_user_role(user_id: str):
    sb = get_supabase_client()
    if not sb:
        return redirect(url_for("admin_dashboard"))

    new_role = request.form.get("role", "").strip().lower()
    if new_role not in ALLOWED_ROLES:
        flash(tr("flash_invalid_role"), "danger")
        return redirect(url_for("admin_dashboard"))

    try:
        sb.table("profiles").update({"role": new_role}).eq("id", user_id).execute()
        current = get_current_user()
        if current and current["id"] == user_id:
            session["user"]["role"] = new_role
            session.modified = True
        flash(tr("flash_role_updated"), "success")
    except Exception as exc:
        flash(str(exc), "danger")

    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    app.run(debug=IS_LOCAL_DEBUG, host="127.0.0.1", port=5000)
