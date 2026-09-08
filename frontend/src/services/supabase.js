import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  // Fail loudly in dev rather than silently sending requests to `undefined`.
  // eslint-disable-next-line no-console
  console.error(
    "Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY. Check your .env file."
  );
}

// This client only ever uses the PUBLIC anon key. It is safe to ship in the
// browser bundle because Supabase Row Level Security (configured in Phase 2)
// restricts exactly what each authenticated user can read or write.
export const supabase = createClient(supabaseUrl, supabaseAnonKey);
