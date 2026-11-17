-- =============================================================================
-- U-Book: University Meeting Room Booking System — Supabase Schema & Seed Data
-- Run this script inside the Supabase SQL Editor.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- -----------------------------------------------------------------------------
-- 1. PROFILES TABLE (Linked to auth.users)
-- Exclusively for Doctors (Faculty), Staff, and Administrators.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    full_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    department TEXT NOT NULL DEFAULT 'General Administration',
    role TEXT NOT NULL CHECK (role IN ('doctor', 'staff', 'admin')) DEFAULT 'doctor',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 2. ROOMS TABLE (Meeting Rooms Only — Bilingual English & Arabic Columns)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.rooms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name_en TEXT NOT NULL UNIQUE,
    name_ar TEXT NOT NULL,
    building_en TEXT NOT NULL,
    building_ar TEXT NOT NULL,
    floor INTEGER NOT NULL DEFAULT 1,
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    equipment_en TEXT NOT NULL DEFAULT '',
    equipment_ar TEXT NOT NULL DEFAULT '',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- -----------------------------------------------------------------------------
-- 3. BOOKINGS TABLE
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.bookings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    room_id UUID NOT NULL REFERENCES public.rooms(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    booking_date DATE NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    purpose TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('confirmed', 'pending', 'cancelled')) DEFAULT 'confirmed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_booking_time_range CHECK (end_time > start_time)
);

CREATE INDEX IF NOT EXISTS idx_bookings_room_date ON public.bookings(room_id, booking_date);
CREATE INDEX IF NOT EXISTS idx_bookings_user ON public.bookings(user_id);

-- -----------------------------------------------------------------------------
-- 4. AUTOMATIC PROFILE TRIGGER ON AUTH SIGNUP
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    INSERT INTO public.profiles (id, full_name, email, department, role)
    VALUES (
        NEW.id,
        COALESCE(NEW.raw_user_meta_data->>'full_name', split_part(NEW.email, '@', 1)),
        NEW.email,
        COALESCE(NEW.raw_user_meta_data->>'department', 'Administration'),
        CASE
            WHEN NEW.raw_user_meta_data->>'role' IN ('doctor', 'staff', 'admin')
            THEN NEW.raw_user_meta_data->>'role'
            ELSE 'doctor'
        END
    )
    ON CONFLICT (id) DO UPDATE SET
        full_name = EXCLUDED.full_name,
        department = EXCLUDED.department,
        role = EXCLUDED.role;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- -----------------------------------------------------------------------------
-- 5. HELPER FUNCTION FOR ADMIN ROLE CHECK IN RLS
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.is_admin()
RETURNS BOOLEAN
LANGUAGE sql
SECURITY DEFINER SET search_path = public
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.profiles
        WHERE id = auth.uid() AND role = 'admin'
    );
$$;

-- -----------------------------------------------------------------------------
-- 6. ROW LEVEL SECURITY (RLS) POLICIES
-- Enforces strict ownership and role-based access at the database layer.
-- -----------------------------------------------------------------------------
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rooms ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bookings ENABLE ROW LEVEL SECURITY;

-- Drop legacy policies if present
DROP POLICY IF EXISTS "Profiles are viewable by everyone" ON public.profiles;
DROP POLICY IF EXISTS "Users can insert own profile" ON public.profiles;
DROP POLICY IF EXISTS "Users and admins can update profiles" ON public.profiles;
DROP POLICY IF EXISTS "Rooms are viewable by everyone" ON public.rooms;
DROP POLICY IF EXISTS "Authenticated users can manage rooms" ON public.rooms;
DROP POLICY IF EXISTS "Admins can insert rooms" ON public.rooms;
DROP POLICY IF EXISTS "Admins can update rooms" ON public.rooms;
DROP POLICY IF EXISTS "Admins can delete rooms" ON public.rooms;
DROP POLICY IF EXISTS "Bookings are viewable by everyone" ON public.bookings;
DROP POLICY IF EXISTS "Authenticated users can create bookings" ON public.bookings;
DROP POLICY IF EXISTS "Authenticated users can update bookings" ON public.bookings;
DROP POLICY IF EXISTS "Users can delete own bookings or admin" ON public.bookings;

-- PROFILES POLICIES
-- Authenticated users can read profiles (to display reservation holder names)
CREATE POLICY "Profiles are viewable by everyone" ON public.profiles
    FOR SELECT USING (auth.role() = 'authenticated');

-- Users can only insert their own profile row matching auth.uid()
CREATE POLICY "Users can insert own profile" ON public.profiles
    FOR INSERT WITH CHECK (auth.uid() = id);

-- Users can update their own profile, or admins can update any user's role/profile
CREATE POLICY "Users and admins can update profiles" ON public.profiles
    FOR UPDATE USING (auth.uid() = id OR public.is_admin())
    WITH CHECK (auth.uid() = id OR public.is_admin());

