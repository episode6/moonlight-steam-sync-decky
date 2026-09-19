/**
 * Test helper: the backend's NDJSON fixtures (`tests/fixtures/**`), parsed by
 * the frontend's own parser, so the Python and TypeScript tests read the
 * same files (spec 3.6.3).
 */

import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { CliEvent } from "../lib/cli";
import { parseNdjson } from "../lib/events";

export const FIXTURES = resolve(dirname(fileURLToPath(import.meta.url)), "../../tests/fixtures");

export function fixtureText(name: string): string {
  return readFileSync(join(FIXTURES, name), "utf8");
}

export function loadFixture(name: string): CliEvent[] {
  return parseNdjson(fixtureText(name));
}

/** Every `<scenario>/<command>.ndjson`, as "scenario/file". */
export function allFixtures(): string[] {
  const names: string[] = [];
  for (const scenario of readdirSync(FIXTURES).sort()) {
    for (const file of readdirSync(join(FIXTURES, scenario)).sort()) {
      if (file.endsWith(".ndjson")) names.push(`${scenario}/${file}`);
    }
  }
  return names;
}
