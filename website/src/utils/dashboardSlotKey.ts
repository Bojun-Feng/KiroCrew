/** Match the persisted dashboard-slot filename fold in dashboard/state.py's
 * `_normalize_slot_key`: channel keys such as `slack:<ts>` use `slack_<ts>` rows. */
export function dashboardGoalLoopSlotKey(key: string): string {
  let folded = key
  if (folded.startsWith('dashboard:')) folded = folded.slice('dashboard:'.length)
  while (folded.startsWith('dashboard_')) folded = folded.slice('dashboard_'.length)
  return folded.replace(/[^a-zA-Z0-9_.-]/g, '_')
}
