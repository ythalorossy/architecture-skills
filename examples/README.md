# Example output

`bookshop/` is what the `c4-diagrams` skill produces for the synthetic repository in [`tests/fixtures/repos/bookshop`](../tests/fixtures/repos/bookshop): a React web app, a FastAPI service, a PostgreSQL database, another team's search index and a payment provider. Start with [`bookshop/ArchitectureReport.md`](bookshop/ArchitectureReport.md).

It is the full pipeline: the analyzer's facts, the agent's `c4-model.json` (people, descriptions, a key flow, a Level 4 component and a summary), and the diagrams `render_c4.py` drew from both.

`tests/test_docs.py` fails when the committed diagrams no longer match what the code produces. To regenerate (needs Node.js for the SVGs), from the repository root:

```bash
rm -rf examples/bookshop
python3 skills/c4-diagrams/scripts/analyze_repository.py tests/fixtures/repos/bookshop --output examples/bookshop
cp tests/fixtures/repos/bookshop/c4-model.json examples/bookshop/
python3 skills/c4-diagrams/scripts/render_c4.py examples/bookshop
```
