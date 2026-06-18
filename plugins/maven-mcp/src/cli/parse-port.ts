export class InvalidPortError extends Error {}

/**
 * Parse the `--port` argument from a CLI argv slice (i.e. `process.argv.slice(2)`).
 *
 * Pure: does not read `process.argv`, never calls `process.exit` or `console.error`.
 * Supports both `--port <value>` (space form, checked first) and `--port=<value>`.
 *
 * @returns the parsed port, or `null` when `--port` is absent.
 * @throws {InvalidPortError} when the value is missing or out of range (integer 1–65535).
 */
export function parsePortArg(args: string[]): number | null {
  const parseValue = (value: string): number => {
    const n = Number(value);
    if (Number.isInteger(n) && n > 0 && n <= 65535) return n;
    throw new InvalidPortError(`Invalid --port value: "${value}". Expected an integer in range 1–65535.`);
  };
  const idx = args.indexOf("--port");
  if (idx !== -1) {
    if (idx + 1 >= args.length) {
      throw new InvalidPortError("--port requires a value. Usage: --port <number> or --port=<number>");
    }
    return parseValue(args[idx + 1]);
  }
  const eq = args.find((a) => a.startsWith("--port="));
  if (eq) return parseValue(eq.slice("--port=".length));
  return null;
}
