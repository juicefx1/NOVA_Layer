import {
  Callout,
  Divider,
  Grid,
  H1,
  H2,
  Pill,
  Row,
  Stack,
  Stat,
  Table,
  Text,
} from "cursor/canvas";

export default function ReleaseEngSprint1Plan() {
  return (
    <Stack gap={24} style={{ padding: 24, maxWidth: 1100 }}>
      <Stack gap={8}>
        <H1>Release Engineering Sprint 1</H1>
        <Text tone="secondary">
          Focus: Release Identity · Target: 1.0.0-rc1 / PEP 440 1.0.0rc1 · No CI · No runtime
          changes · 2026-07-30
        </Text>
        <Row gap={8} style={{ flexWrap: "wrap" }}>
          <Pill tone="warning">Identity incomplete</Pill>
          <Pill tone="deleted">No git commits</Pill>
          <Pill tone="warning">Live 0.1.5.dev0</Pill>
          <Pill tone="neutral">Seal 0.1.4 (legacy)</Pill>
        </Row>
      </Stack>

      <Callout tone="warning" title="Sprint 1 outcome">
        Establish a single reproducible identity for Release Candidate 1. Do not implement Release
        CI. Do not change application behavior. Align packaging version, freeze source revision,
        and define how release_manifest.json is produced and what fields it must carry.
      </Callout>

      <Grid columns={4} gap={12}>
        <Stat value="0.1.5.dev0" label="Live package" tone="warning" />
        <Stat value="none" label="Commit / tag" tone="danger" />
        <Stat value="0.1.4" label="Latest seal" tone="neutral" />
        <Stat value="rc1" label="Sprint target" tone="info" />
      </Grid>

      <Divider />

      <H2>Version alignment decision</H2>
      <Table
        headers={["Authority", "Form", "Action"]}
        rows={[
          ["21_RELEASE_INTEGRITY", "1.0.0-rcN", "Human / docs / git tag label"],
          ["PEP 440 / pyproject", "1.0.0rc1", "Canonical packaging string"],
          ["Release Notes / Checklist", "cite both if needed", "Same candidate"],
        ]}
      />

      <H2>Manifest generation (existing)</H2>
      <Text size="small">
        Tool: nova-release-candidate → create_release_candidate() in release_candidate.py → writes
        08_Release/nova-layer-&lt;version&gt;-&lt;sha12&gt;/release_manifest.json (format_version 3).
        Version is read from the wheel, not typed by hand.
      </Text>

      <H2>Sprint 1 plan (identity only)</H2>
      <Table
        headers={["#", "Task", "Out of scope"]}
        rows={[
          ["1", "Decide PEP440 string 1.0.0rc1 + tag convention", "CI pipeline"],
          ["2", "Bump pyproject version + description", "App/UI code"],
          ["3", "Initial commit + tag for rc1 tree", "Publish/CD"],
          ["4", "Doc inventory: rewrite 0.1.4/dev0 cites for rc1", "Seal execution (optional later)"],
          ["5", "Specify manifest identity fields (commit/tag)", "Implement CI stages"],
          ["6", "Identity verification checklist", "Runtime behavior"],
        ]}
      />
    </Stack>
  );
}
