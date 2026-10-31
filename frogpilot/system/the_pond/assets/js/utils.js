export function formatSecondsToHuman(seconds) {
  const units = [
    [Math.floor(seconds / 86400), "day"],
    [Math.floor(seconds % 86400 / 3600), "hour"],
    [Math.floor(seconds % 3600 / 60), "minute"],
  ];

  return units.filter(([value]) => value > 0).map(([value, label]) => `${value} ${label}${value === 1 ? "" : "s"}`).join(", ");
}

export function parseErrorLogToDate(filename) {
  const [date, time] = filename.replace(/\.(log|txt)$/, "").split("--");
  const timestamp = new Date(`${date}T${time?.replace(/-/g, ":")}`);
  if (!date || !time || Number.isNaN(timestamp.getTime())) {
    throw new Error(`Invalid log date: ${filename}`);
  }

  return timestamp;
}