// Profile-activated <modules> blocks are also returned; non-existent paths are filtered later.
export function parseMavenModules(content: string): string[] {
  const modulesBlockRegex = /<modules>([\s\S]*?)<\/modules>/g;
  const out: string[] = [];
  let blockMatch: RegExpExecArray | null;

  while ((blockMatch = modulesBlockRegex.exec(content)) !== null) {
    const inner = blockMatch[1];
    const moduleRegex = /<module>([^<]+)<\/module>/g;
    let m: RegExpExecArray | null;
    while ((m = moduleRegex.exec(inner)) !== null) {
      const name = m[1].trim();
      if (name) out.push(name);
    }
  }

  return [...new Set(out)];
}
