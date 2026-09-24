# input/

Drop your PRD (Product Requirements Document) here.

## Convention

- One file per project: `my_project_prd.md`
- Use the template in `docs/PRD_TEMPLATE.md` as a guide

## Next step

Open your AI assistant and say:

> "Phasify input/my_project_prd.md"

The AI will read the PRD, break it into phases and tasks,
and write `.ai/plan.json`. Review the plan, approve it by running
`python scripts/approve_plan.py --all`, then say "start phase 1".
(Until you approve a task this way, the validator pauses that task.)
