# S3 contract assets

`topics-v1.json` is a small Daily-authored vocabulary with stable IDs, parent
relationships and distinguishing examples. It is not an imported or certified
IPTC taxonomy. Its byte digest participates in the processing recipe. A changed
definition therefore creates a different recipe, even when the topic ID remains.

The default recipe is provisional and unpromoted. Its input, prompt, schema,
taxonomy, linker and query/document embedding definitions are fingerprinted.
Provider token limits are part of that identity. Promotion requires separately
labeled quality measurements; passing the deterministic contract tests does not
show that a model correctly interprets negation, causality or commercial intent.

## Evidence boundary

The frozen bundle contains normalized article title/summary and, when verified,
the selected original S2 artifact. It carries article semantic revision and
analysis-eligibility generation, exact provenance and evidence-field hashes.
Author, source, publication time, URL, language and candidate snapshots are also
hashed because they are visible to the classifier. Native reader permissions
are not analysis permission. `analysis_revoked=true` makes the bundle unusable.

An artifact must match the selected `analysis_content_artifact_id`, article
owner, current state and SHA-256 of its stored UTF-8 text. An origin extraction
must match the exact article URL and current extractor version. Feeds and APIs
require an exact trusted source acquisition URL and kind, plus source identity;
matching only the publisher domain is insufficient. Current repository rows do
not supply such reviewed S1 acquisition identities, so those artifacts fall
back to title/summary evidence. Never synthesize this trust from the artifact
itself, a display grant, or model output. Legacy or cross-source analysis text
never becomes attributed article evidence.

## Output boundary

Every asserted facet has a quote and normalized field offsets. Unknown/empty
fields have explicit abstention reasons. Entity/place IDs can only come from
the supplied bounded registry snapshot; unknown or ambiguous mentions remain
representable. Strict schema and span validation prove traceability, not that a
paraphrase or classification is true. Semantic correctness remains a measured
quality gate against independent labels.

The card, frozen body and evidence spans are private processing data. Consumers
must use the current-result loader, and public article serializers must not
expose this evidence. The query/document embedding recipe must be compatible
before any semantic lookup; finite, nonzero vectors alone do not prove that.
