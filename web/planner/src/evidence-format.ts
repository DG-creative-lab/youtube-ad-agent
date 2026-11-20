const percentage = new Intl.NumberFormat(undefined, {style: "percent", maximumFractionDigits: 1});

export function probabilityLabel(value: number): string {
  if (value > .999 && value < 1) return ">99.9%";
  if (value > 0 && value < .001) return "<0.1%";
  return percentage.format(value);
}
