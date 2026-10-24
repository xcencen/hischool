export function shanghaiDate(): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'
  }).formatToParts(new Date())
  const value = (type: string) => parts.find(part => part.type === type)?.value ?? ''
  return `${value('year')}-${value('month')}-${value('day')}`
}

// Date-only values never pass through the browser's local timezone.
export function shiftDay(day: string, amount: number): string {
  const value = new Date(`${day}T00:00:00Z`)
  value.setUTCDate(value.getUTCDate() + amount)
  return value.toISOString().slice(0, 10)
}
export function weekday(day: string): string {
  return ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][new Date(`${day}T00:00:00Z`).getUTCDay()] ?? ''
}
