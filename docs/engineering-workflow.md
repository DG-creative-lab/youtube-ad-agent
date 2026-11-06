# Engineering workflow

Keep repo-wide rules in [AGENTS.md](../AGENTS.md) and load the relevant skill for the task. The repo skills carry the project-specific procedure. General design, testing and review skills can supplement them when the work calls for deeper analysis.

| Task | Playbook |
| --- | --- |
| Build a feature, change behavior or implement a screen | [Campaign engineering](../.agents/skills/campaign-engineering/SKILL.md) |
| Decide what to test or review existing coverage | [Campaign tests](../.agents/skills/campaign-tests/SKILL.md) |
| Review a consequential change or inspect a trust boundary | [Adversarial review](../.agents/skills/campaign-adversarial-review/SKILL.md) |

## Verification

Run the offline suite locally for behavior changes. GitHub Actions runs the same command on pushes to main and pull requests.

```sh
python3 -m unittest discover -s tests -v
```

Exercise affected UI behavior in the browser. Use the [design direction](design-direction.md) for visual and accessibility checks. Keep live model, provider and human usability evidence separate from the offline suite.
