export function compactNumber(value: number) {
  return new Intl.NumberFormat(undefined, {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value || 0);
}

export function currency(value: number, code = "USD") {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: code.toUpperCase(),
    maximumFractionDigits: 4,
  }).format(value || 0);
}

export function dateTime(seconds: number) {
  if (!seconds) return "-";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(seconds * 1000));
}

export function dayLabel(seconds: number) {
  if (!seconds) return "-";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
  }).format(new Date(seconds * 1000));
}

export function statusClass(status: number) {
  if (status >= 500) return "danger";
  if (status >= 400) return "warn";
  if (status >= 300) return "muted";
  return "ok";
}
