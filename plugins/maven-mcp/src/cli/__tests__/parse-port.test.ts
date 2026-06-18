import { describe, it, expect } from "vitest";
import { parsePortArg, InvalidPortError } from "../parse-port.js";

describe("parsePortArg", () => {
  it("parses the space form --port 8080", () => {
    expect(parsePortArg(["--port", "8080"])).toBe(8080);
  });

  it("parses the equals form --port=8080", () => {
    expect(parsePortArg(["--port=8080"])).toBe(8080);
  });

  it("returns null when --port is absent", () => {
    expect(parsePortArg([])).toBeNull();
    expect(parsePortArg(["--other", "value"])).toBeNull();
  });

  it("throws InvalidPortError when the value is missing", () => {
    expect(() => parsePortArg(["--port"])).toThrow(InvalidPortError);
  });

  it("throws InvalidPortError for out-of-range and non-numeric values", () => {
    expect(() => parsePortArg(["--port", "0"])).toThrow(InvalidPortError);
    expect(() => parsePortArg(["--port", "65536"])).toThrow(InvalidPortError);
    expect(() => parsePortArg(["--port", "-1"])).toThrow(InvalidPortError);
    expect(() => parsePortArg(["--port", "8080.5"])).toThrow(InvalidPortError);
    expect(() => parsePortArg(["--port", "abc"])).toThrow(InvalidPortError);
    expect(() => parsePortArg(["--port=0"])).toThrow(InvalidPortError);
    expect(() => parsePortArg(["--port=65536"])).toThrow(InvalidPortError);
  });
});
