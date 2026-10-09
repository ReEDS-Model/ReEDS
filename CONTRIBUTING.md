# Contributing to ReEDS

Community contributions to ReEDS are welcome and encouraged!

For questions or general discussion, please open a [discussion](https://github.com/ReEDS-Model/ReEDS/discussions). To report a bug, please open an [issue](https://github.com/ReEDS-Model/ReEDS/issues).

To contribute code, fork the repository, make your changes, and submit a pull request. Please review our [Developer Guide](https://reeds-model.github.io/ReEDS/developer_best_practices.html) before getting started.

**Note:** if you're considering making a change that might lead to meaningful differences in model capability, workflow, or outputs, we recommend initiating a [discussion](https://github.com/ReEDS-Model/ReEDS/discussions).

## ReEDS AI Policy
Contributors are responsible for understanding and verifying every change they make, regardless of how it was produced.

### AI Use Requirements
* **DON'T** submit fully AI-driven contributions.
* **DON'T** let AI tools make direct commits or auto-merge PRs. 
* **DON'T** use AI to write PR descriptions.
* **DON'T** use AI-generated text in `model_documentation.md`. All text there must be original. *See below for permitted AI uses in this file*.
* **DO** disclose AI use in the PR template's LLM section, including *how* you verified any LLM-generated content.
* **DO** include verification for PRs with meaningful AI contributions so the reviewer can confirm correctness without rederiving the change themselves.
* **DO** make sure any AI-assisted comments or docstrings read naturally and don't carry an "AI voice."

> [!NOTE]
> Permitted AI uses for `model_documentation.md` include:
> * Proofreading your own text
> * Trivial, easily verified edits (e.g., replacing a citation, updating a numeric value)
> * Identifying where in the documentation a change should go

### Recommended Practices
**Planning and scope**
* Start in plan mode, and include a verification step in the plan.
* Break larger efforts into multiple PRs.
* Have the AI tool pause at checkpoints for human review before proceeding.

**While developing**
* If you don't understand why a change was made, dig into it before moving on.
* Ask a separate AI tool to review your change.
* Use an `AGENTS.md` file. The repo's [AGENTS.md](AGENTS.md) file can be used as-is.