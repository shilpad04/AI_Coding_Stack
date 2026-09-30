# input/

Drop a PRD (Product Requirements Document) here when the work is big enough to
need one: a new product, or a feature that spans several tasks.

**Small work needs no PRD.** For a bug, a ticket or a small feature, just tell
your AI in chat, e.g. "fix the 500 on login". It plans it as one task and goes
through the same approval, gates and tests.

## Convention

- One file per project or feature: `my_project_prd.md`
- See `focus_game_prd.md` for an example

## Next step

Open your AI assistant and say:

> "Phasify input/my_project_prd.md"

The AI will read the PRD, break it into phases and tasks,
and write `.ai/plan.json`. Review the plan, approve it by running
`python .aistack/scripts/approve_plan.py --all`, then say "start phase 1".
(Until you approve a task this way, the validator pauses that task.)
