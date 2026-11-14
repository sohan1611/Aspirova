export function planName(key: string): string {
  if (key === "free") return "Free";
  if (key.startsWith("pro_lite_")) return "Pro Lite";
  if (key.startsWith("pro_")) return "Pro";
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}
