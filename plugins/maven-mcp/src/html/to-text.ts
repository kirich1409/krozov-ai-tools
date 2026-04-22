function unescapeEntities(text: string): string {
  return text
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");
}

function stripTags(text: string): string {
  // Loop to handle smuggled forms like `<<script>script>` where the inner tag
  // only becomes visible to the regex after the outer one is stripped.
  let result = text;
  let prev: string;
  do {
    prev = result;
    result = result.replace(/<[^>]*>/g, "");
  } while (result !== prev);
  return result;
}

export function htmlToText(html: string): string {
  const formatted = html
    .replace(/<li[^>]*>/gi, "- ")
    .replace(/<\/li>/gi, "\n")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n\n");
  return unescapeEntities(stripTags(formatted))
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
