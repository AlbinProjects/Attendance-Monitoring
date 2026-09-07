import axios from "axios";
import { supabase } from "./supabase";

// All backend calls go through this instance. The FastAPI backend is the
// only thing that ever talks to Supabase with elevated privileges — the
// browser never holds anything but the public anon key (see supabase.js).
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
});

// Attach the current Supabase session's access token to every request.
// FastAPI verifies this token server-side (Phase 3) — the frontend never
// tells the backend who the user is by any other means (no employee_id in
// the request body, no trusted headers).
api.interceptors.request.use(async (config) => {
  const { data } = await supabase.auth.getSession();
  const token = data?.session?.access_token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default api;
