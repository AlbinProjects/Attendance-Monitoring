/**
 * Heuristic device-type detection for the laptop-presence signal
 * (Phase 14) — distinguishes "probably a phone" from "probably a
 * laptop/desktop" using a User-Agent regex, the standard practical
 * approach for this kind of signal.
 *
 * This is NOT security-critical and NOT perfectly reliable — a tablet in
 * desktop mode, an unusual browser, or a phone with a spoofed UA could be
 * misclassified. That's an accepted, documented limitation (see
 * SECURITY.md): the laptop-presence requirement is a practical nudge
 * toward genuine dual-device usage, not a hard security boundary on its
 * own — GPS and (optionally) IP verification remain the actual
 * attendance authorization checks.
 */
const MOBILE_UA_PATTERN = /Android|iPhone|iPod|Mobi|Windows Phone/i;
// iPadOS 13+ reports as "Macintosh" by default, so also check for touch
// support alongside a Mac-like UA to catch iPads.
const IPAD_LIKE_PATTERN = /Macintosh/i;

export function isLikelyMobileDevice() {
  const ua = navigator.userAgent || "";
  if (MOBILE_UA_PATTERN.test(ua)) return true;
  if (IPAD_LIKE_PATTERN.test(ua) && navigator.maxTouchPoints > 1) return true;
  return false;
}
