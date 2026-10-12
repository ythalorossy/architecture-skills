# Reading a degraded run

`summary.json` carries `status` and a `warnings` list. `status: "degraded"`
means something needs attention; every cause is in `warnings`, each with
`kind`, `message`, `source` and sometimes `path`.

| `kind` | What happened | What to do |
|---|---|---|
| `parse` | a file could not be parsed (bad TOML, bad XML, an encoding the reader could not decode) | it is also in `skipped_files`. Tell the user which file and why; whatever it declared is missing from the facts |
| `skipped` | a file could not be read at all (permissions, a broken link, over the size limit) | as above |
| `render` | a diagram failed to render | `syntax-error` is a bug in the diagram, usually a label in your model: fix the label and re-run `render_c4.py`. `timeout` and `tool-error` are environment problems — report them |
| `model_error` | `c4-model.json` did not validate, so `c4.model_status` is `"invalid"` and the diagrams fell back to facts-only | fix the listed errors and re-run `render_c4.py`. Until you do, the diagrams the user sees have no Context level and no flows |
| `detection` | nothing runnable was recognised, so the whole repository is one box. **Not** degraded | the detectors did not understand the stack. Find the runnable parts in the code and describe them in the model yourself |

`c4.model_status: "drift"` is also **not** degraded. It means the code has
facts the model does not cover yet: add them to the model, or list them in
`excluded` with a reason, and re-run `render_c4.py`.

Exit codes: a degraded run exits 2 under `--strict`, and 0 otherwise.

## One thing `summary.json` will not tell you

`summary.json` is written by `analyze_repository.py`. Running `render_c4.py`
on its own afterwards does **not** rewrite it, so once you have written
`c4-model.json` and rendered it, `summary.json` still reports the Step 1 state
— typically `c4.model: "facts-only"` and the shorter Step 1 diagram list. Read
`render_c4.py`'s own output for the state of your model, not `summary.json`.
