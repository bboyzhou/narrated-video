# NarratedProject v1 architecture

## Decision

`NarratedProject v1` is the only persistent authoring model. JSON files emitted for RuntimePlan, RenderPlan, jobs, approvals, cache indexes and verification are derived execution or state records; they are never alternative project formats.

```text
Agent + narrated-video Skill
            │
  Image / TTS / I2V Providers
            │
     NarratedProject v1
            │ compile after asset realization
       RenderPlan v1
      ┌─────┼──────────┐
   FFmpeg Remotion OpenChatCut
```

## Ownership

| Data | Owner | Persistent project data |
| --- | --- | --- |
| Creative brief, approved narration, shots, Demo, style | NarratedProject | Yes |
| Provider selection and pinned model/service metadata | NarratedProject | Yes |
| Media source, license and content hash | NarratedProject/asset registry | Yes |
| Local executables, browser and model-cache paths | Runtime sidecar | No |
| Approval quotes and stage fingerprints | State sidecar | No |
| GPU, dtype, frame count, steps and offload | RuntimePlan | No |
| Realized frame timing and absolute asset paths | RenderPlan | No |
| Adapter fallback reason and feature loss | Adapter report | No |

## Compatibility

The loader detects v1 by `kind: NarratedProject`. Files without the discriminator are treated as legacy v1 configuration and combined with their referenced storyboard in memory. Migration writes `narrated-project.json` beside the old file and refuses overwrite or cross-directory output so relative paths remain valid.

New capabilities enter `narrated-project-v1.schema.json` and semantic validation first. Pipeline compatibility views may translate names such as `providers.tts → voice` and `transition_seconds → transition`, but adapters and providers must not define new project fields in those views.

## Adapter contract

Adapters declare whether they render flattened video or export an editable project and which RenderPlan features they preserve. Capability negotiation happens before execution. Unsupported fields produce an error or explicit loss report; configuration alone never proves that an Adapter ran.

OpenChatCut integration targets its public MCP/EditorCore command surface. The offline import plan is deterministic and reviewable, while actual application remains a connected-runtime action. The adapter never writes OpenChatCut's private project store.

## Skill distribution

The runtime repository and installable Skill have separate release boundaries. `skill/narrated-video/` contains only the discovery metadata, production decision rules, one-level references and a thin launcher. Build validation rejects development docs, tests, notebooks, provider workers, renderer source, dependencies, caches and media outputs.
