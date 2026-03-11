import { describe, it, expect } from "vitest";
import { htmlToText } from "../to-text.js";

describe("htmlToText", () => {
  it("strips HTML tags", () => {
    expect(htmlToText("<p>Hello <b>world</b></p>")).toBe("Hello world");
  });

  it("converts <li> to bullet points", () => {
    expect(htmlToText("<ul><li>First</li><li>Second</li></ul>")).toBe("- First\n- Second");
  });

  it("converts <br> to newline", () => {
    expect(htmlToText("Line 1<br/>Line 2")).toBe("Line 1\nLine 2");
  });

  it("unescapes HTML entities", () => {
    expect(htmlToText("&lt;T&gt; &amp; &quot;foo&quot;")).toBe('<T> & "foo"');
  });

  it("collapses multiple newlines", () => {
    expect(htmlToText("<p>A</p><p>B</p><p>C</p>")).toBe("A\n\nB\n\nC");
  });

  it("returns empty string for empty input", () => {
    expect(htmlToText("")).toBe("");
  });

  it("preserves escaped angle brackets (does not strip them as tags)", () => {
    expect(htmlToText("Use &lt;Fragment&gt; here")).toContain("<Fragment>");
  });
});
