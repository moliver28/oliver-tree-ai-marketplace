# Learned invocation terms

`phrases.log`: append-only, zero-LLM. After each successful /voice run, the command appends one line:
`<date>\t<verbatim user input>`. No model tokens; a shell redirect.
Maintenance passes distill recurring phrasings into plugin descriptions per MAINTENANCE.md section 10.
