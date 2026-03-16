# Prompting Patterns — OSCAL/SSCF Multi-Agent System

These are the prompting patterns that work well for this system. The approach: short prompts at expert level, not long waterfall specs.

## Starting A Session

### Session Start (Standard)
```
Continue work on saas-assurance. Read mission.md and AGENTS.md first, then tell me the current state.
(Session notes are in Obsidian vault — saas-assurance/Next Session.md)
```

### Session Start (Live Assessment)
```
I have a Salesforce org called [alias] in [env] environment.
Run a full OSCAL/SSCF assessment and generate both the app-owner deliverable and the Security Team gap matrix.
Which org connection method do you need from me?
```

### Session Start (Gap JSON Provided)
```
Here is the gap JSON from [org/source]: [path or paste]
Run this through the OSCAL pipeline and generate the latest deliverables.
```

## During Assessment

### Context Gap Discovery
```
Do you have any questions for me before you proceed?
```
(Ask this before every major step. Agents find context gaps they cannot resolve alone.)

### Pausing For Review
```
Before you generate the final output, show me the critical and high fail findings first.
I want to review them before the reporter runs.
```

### Forcing Deep Analysis
```
Take your time on the SSCF mapping for [control group].
I want you to verify each mapping against the sscf_control_index.yaml before confirming confidence.
```

## After Assessment

### Retrospective (Build Quality)
```
Now that you have completed this assessment, what would you have done differently?
```

### Refactoring Prompt
```
Now that you have run this pipeline end-to-end, what can we refactor to make it faster or more reliable?
```

### Exception Triage
```
Look at all findings with status=fail and severity=critical.
For each one, tell me: is there an existing exception, or do we need to start the exception process?
Reference docs/saas-baseline/exception-process.md for the required fields.
```

## NIST AI RMF Review

### Requesting Validation
```
Run the nist-reviewer agent against the latest backlog and deliverable.
Return the structured verdict and flag any blocking issues.
```

### Overriding A Flag (Human Acknowledgment)
```
I acknowledge the NIST AI RMF flag: [paste flag from nist-reviewer output].
The output may proceed. The flag is noted for the governance record.
```

## Research Mode

### CVE Impact Assessment
```
Switch to research mode.
CVE-[ID] affects Salesforce [component].
What SBS and SSCF controls does this touch, and do we need to update any collector scopes?
```

### Control Definition Lookup
```
Switch to research mode.
What does SBS-ACS-003 require, how do we currently assess it, and what is its SSCF mapping?
```

## Proactive / Scheduled

### Weekly Drift Check (Heartbeat Prompt)
```
Run a proactive SSCF drift check against the last known backlog.
Do not run a new live assessment — compare docs/oscal-salesforce-poc/generated/salesforce_oscal_backlog_latest.json
against the current sscf_control_index.yaml and report any changes.
```

### Monthly Governance Pack Refresh
```
Generate the monthly governance pack from the latest backlog.
Produce: app-owner DOCX, Security Team gap matrix MD, and NIST review section.
Use today's date in the filename. Commit and push when done.
```

## Anti-Patterns (What Not To Do)

These prompts produce worse results:

BAD: "Analyze my Salesforce security posture and give me a comprehensive report covering all possible risks."
WHY: Too vague. No org, no scope, no audience, no output format.

BAD: "Run the full pipeline and handle everything automatically."
WHY: Skips the human checkpoints that mission.md requires.

BAD: "Just give me the results without the NIST review section."
WHY: Bypasses a required quality gate. The nist-reviewer runs on every output.

GOOD: "Run the assessor against this gap JSON. Show me the critical/high fail findings before you hand to reporter."
WHY: Scoped, includes a human checkpoint, clear scope.
