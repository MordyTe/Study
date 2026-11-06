# Anti-cheat: how it works and what the agent does about it

**תקציר בעברית.** מערכות anti-cheat מגינות על משחקים מקוונים מפני רמאות ואוטומציה. הן רצות במחשב של
השחקן (user-mode, ולעיתים driver ברמת ה-kernel שעולה עם המערכת), בשרת (סימולציה סמכותית, סטטיסטיקה
ולמידת מכונה על טלמטריה), ובפלטפורמה. הן מזהות בוטים לפי מקור הקלט, התזמון וההתנהגות. agent-play שולח
קלט מסונתז, וזו בדיוק הקטגוריה שהן תופסות, אז השימוש במשחק מוגן עלול להוביל לחסימת חשבון, לעיתים שבועות
אחר כך. הסוכן לומד את המסמך הזה כדי **לזהות משחק מוגן ולהזהיר בבירור** עם ההשלכה האמיתית, ואז ההחלטה
בידי המשתמש, כי זה המחשב והחשבון שלו. אין כאן טכניקות עקיפה, והסוכן לא מפתח כאלה: הוא לא מסווה קלט, לא
מחביא תהליך, לא קורא זיכרון משחק, ולא חוקר מערכת anti-cheat כדי לעקוף אותה.

---

## 0. Why the agent learns this

agent-play is "screen in, input out": it reads the screen and synthesizes keyboard and mouse events.
That is exactly the behavior anti-cheat systems are built to detect, and using it in a protected game
can get the user's account banned, sometimes their hardware fingerprint too. The agent therefore:

1. Recognizes a protected game from its name, its launcher, or signals on screen.
2. Warns clearly and explains the real consequence, so the user decides with the facts in front of them.
3. Knows which games are safe: offline, single-player, or games whose terms allow bots.

This document is the theory. `src/agent_play/skills/anti_cheat.md` is the short version the model reads
every run. `src/agent_play/knowledge/anticheat.json` is the registry the code consults. None of them
contains evasion techniques, and the agent will not develop any. What the user *can* decide is whether
to proceed on their own machine after the warning: the default is warn-and-continue, and
`--block-protected` turns the warning into a hard stop for those who want the guardrail.

## 1. The threat model anti-cheat is built against

| Cheat class | What it does | Where it is visible |
|---|---|---|
| Memory cheats | read or write the game process: ESP/wallhacks, god mode, speed | handles opened to the process, modified memory, unknown modules |
| Aimbots and triggerbots | compute aim and inject input | input provenance, inhuman precision, reaction-time distribution |
| Input automation (macros, bots, computer-use agents) | play or grind without a human | synthetic input flags, timing regularity, session patterns, screen-capture usage |
| Packet manipulation | alter or delay network traffic | server-side sanity checks, desync patterns |
| Hardware cheats | DMA cards read memory from a second PC; devices replay recorded paths | PCIe enumeration, firmware checks, statistical input analysis |
| Tampering | patch the binary, hook APIs, run under a hypervisor or debugger | integrity hashes, hook scans, hypervisor and debugger checks |

agent-play falls into the third row. It never touches memory or network, but input automation alone is
a bannable category in every competitive online game.

## 2. Where detection runs

### 2.1 Client, user-mode
A module inside the game process, or a companion process, that scans its own address space for known
cheat signatures, verifies the game binary and loaded modules, checks for API hooks, enumerates
processes and windows, and reports to the vendor's servers. Valve's VAC, Blizzard's Warden and Roblox's
Hyperion (Byfron) work mostly here.

