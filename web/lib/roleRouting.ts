// Where each web-facing role lands after login / on "/". Roles with no page
// of their own (auditor) fall through to the hr/admin default and hit
// RequireAuth's "Not authorized" — a known, separately-tracked gap, not
// something this routing table should paper over.
export function roleLandingPath(role: string): string {
  if (role === "supervisor") return "/team";
  return "/geofences";
}
