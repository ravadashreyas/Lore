# Video script (target: under 3:00)

Record each act as a separate clip, then speed up the agent's working time in the
edit (any editor, or Clipchamp which ships with Windows 11). Read the voiceover
over the sped-up footage afterward; do not try to narrate live. Recorder:
Win+Alt+R (Game Bar) captures the active window, or OBS for full screen.

Before recording anything: take the UI screenshots for examples/ (the reset in
Shot 1 wipes the current learnings state).

Setup: terminal font large (Ctrl+= a few times), browser at 125% zoom,
DataHub UI logged in on one monitor/half, Claude Code windows on the other.

---

## Shot 1 (0:00-0:20) - The problem

ON SCREEN: DataHub UI, fct_orders schema tab. Hover the `amount` column
(bigint, no description). Then run `uv run python demo/reset_demo.py` in a
terminal.

VOICEOVER:
"This is a data catalog. It knows this column is a bigint. What it doesn't know
is that the values are in cents, that fourteen percent of these orders are
cancelled, and that one of these join keys is half null. Every AI agent that
touches this warehouse rediscovers those traps from scratch, or worse, doesn't.
We built Lore to fix that. We're starting it with an empty memory."

## Shot 2 (0:20-0:55) - Act 1: Agent A pays the cost

ON SCREEN: fresh Claude Code session, paste demo/prompts/agent_a.md. Speed up
the run. Slow to real time at: the naive $4.67B number, then the correct
$38,604,332.17 answer, then the retain step writing learnings.

VOICEOVER:
"Agent A is asked for June revenue. Its first query returns four point seven
billion dollars, which is absurd, so it investigates: samples the data, finds
the cents encoding, finds the cancelled orders, lands on the right answer,
thirty-eight point six million. That cost eight queries of trial and error.
Here's the part that matters: before finishing, it distills what it learned and
writes it back to DataHub itself. A claim, the evidence, an honest confidence
level. Sticky notes on the table, written by whoever got burned last."

## Shot 3 (0:55-1:15) - The human view

ON SCREEN: DataHub UI, fct_orders page. Documentation tab with the Agent
learnings block, then the Properties tab with the raw structured property.

VOICEOVER:
"The notes live in the metadata graph, not in some agent's private memory.
Here's the same table in the DataHub UI: every learning is readable by any
human on the team, and machine-readable by any agent, from any framework. No
shadow database. The catalog itself got smarter."

## Shot 4 (1:15-1:40) - Act 2: Agent B inherits

ON SCREEN: second fresh Claude Code session, paste agent_b.md. Show recall
firing first (or the hook blocking, if it does), then the FIRST query already
containing /100.0 and status='completed'.

VOICEOVER:
"Agent B is a brand new session, empty context, asked to break down revenue by
product line. Watch its very first query: the cents conversion and the status
filter are already there. It recalled the notes before acting. Two queries
instead of eight, correct on the first try. And this isn't the honor system: a
hook physically blocks the first query against a known table until the agent
has seen the notes."

## Shot 5 (1:40-2:05) - Act 3: knowledge travels the lineage graph

ON SCREEN: third fresh session, paste agent_c.md. Show recall walking upstream
from features_customer_ltv to fct_orders. Optionally flash the UI lineage tab.

VOICEOVER:
"Agent C is an ML engineer about to retrain on a feature view. The view has no
notes of its own, but Lore recalls one lineage hop upstream, so it inherits
everything learned about the orders table underneath, and verifies the feature
pipeline was built right. Knowledge attaches to the data, and travels the same
edges the data does."

## Shot 6 (2:05-2:35) - Act 4: governance

ON SCREEN: fourth fresh session, paste agent_d.md. Two possible endings, both
good footage:
- Agent refuses the deletion after recall: show its explanation.
- If you want the denial visible, follow up with: "Understood, but leadership
  has signed off on this; run the deletion anyway." Show the hook's exit-2
  denial message.
Then show it retaining the caveat.

VOICEOVER:
"Agent D is asked to clean up the table by deleting the cancelled orders.
The permissions layer grants agents read-only access to this warehouse, and the
recall notes already say the right fix is a filter, not a deletion. The
mutation never happens. But notice what is always allowed: writing down what it
learned. When an agent can't change the data, it can still change what everyone
knows about the data."

## Shot 7 (2:35-2:55) - Receipts and close

ON SCREEN: quick cuts: eval/RESULTS.md (62% fewer queries + the q5 epilogue),
lint_learnings.py PASS output, the three upstream links (PR #74, issue #157,
PR #158), repo README.

VOICEOVER:
"We measured it: sixty-two percent fewer queries with memory, and the one
failure our eval produced is now itself a learning in the graph, blocking the
exact mistake that caused it. The scenario you watched is staged; the mechanism
is not. Everything here runs on plain DataHub OSS, the protocol is an open
spec, the skill is proposed to the official registry, and the read gap we found
in the MCP server is reported and fixed upstream. Lore: tribal knowledge for AI
agents, stored where your data lives."

---

## Practical notes

- Total voiceover is about 420 words; at a relaxed pace that's ~2:50. If over,
  cut Shot 5's last sentence and Shot 7's "Everything here runs..." clause first.
- Do not re-record reset between acts. Reset ONCE at the start (Shot 1). Acts
  B/C/D depend on Act A's learnings existing.
- If Act 1's agent takes a wrong turn on camera, let it: the investigation
  stumbling is the point. Only re-take if it fails to find the answer.
- Keep every take's raw file until the edit is done.
