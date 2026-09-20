/**
 * CLI version handling for the panel and About (spec 3.6.1).
 *
 * The backend decides `too_old` with `install.MIN_CLI_VERSION`; this module
 * only turns `cli_version()` into the panel's one row and About's lines, and
 * parses versions the same way the backend does (`X.Y.Z`, suffixes ignored).
 */

import type { CliVersion } from "./cli";

export type Version = [number, number, number];

export function parseVersion(text: string | null | undefined): Version | null {
  if (!text) return null;
  const match = /^(\d+)\.(\d+)\.(\d+)/.exec(text.trim());
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null;
}

export function compareVersions(a: Version, b: Version): number {
  for (let i = 0; i < 3; i++) {
    if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  }
  return 0;
}

export type CliState = "ok" | "missing" | "too-old";

export interface CliStatus {
  state: CliState;
  /** The panel's single row when the CLI cannot be used; "" when it can. */
  text: string;
}

export function cliStatus(info: Pick<CliVersion, "installed" | "minimum" | "too_old">): CliStatus {
  if (!info.installed) return { state: "missing", text: "CLI not installed — see About" };
  const installed = parseVersion(info.installed);
  const minimum = parseVersion(info.minimum);
  const tooOld =
    info.too_old || !installed || (minimum !== null && compareVersions(installed, minimum) < 0);
  if (tooOld) {
    return {
      state: "too-old",
      text: `CLI too old (${info.installed}, needs ${info.minimum}) — see About`,
    };
  }
  return { state: "ok", text: "" };
}

/** About's "bundled CLI" line (spec 3.6.1). */
export function bundledLine(info: Pick<CliVersion, "bundled" | "minimum">): string {
  if (!info.bundled) {
    return "none (built before the CLI release); install it with the CLI's install.sh";
  }
  return info.bundled;
}
