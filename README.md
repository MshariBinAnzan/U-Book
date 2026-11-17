# U-Book — University Meeting Room Booking System

**U-Book** is a bilingual (English & Arabic `RTL`) web application for university **Doctors (Faculty)**, **Staff Members**, and **Administrators** to browse and reserve campus meeting rooms with server-side conflict prevention.

---

## Tech Stack

- **Backend:** Python 3.12+, Flask 3, `supabase-py`, `python-dotenv`
- **Frontend:** HTML5, CSS3, Bootstrap 5.3 (LTR & RTL), Jinja2 templates, `Inter` & `IBM Plex Sans Arabic`
- **Database & Auth:** Supabase (PostgreSQL + Supabase Auth + Row-Level Security)

---

## Project Structure

```text
U-Book/
├── app.py                  # Flask application, auth decorators, overlap validation, routes
├── translations.py         # English (en) & Arabic (ar) UI and flash message dictionary
├── supabase_schema.sql     # PostgreSQL tables, RLS policies, auth trigger, and meeting room seed data
├── requirements.txt        # Python dependencies
├── .env.example            # Safe environment variable template
├── .gitignore              # Git ignore rules (.env, venv/, __pycache__/, etc.)
├── static/
│   └── css/
│       └── style.css       # Minimalist institutional university styling
└── templates/
    ├── base.html           # Navbar, language toggle (EN | عربي), RTL/LTR switcher
    ├── index.html          # Meeting rooms directory & filter bar
    ├── book_room.html      # Room specifications, daily schedule, and booking form
    ├── my_bookings.html    # Upcoming and past/cancelled reservations
    ├── admin.html          # Admin panel for rooms, bookings, and user roles
    ├── login.html          # Faculty, staff, and admin sign-in
    └── register.html       # Account registration (Doctor, Staff, Admin)
```

---

## Setup & Installation

### 1. Create and Activate a Virtual Environment

```powershell
py -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your Supabase project URL and public `anon` key:

```powershell
Copy-Item .env.example .env
```

```env
SUPABASE_URL=your_project_url
SUPABASE_KEY=your_anon_key
FLASK_SECRET_KEY=change_me
FLASK_DEBUG=0
```

> **Security Note:** Only use your public `anon` / publishable key in `SUPABASE_KEY`. Never commit `.env` or use a `service_role` key in the application.

### 3. Initialize the Supabase Database

Open the **SQL Editor** in your Supabase dashboard, paste the contents of `supabase_schema.sql`, and click **Run**. This creates:
- `public.profiles` (linked to `auth.users` via trigger)
- `public.rooms` (bilingual English/Arabic meeting room columns + 6 seeded university meeting rooms)
- `public.bookings` (with time-range constraints and indexes)
- Row-Level Security (RLS) policies for `profiles`, `rooms`, and `bookings`

### 4. Run the Application

```powershell
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

---

## Contributors

- **MshariBinAnzan** ([@MshariBinAnzan](https://github.com/MshariBinAnzan))
- **MoBinTalib** ([@MoBinTalib](https://github.com/MoBinTalib))
- **SultanAbuthnain** ([@SultanAbuthnain](https://github.com/SultanAbuthnain))