### 2.2 Client, kernel-mode (ring 0)
A signed driver with full system privileges. It can register system-wide callbacks for process, thread
and image-load events; refuse handles to the game process; verify every loaded driver against an
allowlist or a denylist of known-vulnerable drivers; check Secure Boot, TPM and hypervisor state; and
scan kernel memory for hooks. Riot Vanguard loads at boot and stays resident; Easy Anti-Cheat and
BattlEye load their drivers when a protected game starts. Kernel anti-cheat has the same reach as a
rootkit, which is why some users refuse to install certain games, and why a vulnerable such driver
(Genshin's `mhyprot2.sys`) has been abused by ransomware to disable antivirus software.

### 2.3 Server-side
The game server is authoritative: it simulates movement, fire rate, cooldowns and economy, and rejects
impossible states. It also runs statistics and machine learning over telemetry (aim traces, inputs per
second, reaction times, win rates, session lengths). VACnet (Valve), Ricochet's server signals
(Activision) and academic systems such as XGuardian are examples. It needs no software on the client,
so playing on Linux, on a console, or in a browser does not avoid it. Jagex (RuneScape) and chess
platforms ban bots with server-side analysis alone.

### 2.4 Platform and community
Steam enforces VAC bans account-wide. Consoles sandbox games and verify firmware. Replay review and
player reports feed human judgment into the pipeline.

## 3. Client-side techniques in detail

- **Integrity verification.** Hash the executable and every loaded module against the shipped manifest;
  walk import tables and function prologues for inline or IAT hooks; verify the driver's own callbacks.
- **Environment checks.** Secure Boot and TPM 2.0 state, hypervisor presence, debugger flags,
  test-signing mode, known virtualization vendors.
- **Driver and process inventory.** Enumerate kernel drivers against an allowlist (Vanguard) or a
  denylist of vulnerable signed drivers (EAC); enumerate processes, windows and overlays; flag anything
  with a handle to the game process or with screen-capture or input-injection capabilities.
- **Memory scanning.** Signatures of known cheats and heuristics for manually mapped modules and
  executable memory with no backing file.
- **Input provenance.** Windows marks `SendInput` events with the `LLMHF_INJECTED` flag, which low-level
  hooks read. Anti-cheat compares HID device enumeration against the events it sees, and watches for
  input arriving from a virtual device or a process rather than a real driver.
- **Attestation.** Obfuscated or virtualized challenge-response between the client module and the vendor
  server, so tampering cannot fake the answers.

## 4. Server-side techniques in detail

- **Sanity checks.** Movement speed, fire rate, cooldowns, inventory counts and position deltas are
  recomputed on the server; impossible claims are corrected or flagged.
- **Statistical anomaly detection.** Headshot ratio, time to target, reaction-time distribution, aim
  smoothness (human aim overshoots and corrects; a bot moves in straight lines or perfect curves),
  inter-action intervals (human intervals are noisy; automation is periodic), win rate against skill,
  playtime without breaks.
- **Machine learning on telemetry.** Models trained on labeled cheaters versus clean players over those
  features and raw input traces.
- **Report and replay review.** Reports raise a player's priority; replays let humans or models review
  the whole match.
- **Delayed enforcement (ban waves).** Detections are batched and applied days or weeks later, so a
  session that "worked" today can still be banned next month.
- **Hardware and account linking.** HWID fingerprints, phone numbers and payment data link new accounts
  to banned ones.

## 5. Why an automation agent specifically gets noticed

This is the part that applies to agent-play. It is here so the agent can warn truthfully, not so it can
hide: there is no weakness to exploit in this list.

1. **Synthetic input.** `SendInput`, `pynput`, `xdotool` and virtual HID devices are visible by the
   injected flag, by the missing hardware device, or by the sending process. Scancode-level `SendInput`
   still comes from a process, not a USB controller.
2. **Timing.** Fixed settle times, round-number key holds, identical intervals and no idle jitter form a
   periodic signal server-side models separate from human play.
3. **Precision and smoothness.** Exact-center clicks and single straight pointer jumps are not how hands
   move.
4. **Session shape.** Long sessions with no breaks, no mistakes, no camera wandering, no chat.
5. **Process inventory.** A process capturing the screen at a steady rate beside a game is itself a
   signal, as is any process holding a handle to the game.
6. **Outcome statistics.** Even disguised input produces win-rate and reaction-time distributions that
   server-side models catch over time.

The honest conclusion the agent gives the user: there is no careful way to run an automation agent in a
protected online game. The detection surface is the agent's own behavior.

## 6. Systems and the games that use them

| System | Vendor | Runs | Notable games |
|---|---|---|---|
| Riot Vanguard | Riot Games | kernel, boot-time, + server | Valorant, League of Legends, Teamfight Tactics |
| Easy Anti-Cheat | Epic Games | kernel (Windows), user-mode (Proton) | Fortnite, Apex, Rust, Dead by Daylight, Elden Ring online, Hunt, The Finals, War Thunder, New World, Lost Ark, Fall Guys |
| BattlEye | BattlEye | kernel + server | PUBG, Rainbow Six Siege, DayZ, Tarkov, Arma 3, Destiny 2, GTA Online, Ark, Conan Exiles |
| Ricochet | Activision | kernel + server ML | Call of Duty: Warzone, Modern Warfare, Black Ops |
| EA Javelin | Electronic Arts | kernel | Battlefield 2042/6, EA Sports FC, Madden (PC) |
| VAC / VACnet / Overwatch | Valve | user-mode + server ML + replay | Counter-Strike 2, Dota 2, Team Fortress 2 |
| FACEIT AC | FACEIT | kernel | CS2 and other ladders on FACEIT |
| Hyperion (Byfron) | Roblox | user-mode anti-tamper + server | Roblox |
| Warden | Blizzard | user-mode + server | World of Warcraft, Diablo IV, Overwatch 2, Hearthstone |
| HoYoProtect (mhyprot) | HoYoverse | kernel | Genshin Impact, Honkai: Star Rail, Zenless Zone Zero |
| nProtect GameGuard, XIGNCODE3 | INCA, Wellbia | user-mode and kernel | Korean MMOs: Lineage, PSO2, Black Desert |
| Server-side only | Jagex, Chess.com, Lichess, Minecraft servers | server | RuneScape, chess platforms, multiplayer Minecraft |

Consoles: no third-party driver, but platform sandboxing plus the same server-side analysis. Lichess
allows bots only through its official Bot API with a BOT-flagged account, never through the UI.

## 7. The policy the agent applies

The registry assigns each game a risk tier. The tier drives how loudly the agent warns, not whether the
user is allowed to decide. By default the agent warns and continues; `--block-protected` makes the
highest tier a hard stop.

| Tier | Meaning | Agent behavior (default) |
|---|---|---|
| `refuse` | Kernel or client anti-cheat, online competitive, or terms forbidding automation | State the system and the ban risk early; `ask_user` to confirm they accept it before acting unless they already said to go ahead; offer a safe alternative |
| `warn` | Online or server dependent, no known client anti-cheat | Warn once, record it, continue with clearly allowed activity |
| `ok` | Offline, single-player, the simulator, owned emulated games, games that allow bots | Play |
| `unknown` | Not in the registry | Proceed for single-player; ask if the task mentions ranked/multiplayer/online/PvP/leaderboard |

Decision order: the registry by name or alias; online keywords in the task; signals on screen (a
launcher naming an anti-cheat, a matchmaking queue, other players' names); finally the user's own
statement. Examples: Valorant and CS2 are `refuse`; Minecraft is `warn` (single-player fine, servers
run their own plugins); Stardew Valley and the simulator are `ok`.

## 8. Consequences, for the record

Account bans (often permanent), hardware bans, loss of purchased content, platform-wide propagation
(VAC), and for kernel drivers a privacy and stability cost on the user's machine. Ban waves mean the
consequence can arrive weeks after the session.

## 9. Sources

- Wikipedia, [Kernel-level anti-cheat](https://en.wikipedia.org/wiki/Kernel-level_anti-cheat) and [Easy Anti-Cheat](https://en.wikipedia.org/wiki/Easy_Anti-Cheat)
- "If It Looks Like a Rootkit and Deceives Like a Rootkit: A Critical Examination of Kernel-Level Anti-Cheat Systems", [arXiv 2408.00500](https://arxiv.org/pdf/2408.00500)
- "XGuardian: Towards Explainable and Generalized AI Anti-Cheat on FPS Games", [arXiv 2601.18068](https://arxiv.org/pdf/2601.18068)
- Landscape overviews consulted (treat blogs as secondary to the papers and vendor docs): [gameluster](https://gameluster.com/gambling/how-anti-cheat-really-works-in-big-2026-online-games-and-wha/), [tech-insider](https://tech-insider.org/riot-vanguard-vs-eac-vs-battleye-vs-ricochet-vs-vac-2026/), [commandlinux](https://commandlinux.com/blog/how-anti-cheat-systems-on-linux-actually-detect-aimbots-and-esp-hacks)

## Glossary

- **Ring 0 / kernel-mode**: code running with full operating-system privileges, as a driver.
- **HWID**: a fingerprint built from hardware serial numbers, used to link accounts.
- **Ban wave**: delayed, batched enforcement of accumulated detections.
- **Attestation**: a client proving to a server that it runs unmodified code.
- **Synthetic input**: keyboard or mouse events created by software rather than a physical device.
