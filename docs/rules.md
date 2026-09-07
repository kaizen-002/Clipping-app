# Coding Rules

Binding for all code in this repository. When a rule conflicts with a request, say
so before writing the code rather than silently breaking the rule.

## SOLID

### Single Responsibility
A module has one reason to change. The test is not "is this file short" — it is
"can I name a single actor whose changing needs would force me to edit this file".

In this project: fetching, transcribing, hook detection, caption generation and
rendering each change for different reasons — a `yt-dlp` flag change, a Whisper
model swap, a prompt revision, a style tweak, an FFmpeg upgrade. They are separate
modules for that reason, not because layering is tidy.

### Open/Closed
Extend by adding code, not by editing a working branch. When a `switch` over a type
gains a fourth case, move to a lookup table or polymorphism — not on the first case.

### Liskov Substitution
Any implementation of an interface must work wherever that interface is expected,
without the caller checking which one it got. If a caller needs `isinstance`, the
abstraction is wrong.

### Interface Segregation
Callers depend only on the methods they use. A five-method interface where every
consumer uses two is three methods of false coupling.

### Dependency Inversion
Business logic depends on abstractions; the concrete adapter is injected at the
edge. The core must not import `yt_dlp`, `faster_whisper`, the Ollama client, or
`subprocess` directly.

**This rule and KISS pull in opposite directions here. The carve-out is below and
it is not open to re-litigation in review.**

## The ports carve-out

KISS says no abstraction with exactly one implementation. Dependency Inversion says
the core must not import the tools. In this project every port has exactly one
adapter, so read literally the two rules deadlock and the first feature stalls in a
style argument.

**Resolution.** Exactly these four ports exist, each with one adapter, and their
existence is settled:

| Port | Adapter | Why the seam is worth it |
|---|---|---|
| `MediaSource` | `YtDlpSource` | Tests must run without network or YouTube |
| `Transcriber` | `FasterWhisperTranscriber` | Tests must run without model weights, and the survey and precise passes are the same port with different settings |
| `HookFinder` | `OllamaHookFinder` | Tests must run without a model server, and the PRD mandates a deterministic fallback — so this port genuinely has two implementations |
| `Renderer` | `FfmpegRenderer` | Tests must run without spawning FFmpeg or writing hundreds of megabytes |

The justification is **testability, not future flexibility**. Each seam is what
lets the pipeline be tested with a fake in milliseconds instead of end-to-end in
twelve minutes. That is a present, measurable benefit, which is what KISS actually
asks for — it forbids speculative generality, not seams that pay today.

**A fifth port requires an explicit decision recorded in the PRD.** The carve-out
is a closed list, not a licence to add interfaces.

## DRY — rule of three, same reason to change

Duplicate code is not automatically a defect. Abstract only when **both** hold:

1. The pattern has appeared three times, and
2. All three copies would change **for the same reason**.

If two pieces of code look alike but change for different reasons, they are
coincidentally similar, not duplicated. Merging them couples unrelated parts of the
system, and the next change adds a boolean parameter, then another, until nobody
can safely edit the shared function. That coupling costs more than the duplication
it removed.

Concretely here: the survey transcription call and the precise transcription call
look nearly identical and are **not** duplication — one optimises for speed over an
hour, the other for word-level accuracy over a minute. They will diverge. Leave
them apart.

## KISS

Ship the simplest implementation that satisfies the acceptance criteria in `PRD.md`.

- No abstraction with exactly one implementation, **except the four ports above**.
- No configuration option nobody asked for.
- No caching, queueing or batching before a measurement shows it is needed. The
  per-stage timings in the PRD's Performance Budget are the measurement that would
  justify it — collect them first.
- Solve the case in front of you.

## Numbers must be computed

No measurement, ratio, duration or performance figure enters a document or a code
comment unless it was produced by running something. If it cannot be computed yet,
write the range and mark it an estimate.

This rule exists because the first version of `design.md` stated eight contrast
ratios and every one was wrong — including four it marked as passing — and the
first `PRD.md` set a 5-minute performance target that was roughly a third of what
the transcription stage alone requires. Both read as authoritative. Both were
invented.

`scripts/contrast.py` is the source of every ratio in `design.md`, and it exits
non-zero on a failure. Run it after any colour change.

## Working agreements

- **Scope.** Read `PRD.md` before starting a feature. If the work is not in MVP
  Scope, stop and say so. If it is in Out of Scope, refuse and explain.
- **Decisions.** `PRD.md` contains items marked `DECISION`. Do not build past one
  that is still open; the answer changes the code.
- **Design.** Read `design.md` before writing UI **or the caption renderer**. Use
  the defined tokens. Never introduce a raw hex, size or duration outside the token
  set. The caption tokens are tokens: the ASS generator emits them, it does not
  invent values.
- **Two token scales.** UI motion tokens are for the interface; caption motion
  tokens are for the rendered video, frame-quantised at 30 fps. Never mix them.
- **Files, not a database.** This project has no database and no `schema.md`. On
  disk: `input/` fetched media, `work/` intermediates, `output/` finished renders.
  Honour the retention policy in `PRD.md` — `work/` cleared per run, `input/` aged
  out at 7 days or 5 GB, `output/` never auto-deleted. Hour-long video downloads
  fill a disk quickly, and nothing else in the system will notice.
- **Model output is untrusted input.** Anything from Llama 3 is validated against a
  Pydantic model and range-checked before use. A timestamp from a model is a claim,
  not a fact. The validation ladder and fallback are specified in `PRD.md`; a
  failure path that ends in an unhandled exception is a bug, not an edge case.
- **The documents are one set.** `PRD.md`, `design.md` and `rules.md` are read
  together. If a change makes any of them wrong, fix it in the same commit, and
  check whether the change contradicts the other two. A stale document is worse
  than a missing one, because it will be trusted.
- **Errors.** Handle the failure path explicitly. No empty `except`. No error
  swallowed to make a test pass.
- **Naming.** Names state intent. `data`, `temp`, `handle2` and `utils` are not
  names.
- **Comments.** Comment why, not what. Delete commented-out code.

## Stack conventions — Python

- Type hints on every public function; a type checker runs in CI. Unchecked hints
  drift immediately.
- Dataclasses or Pydantic models between layers, never bare dicts. A dict is an
  untyped contract.
- Virtual environment plus a lock file. Never install into the system interpreter.
- Exceptions are specific. Bare `except:` is banned; `except Exception` needs a
  comment saying why that breadth is correct.
- I/O lives at the edges. Core logic takes values and returns values, so it can be
  tested without network, model weights or FFmpeg.
- **Subprocesses are adapters.** `yt-dlp` and FFmpeg are invoked with argument
  lists, never a shell string, never with user input interpolated into a command.
  A pasted URL reaching a shell is a command injection.
- **Long operations report progress.** Any stage over a second yields structured
  progress events. A twelve-minute pipeline that prints nothing is indistinguishable
  from a hung one.
- Format and lint with one configured tool. Style is not a review topic.
