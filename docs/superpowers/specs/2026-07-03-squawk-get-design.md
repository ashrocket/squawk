# `/squawk:get` UX Evaluation — Design Spec

**Branch:** `explore/squawk-get` (off `main`, isolated from the in-flight
`feature/handsfree-voice` work)

## Goal

Explore a new Squawk capability — `/squawk:get <url>` — that fetches a web
document, summarizes it, and speaks the summary aloud through Squawk, with
multiple summarizer/reader/voice personalities to compare. Before writing any
product code, manually simulate the whole experience once, capture what
actually felt useful vs. repetitive vs. noisy, and use that to propose the
smallest implementation worth building.

## Non-goals (this spec)

- No changes to `speak.py`, `voice_chat.py`, or the `claude-plugin/` command
  set. The manual simulation must work entirely with what already exists
  today (`speak.py` CLI, `squawk-say`/`squawk-mode` commands, WebFetch/agent
  tooling available to whatever Claude Code session runs it).
- No diagnosis of the global Codex `~/.codex/hooks.json` Stop-hook issue
  raised in a separate paste during brainstorming. That is an unrelated
  global dev-environment concern (not part of this repo), the hooks file
  already redirects `cmux` stderr to `/dev/null` and falls back to `{}` on
  invalid JSON (i.e. the described failure mode may already be fixed), and
  another agent was already working it live. Out of scope here.
- No decision yet on whether `/squawk:get` ships as a real command — that's
  the output of phase 2, not an input to it.

## Two-phase structure, two sessions

**This session (planning only):** produces this spec, then an implementation
plan for the phases below via the `writing-plans` skill. No execution.

**A new session executes the plan end-to-end:**

### Phase 1 — Manual simulation (no code changes)

1. Fetch and read `https://www.1password.dev/environments`.
2. Produce two summaries of the document via two subagents with distinct
   personas, both using the cheapest/fastest capable model for this first
   pass (e.g. Haiku-tier):
   - **Agent #1 — practical implementation-focused summarizer.**
   - **Agent #2 — user-facing explainer summarizer.**
3. Trim each summary to its first three sentences for the spoken version.
   Readers (step 5) rewrite these three sentences in their own delivery
   style but should stay roughly the same length — this is a style pass,
   not a new composition.
4. Voice pool for this run — 2 Kokoro + 2 Apple Premium, deliberately
   crossed on accent/gender so the two engines are directly comparable:
   - `kokoro:af_heart` (US, F) vs. `Ava (Premium)` (US, F)
   - `kokoro:bm_lewis` (GB, M) vs. `Jamie (Premium)` (GB, M)
5. Three reader personalities — each is a distinct rewrite pass over the
   3-sentence summary (not just a voice choice), performing as if voicing
   the original researcher:
   - **Field Briefer** — terse, radio-operator cadence.
   - **Enthusiastic Explainer** — warm, conversational, natural fillers
     ("so basically," "the cool part is").
   - **Skeptical Reviewer** — measured/dry, rhetorical pause before caveats,
     stresses risk/limitation words.

   Prosody techniques available **today, with zero code changes**
   (verified against the current `speak.py`/`kokoro_onnx` code):
   - `say`-backed voices (default + all Premiums): `speak.py` passes text
     to `say` as a raw, unescaped argv string, so macOS's documented
     embedded speech commands work directly — `[[slnc 300]]` (pause, ms),
     `[[rate 180]]`, `[[emph +]]`/`[[emph -]]`, `[[pbas ±N]]`/`[[pmod ±N]]`
     (pitch).
   - Kokoro voices: `kokoro_onnx.Kokoro.create()` only accepts
     `text/voice/speed/lang/is_phonemes` — no markup language — and
     `speak.py` currently hardcodes `speed=1.0` for Kokoro (`--rate` is
     `say`-only). So pacing/pauses/emphasis/"um" on Kokoro voices can only
     be expressed through wording and punctuation itself (em dashes,
     ellipses, literal "um,", short clauses).
   - Readers should exploit `[[...]]` markup on the two `say` voices and
     rely on phrasing tricks on the two Kokoro voices. Note in the UX
     writeup how different that feels — this asymmetry is itself a finding.
6. For every voice, announce it in ~3 seconds with no extra context, in
   this exact format before its block of readings (voice id shown here is
   illustrative — substitute the actual voice id being announced, e.g.
   `voiceid:af_heart`, `voiceid:Ava`):

   ```
   voiceid:nicole
   This 1Password article describes how users can query their 1Password
   vaults for values normally stored in .env files.
   ```

7. Run the full presentation matrix, in order, for all three readers:

   ```
   Reader #1 × Agent #1 summary × Voice #1, #2, #3, #4
   Reader #1 × Agent #2 summary × Voice #1, #2, #3, #4
   Reader #2 × Agent #1 summary × Voice #1, #2, #3, #4
   Reader #2 × Agent #2 summary × Voice #1, #2, #3, #4
   Reader #3 × Agent #1 summary × Voice #1, #2, #3, #4
   Reader #3 × Agent #2 summary × Voice #1, #2, #3, #4
   ```

   28 total spoken utterances (24 combos + 4 voice IDs). Run all of them —
   don't sample. `speak.py` blocks until each finishes, so this will take
   several real minutes; that repetition is itself part of what's being
   evaluated (see UX notes below).

8. Capture UX notes as the run proceeds, covering:
   - What felt successful vs. too repetitive vs. too noisy.
   - Preferred summary style (Agent #1 vs #2, or a blend).
   - Preferred reader/delivery style.
   - Preferred voice, and whether the Kokoro/Premium prosody asymmetry
     mattered in practice.
   - Feedback-loop shape: how should future runs learn these preferences
     without asking the user to sit through the full matrix again?

### Phase 2 — Implementation proposal

Using the UX notes, propose the smallest useful `/squawk:get` implementation:
command syntax, fetch layer, summarizer-agent interface, voice-selection
behavior, reader-personality behavior, feedback/tuning storage, and test
harness changes. No code is written yet — this is still a proposal.

## Verification required (of the new session's run)

- Source document URL actually fetched.
- Model/agent used for each summary.
- Exact voices and reader personalities used.
- What was actually spoken (or queued) through Squawk, in what order.
- The UX notes: what felt successful, what felt repetitive, what should
  change before this becomes a real command.

## Workspace

New branch `explore/squawk-get`, based on `main`, created in the existing
working directory (verified `main` and `feature/handsfree-voice` have
identical committed blobs for every file currently dirty in this tree, so
the branch switch carried the uncommitted handsfree WIP over with zero
conflicts). Only this spec, its implementation plan, and the new session's
UX-notes output should ever be staged/committed on this branch — the
handsfree files sitting in the working tree are left alone.
