## Summary

<!-- 1-3 bullet points describing what changed and why -->

-

## Test plan

<!-- How you verified these changes -->

- [ ] All existing tests pass (`uv run pytest tests/ -v`)
- [ ] Added new tests for the changed behavior
- [ ] Tested GUI changes in both live and review mode
- [ ] Tested CLI path (`uv run council "test query" --no-confirm`)

## Screenshots

<!-- If the change affects the GUI, include before/after screenshots -->

## Checklist

- [ ] My change is one concern (not mixing features with bug fixes)
- [ ] New agents/tasks are in `config/agents.yaml` and `config/tasks.yaml`
- [ ] I updated `README.md` if user-facing behavior changed
- [ ] No debug code, commented-out blocks, or unnecessary comments
