# ACS Skill runtime presentation

## Objective

Present enough ACS knowledge for an Agent to recognize the governing model and
retrieve the right detail while keeping unrelated domains outside active
context.

## Presentation stages

### Stage 1: metadata

The Harness receives Skill name and a high-signal description. Descriptions name
the domain entities, authority questions and conditions that make the Skill
relevant. They avoid generic phrases such as manage a project or complete work.

### Stage 2: domain router

When a request or tool result matches the description, load SKILL.md. The file
contains:

- one knowledge boundary;
- four to six core invariants;
- a question-to-reference retrieval map;
- relevant tool vocabulary;
- links to adjacent domains.

This layer should normally fit in a small context slice.

### Stage 3: targeted reference

Follow one reference for the current material question:

- model.md for identity, state, authority or storage;
- decisions.md for choosing boundaries or interpreting cases;
- tools.md for parameter, result and readback implications.

Expand into a second Skill only when the task crosses its stated boundary.

### Stage 4: project evidence

Use load_project, ProjectContextPack, AGENTS, SourceBindings and project
knowledge for current project facts. Product Skills describe ACS semantics;
project context supplies project-specific goals, state and policy.

## Runtime routing signals

A route can be activated by:

- user language naming a domain entity or decision;
- current resource kind, such as Review, Lease or SourceBinding;
- an MCP error or state such as revision conflict, stale context or uncertain
  effect;
- knowledge_hints returned in structured result metadata;
- explicit Skill invocation.

A knowledge_hint has this form:

~~~json
{
  "skill": "acs-source-evidence",
  "topic": "source synchronization",
  "reason": "the handoff contains an unpushed commit",
  "reference": "references/decisions.md"
}
~~~

The hint is advisory. The Agent verifies relevance and reads the smallest
material source.

## Recall and context tradeoff

Improve recall by:

- distinctive domain names;
- descriptions containing stable entities and common user language;
- ProjectContextPack hints based on resource types;
- tool-result hints at boundary states;
- cross-links for frequent domain intersections.

Limit context by:

- metadata-first discovery;
- one primary Skill per material question;
- references loaded by named question;
- no duplicated tool schema or project facts in Skills;
- bounded ProjectContextPack content;
- stopping retrieval when current evidence answers the question.

## Precedence and freshness

User instruction, active project instructions and authenticated Policy govern
actions. Skills explain ACS semantics. Current code, configuration, runtime
readback and project sources establish observed facts. Tool descriptions and
machine contracts establish invocation shape.

A Skill reference records durable semantics rather than current Project state.
Source and capability observations retain revision, evidence class and expiry.

## Quality measures

Evaluate the Skill layer with:

- retrieval recall for representative and indirect prompts;
- unnecessary-load rate;
- tool-selection accuracy after retrieval;
- project-context token cost;
- stale or contradictory knowledge findings;
- percentage of complex tasks resolved without pasted operating manuals;
- correct preservation of unknown and unresolved state.

Gate evidence includes the metadata initially shown, loaded Skill and references,
tool calls influenced by that knowledge, and the final evidence-bound result.