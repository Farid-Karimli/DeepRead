# DeepRead

Bridging the Gap Between Academic Theory and Implementation.

DeepRead is an augmented research consumption system designed to eliminate the "documentation debt" in ML and HCI research. It creates a live, bidirectional mapping between a research PDF and its source code, allowing researchers to see exactly how abstract equations and methods are implemented in practice. 

## Status

This project is currently being developed at Boston University. We aim to evaluate how DeepRead reduces cognitive load and improves implementation accuracy for graduate-level researchers.

## Get Started

This project uses [uv](https://docs.astral.sh/uv/#projects) and the [Claude Code SDK](https://platform.claude.com/docs/en/agent-sdk/overview). Follow the respective instructions to these up.

To start using DeepRead:

```{python}
git clone https://github.com/Farid-Karimli/DeepRead.git
cd DeepRead
uv sync
source .venv/bin/activate # If on Windows, .venv\Scripts\Activate
```

Run the test scripts:

```{python}
uv run python deepread/main.py
```

**Something to be aware of**:

There's a bug in Claude Code SDK where the LLM ignores explicitly set output schema. For that reason, you might see 'No result found...', but the print result should show the result. Often times, Claude adds a little text before providing JSON, like "Based on the context, here is the...".


## Planned Features

- Semantic Cross-Linking: Click an equation or a paragraph in the PDF to instantly highlight the corresponding implementation in the repository.

- Gap Analysis: Automatically identifies "missing" logic—flagging instances where a paper claims a method that isn't reflected in the released code.

- Implementation Tooltips: Hover over technical jargon in the text to see a "Code-First" explanation (e.g., seeing the PyTorch tensor shapes for a "spatio-temporal mask").

- Faithfulness Scoring: A heuristic-driven metric that evaluates how closely the code follows the paper’s conventions and completeness.

## How it Works

- PDF Parsing: Extracts text, equations, and figures using specialized LaTeX-aware parsers.

- Repo Analysis: Scans the linked GitHub repository, building a dependency graph of the codebase.

- Alignment Engine: Uses a combination of LLMs and static analysis to map mathematical symbols and method descriptions to specific code snippets.

- Interactive UI: A split-pane web interface for synchronized reading and code exploration.
  