-- ROOMS POLICIES
-- Anyone can view meeting rooms directory
CREATE POLICY "Rooms are viewable by everyone" ON public.rooms
    FOR SELECT USING (true);

-- Only administrators can create, update, or delete meeting rooms
CREATE POLICY "Admins can insert rooms" ON public.rooms
    FOR INSERT WITH CHECK (public.is_admin());

CREATE POLICY "Admins can update rooms" ON public.rooms
    FOR UPDATE USING (public.is_admin())
    WITH CHECK (public.is_admin());

CREATE POLICY "Admins can delete rooms" ON public.rooms
    FOR DELETE USING (public.is_admin());

-- BOOKINGS POLICIES
-- Anyone can read bookings to check room schedule availability
CREATE POLICY "Bookings are viewable by everyone" ON public.bookings
    FOR SELECT USING (true);

-- Authenticated Doctors, Staff, and Admins can only insert bookings under their own user_id
CREATE POLICY "Authenticated users can create bookings" ON public.bookings
    FOR INSERT WITH CHECK (
        auth.uid() = user_id
        AND EXISTS (
            SELECT 1 FROM public.profiles
            WHERE id = auth.uid() AND role IN ('doctor', 'staff', 'admin')
        )
    );

-- Users can only update/cancel their own bookings; Admins can update/approve/cancel any booking
CREATE POLICY "Authenticated users can update bookings" ON public.bookings
    FOR UPDATE USING (auth.uid() = user_id OR public.is_admin())
    WITH CHECK (auth.uid() = user_id OR public.is_admin());

CREATE POLICY "Users can delete own bookings or admin" ON public.bookings
    FOR DELETE USING (auth.uid() = user_id OR public.is_admin());

-- -----------------------------------------------------------------------------
-- 7. SEED DATA: UNIVERSITY MEETING ROOMS ONLY (BILINGUAL)
-- -----------------------------------------------------------------------------
INSERT INTO public.rooms (name_en, name_ar, building_en, building_ar, floor, capacity, equipment_en, equipment_ar, is_active)
VALUES
    (
        'Dean''s Executive Boardroom E-401',
        'قاعة مجلس العميد التنفيذية E-401',
        'Central Administration Building',
        'مبنى الإدارة المركزية',
        4,
        18,
        'Video Conferencing System, Dual Displays, Table Microphones',
        'نظام مؤتمرات مرئية، شاشتا عرض، ميكروفونات طاولة',
        TRUE
    ),
    (
        'Department Council Room C-202',
        'قاعة مجلس القسم C-202',
        'College of Engineering',
        'كلية الهندسة',
        2,
        14,
        '75-inch Display, HDMI Connection, Whiteboard',
        'شاشة عرض 75 بوصة، توصيل HDMI، سبورة بيضاء',
        TRUE
    ),
    (
        'Academic Committee Room A-105',
        'قاعة اللجان الأكاديمية A-105',
        'Academic Affairs Building',
        'مبنى الشؤون الأكاديمية',
        1,
        12,
        'Projector, Speakerphone, Glass Whiteboard',
        'جهاز عرض ضوئي، هاتف اجتماعات، سبورة زجاجية',
        TRUE
    ),
    (
        'Faculty Meeting Room M-304',
        'قاعة اجتماعات أعضاء هيئة التدريس M-304',
        'College of Computer & Information Sciences',
        'كلية علوم الحاسب والمعلومات',
        3,
        20,
        'Smart Screen, Wireless Presentation, Conference Audio',
        'شاشة ذكية، عرض لاسلكي، نظام صوتي للاجتماعات',
        TRUE
    ),
    (
        'Administrative Affairs Meeting Room B-110',
        'قاعة اجتماعات الشؤون الإدارية B-110',
        'Central Administration Building',
        'مبنى الإدارة المركزية',
        1,
        10,
        'LED TV, Conference Table, High-Speed Network',
        'شاشة تلفاز LED، طاولة اجتماعات، شبكة عالية السرعة',
        TRUE
    ),
    (
        'Graduate Studies Committee Room G-208',
        'قاعة لجنة الدراسات العليا G-208',
        'Deanship of Graduate Studies',
        'عمادة الدراسات العليا',
        2,
        16,
        'Video Conferencing Bar, Interactive Display, Whiteboard',
        'وحدة اتصال مرئي، شاشة تفاعلية، سبورة بيضاء',
        TRUE
    )
ON CONFLICT (name_en) DO UPDATE SET
    name_ar = EXCLUDED.name_ar,
    building_en = EXCLUDED.building_en,
    building_ar = EXCLUDED.building_ar,
    floor = EXCLUDED.floor,
    capacity = EXCLUDED.capacity,
    equipment_en = EXCLUDED.equipment_en,
    equipment_ar = EXCLUDED.equipment_ar,
    is_active = EXCLUDED.is_active;
